"""The Autodebug service: one process per user that owns the debug session (docs/design.md, "The service").

Every agent reaches the same session through it: the MCP server (`autodebug serve`, started by
Cursor, VS Code or Visual Studio) and the command line (`autodebug run <tool> ...`), which any agent
with a terminal can use when its app does not show the MCP tools. The session and the report's
timeline live here, so they survive an MCP server being restarted or dropped by the IDE.

Protocol: one JSON object per line over TCP on 127.0.0.1, every request carrying the token from
`hub.json` in the state folder (readable only by this user). The first client that finds no service
starts one in the background; it exits after IDLE_SECONDS without calls while no session is open.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

from autodebug import __version__
from autodebug.connection import state_folder
from autodebug.tools import Debugger

_LOG = logging.getLogger("autodebug")
IDLE_SECONDS = 30 * 60
MAX_LINE = 1024 * 1024
CALL_TIMEOUT = 180  # longer than any tool's own wait (55 s) plus the IDE's answer
_FINISHED = ("ended", "denied", "build_failed", "none")


class ServiceError(Exception):
    """The service could not be reached or started; the message says why and what to do."""


def hub_file() -> Path:
    return state_folder() / "hub.json"


_CODE: list[str] = []


def code_id() -> str:
    """A fingerprint of this Autodebug's Python code, so a service left running from before an update
    (`git pull`, same version number) is replaced instead of answering with the old code."""
    if not _CODE:
        digest = hashlib.sha256()
        for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
            digest.update(path.name.encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n"))
        _CODE.append(digest.hexdigest()[:16])
    return _CODE[0]


# -- the service ---------------------------------------------------------------------------


class Hub:
    def __init__(self, debugger: Debugger | None = None, idle_seconds: float = IDLE_SECONDS,
                 info_file: Path | None = None) -> None:
        self.debugger = debugger or Debugger()
        self.idle_seconds = idle_seconds
        self.info_file = info_file or hub_file()
        self.token = secrets.token_hex(24)
        self.code = code_id()
        self.last_call = time.monotonic()
        self._tool_lock = threading.Lock()  # one debugger action at a time, whoever asks
        hub = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                line = self.rfile.readline(MAX_LINE + 1)
                if not line or len(line) > MAX_LINE:
                    return
                reply = hub.answer(line)
                with contextlib.suppress(OSError):
                    self.wfile.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")

        class TCP(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = False

        self.server = TCP(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]

    def busy(self) -> bool:
        """Whether a debug session is open, so the service must not exit or be replaced."""
        status = (self.debugger._last_status or ("none",))[0]
        return self.debugger.connection is not None and status not in _FINISHED

    def answer(self, line: bytes) -> dict:
        try:
            request = json.loads(line)
        except ValueError:
            return {"error": "BAD_REQUEST", "message": "not JSON"}
        if not isinstance(request, dict) or not hmac.compare_digest(str(request.get("token", "")), self.token):
            return {"error": "BAD_TOKEN", "message": "wrong token"}
        op = request.get("op")
        if op == "ping":
            return {"ok": True, "version": __version__, "code": self.code, "busy": self.busy(), "pid": os.getpid()}
        if op == "shutdown":
            if self.busy() and not request.get("force"):
                return {"ok": False, "busy": True}
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return {"ok": True}
        if op != "call":
            return {"error": "BAD_REQUEST", "message": f"unknown op {op}"}
        from autodebug.mcp_server import TOOLS, argument_problem, call_tool

        name, arguments = request.get("name"), request.get("arguments") or {}
        if name not in TOOLS:
            return {"result": {"error": "BAD_REQUEST", "message": f"unknown tool {name}"}, "is_error": True}
        problem = argument_problem(arguments, TOOLS[name][1])
        if problem:
            return {"result": {"error": "BAD_REQUEST", "message": f"{name}: {problem}"}, "is_error": True}
        self.last_call = time.monotonic()
        with self._tool_lock:
            result, is_error = call_tool(self.debugger, name, arguments)
        self.last_call = time.monotonic()
        return {"result": result, "is_error": is_error}

    def _write_info(self) -> None:
        self.info_file.parent.mkdir(parents=True, exist_ok=True)
        info = {"port": self.port, "token": self.token, "pid": os.getpid(), "version": __version__, "code": self.code}
        temporary = self.info_file.with_name(f"hub-{os.getpid()}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(info, handle)
        os.replace(temporary, self.info_file)

    def _remove_info(self) -> None:
        try:
            if json.loads(self.info_file.read_text(encoding="utf-8")).get("pid") == os.getpid():
                self.info_file.unlink()
        except (OSError, ValueError):
            pass

    def _watch_idle(self) -> None:
        while True:
            time.sleep(min(30.0, max(0.05, self.idle_seconds / 4)))
            if time.monotonic() - self.last_call > self.idle_seconds and not self.busy():
                _LOG.info("idle; the Autodebug service exits")
                self.server.shutdown()
                return

    def serve(self) -> None:
        self._write_info()
        threading.Thread(target=self._watch_idle, daemon=True).start()
        try:
            self.server.serve_forever(poll_interval=0.2)
        finally:
            self._remove_info()
            self.server.server_close()
            self.debugger.close()


# -- clients ---------------------------------------------------------------------------------


def _read_info() -> dict | None:
    try:
        info = json.loads(hub_file().read_text(encoding="utf-8"))
        return info if isinstance(info.get("port"), int) and isinstance(info.get("token"), str) else None
    except (OSError, ValueError):
        return None


def _request(info: dict, request: dict, timeout: float) -> dict:
    with socket.create_connection(("127.0.0.1", info["port"]), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(json.dumps({**request, "token": info["token"]}).encode("utf-8") + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > 64 * MAX_LINE:
                raise OSError("reply too long")
    if not data:
        raise OSError("the service closed the connection")
    return json.loads(data)


def _ping(info: dict | None) -> dict | None:
    if not info:
        return None
    try:
        reply = _request(info, {"op": "ping"}, 3)
    except (OSError, ValueError):
        return None
    return reply if reply.get("ok") else None


#: Background services this process started. Kept so each one is reaped once it exits (not left as a zombie or
#: reported as a leaked process); the service itself outlives this process.
_started: list[subprocess.Popen] = []


def reap(wait_seconds: float = 0) -> None:
    """Collect the exit of background services this process started that have ended (or end within the wait)."""
    for process in list(_started):
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(wait_seconds)
            _started.remove(process)


def _start_process() -> None:
    """Start `autodebug hub` in the background, detached from the caller (an IDE may kill its MCP servers)."""
    reap()
    package_parent = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (package_parent, env.get("PYTHONPATH")) if p)
    folder = state_folder()
    folder.mkdir(parents=True, exist_ok=True)
    log = open(folder / "hub.log", "ab")  # noqa: SIM115 (handed to the child process)
    options: dict = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": log, "env": env, "close_fds": True}
    command = [sys.executable, "-m", "autodebug", "hub"]
    try:
        if os.name == "nt":
            flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            try:
                process = subprocess.Popen(command, creationflags=flags | 0x01000000, **options)  # BREAKAWAY_FROM_JOB
            except OSError:
                process = subprocess.Popen(command, creationflags=flags, **options)
        else:
            process = subprocess.Popen(command, start_new_session=True, **options)
        _started.append(process)
    finally:
        log.close()


def connect_service(start: bool = True, wait_seconds: float = 15) -> dict:
    """The running service's connection info, starting it (or replacing an idle older version) if needed."""
    info = _read_info()
    alive = _ping(info)
    if alive and (alive.get("version"), alive.get("code")) != (__version__, code_id()) and not alive.get("busy"):
        with contextlib.suppress(OSError, ValueError):
            _request(info, {"op": "shutdown"}, 3)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _ping(info):
            time.sleep(0.1)
        alive = None
    if alive:
        return info
    if not start:
        raise ServiceError("the Autodebug service is not running")
    _start_process()
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        info = _read_info()
        if _ping(info):
            return info
        time.sleep(0.1)
    raise ServiceError(f"the Autodebug service did not start; see {state_folder() / 'hub.log'}")


def call(name: str, arguments: dict, timeout: float = CALL_TIMEOUT) -> tuple[dict, bool]:
    """Run one tool in the shared service: (result, is_error). Raises ServiceError if it cannot be reached."""
    info = connect_service()
    try:
        reply = _request(info, {"op": "call", "name": name, "arguments": arguments}, timeout)
    except (OSError, ValueError) as exc:
        raise ServiceError(f"lost the Autodebug service during {name}: {exc}") from exc
    if "result" not in reply:
        raise ServiceError(f"the Autodebug service refused the call: {reply.get('message') or reply}")
    return reply["result"], bool(reply.get("is_error"))


def status() -> dict | None:
    """{version, busy, pid} of the running service, or None."""
    return _ping(_read_info())
