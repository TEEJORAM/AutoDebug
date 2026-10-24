"""A fake AutoDebug Bridge that speaks the real wire protocol (BR-11).

It listens on 127.0.0.1, writes a connection file like the extension does, and
simulates one program as a list of executed locations: launching runs to the
first planned breakpoint, `step` moves one location, `continue` runs to the
next breakpoint or to the end. Tests drive approval with `answer()`.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path

from autodebug.bridge.protocol import LOOPBACK, PROTOCOL_VERSION, ProtocolError, decode, encode
from autodebug.evidence import make_private_dir

DEMO_LAUNCH = {"name": "Debug tests", "type": "debugpy", "request": "launch", "module": "unittest", "args": ["-v"]}
DEMO_FILES = {"geometry.py": b"def polygon_area(points):\n    total = 0.0\n"}


@dataclass
class Location:
    file: str
    line: int
    variables: dict[str, str] = field(default_factory=dict)
    function: str = "polygon_area"


DEMO_TRACE = (
    Location("geometry.py", 12, {"points": "[(0, 0), (1, 0), (1, 1), (0, 1)]", "total": "0.0"}),
    Location("geometry.py", 15, {"i": "0", "total": "0.0", "password": "hunter2"}),
    Location("geometry.py", 12, {"i": "0", "total": "0.0"}),
    Location("geometry.py", 15, {"i": "1", "total": "0.0"}),
    Location("geometry.py", 15, {"i": "2", "total": "1.0"}),
    Location("geometry.py", 16, {"total": "2.0"}),
)


class FakeBridge:
    def __init__(
        self, bridges_folder: Path, workspace: str, *, ide: str = "vscode", window_id: str = "window-1",
        launch_configs: dict | None = None, tasks: dict | None = None, files: dict | None = None,
        trace: tuple[Location, ...] = DEMO_TRACE, build_result: tuple[int, list[str]] = (0, ["Build finished"]),
        bind: bool = True, write_file: bool = True,
    ) -> None:
        self.folder = Path(bridges_folder)
        self.workspace = workspace
        self.ide = ide
        self.window_id = window_id
        self.token = secrets.token_hex(32)
        self.launch_configs = {DEMO_LAUNCH["name"]: DEMO_LAUNCH} if launch_configs is None else launch_configs
        self.tasks = tasks or {}
        self.files = dict(DEMO_FILES if files is None else files)
        self.trace = trace
        self.build_result = build_result
        self.bind = bind
        self.calls: list[tuple[str, dict]] = []
        self.requests: list[dict] = []
        self.approvals: dict[str, dict] = {}
        self.ended = False
        self._position: int | None = None
        self._stop_count = 0
        self._breakpoints: set[tuple[str, int]] = set()
        self._build_polls = 0
        self._lock = threading.Lock()
        self._server = socket.create_server((LOOPBACK, 0))
        self.port = self._server.getsockname()[1]
        self._threads: list[threading.Thread] = []
        accept = threading.Thread(target=self._accept, daemon=True)
        accept.start()
        self._threads.append(accept)
        if write_file:
            self.write_connection_file()

    # -- test controls ----------------------------------------------------

    def connection_data(self) -> dict:
        return {
            "protocol": PROTOCOL_VERSION, "host": LOOPBACK, "port": self.port, "token": self.token,
            "window_id": self.window_id, "ide": self.ide, "workspace_folders": [self.workspace],
            "extension_version": "0.1.0-fake",
        }

    def write_connection_file(self) -> Path:
        make_private_dir(self.folder, exist_ok=True)
        path = self.folder / f"{self.window_id}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(self.connection_data(), handle)
        return path

    def answer(self, decision: str) -> None:
        """Simulate the developer clicking Approve or Deny on every pending request."""
        with self._lock:
            for request in self.approvals.values():
                if request["status"] == "pending":
                    request["status"] = "approved" if decision == "approve" else "denied"
                    if decision == "approve":
                        request["approval_id"] = secrets.token_hex(16)

    def close(self) -> None:
        try:
            self._server.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._server.close()

    # -- server -----------------------------------------------------------

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            thread = threading.Thread(target=self._serve, args=(conn,), daemon=True)
            thread.start()
            self._threads.append(thread)

    def _serve(self, conn: socket.socket) -> None:
        reader = conn.makefile("rb")
        try:
            hello = decode(reader.readline(1024 * 1024 + 1))
            if not secrets.compare_digest(str(hello.get("hello")), self.token) or hello.get("protocol") != PROTOCOL_VERSION:
                return  # BR-01-B: wrong token -> no reply, connection closed.
            conn.sendall(encode({"hello": "ok", "protocol": PROTOCOL_VERSION, "window_id": self.window_id}))
            while True:
                line = reader.readline(1024 * 1024 + 1)
                if not line:
                    return
                message = decode(line)
                conn.sendall(encode(self._dispatch(message)))
        except (OSError, ProtocolError):
            return
        finally:
            reader.close()
            conn.close()

    def _dispatch(self, message: dict) -> dict:
        op, args = message.get("op"), message.get("args") or {}
        self.calls.append((op, args))
        handler = getattr(self, f"op_{op}", None)
        try:
            if handler is None:
                raise _Error("CAPABILITY_UNSUPPORTED", f"unknown operation {op!r}")
            with self._lock:
                if op not in ("describe", "resolve_plan", "request_approval", "approval_status"):
                    self._require_approval(args)
                result = handler(args)
            return {"id": message.get("id"), "ok": True, "result": result}
        except _Error as exc:
            return {"id": message.get("id"), "ok": False, "error": {"code": exc.code, "message": exc.message}}

    def _require_approval(self, args: dict) -> None:
        approved = {r.get("approval_id") for r in self.approvals.values() if r["status"] == "approved"}
        if args.get("approval_id") not in approved:
            raise _Error("NOT_APPROVED", "no approval from the developer covers this operation")

    # -- operations -------------------------------------------------------

    def op_describe(self, args: dict) -> dict:
        return {"window_id": self.window_id, "ide": self.ide, "ide_version": "1.99.0-fake",
                "extension_version": "0.1.0-fake", "workspace_folders": [self.workspace]}

    def op_resolve_plan(self, args: dict) -> dict:
        launch = self.launch_configs.get(args.get("launch_configuration_name"))
        if launch is None:
            raise _Error("TARGET_MISMATCH", "launch configuration not found in .vscode/launch.json")
        task_label = args.get("build_task")
        task = None
        if task_label is not None:
            task = self.tasks.get(task_label)
            if task is None:
                raise _Error("TARGET_MISMATCH", "build task not found in .vscode/tasks.json")
        missing = [f for f in args.get("files", []) if f not in self.files]
        if missing:
            raise _Error("TARGET_MISMATCH", f"breakpoint file not found: {missing[0]}")
        return {"launch": launch, "task": task,
                "files": {f: base64.b64encode(self.files[f]).decode("ascii") for f in args.get("files", [])}}

    def op_request_approval(self, args: dict) -> dict:
        request_id = secrets.token_hex(8)
        self.requests.append(args)
        self.approvals[request_id] = {"status": "pending", "case_id": args.get("case_id"), "digest": args.get("digest")}
        return {"request_id": request_id}

    def op_approval_status(self, args: dict) -> dict:
        request = self.approvals.get(args.get("request_id"))
        if request is None:
            raise _Error("NOT_APPROVED", "unknown approval request")
        result = {"status": request["status"]}
        if request["status"] == "approved":
            result["approval_id"] = request["approval_id"]
        return result

    def op_build_start(self, args: dict) -> dict:
        self._build_polls = 0
        return {"status": "running"}

    def op_build_status(self, args: dict) -> dict:
        self._build_polls += 1
        if self._build_polls < 2:
            return {"status": "running"}
        code, lines = self.build_result
        return {"status": "succeeded" if code == 0 else "failed", "exit_code": code, "output_tail": lines}

    def op_launch(self, args: dict) -> dict:
        self._breakpoints = {(b["file"], b["line"]) for b in args.get("breakpoints", [])}
        self._position = -1
        self.ended = False
        self._run_to_breakpoint()
        return {"debug_session_id": "dap-session-1", "pid": 4242, "process_start_id": "start-" + secrets.token_hex(4),
                "executable": "python"}

    def op_breakpoints(self, args: dict) -> dict:
        return {"results": [{"file": f, "line": line, "bound": self.bind, "message": "" if self.bind else "unverified"}
                            for f, line in sorted(self._breakpoints)]}

    def op_stop_state(self, args: dict) -> dict:
        if self.ended or self._position is None:
            return {"state": "ended"}
        if self._position < 0:
            return {"state": "running"}
        here = self.trace[self._position]
        planned = (here.file, here.line) in self._breakpoints and self._reason == "breakpoint"
        return {
            "state": "paused", "stop_id": f"stop-{self._stop_count}", "reason": self._reason,
            "generation": self._stop_count, "location": {"file": here.file, "line": here.line},
            "planned_breakpoint": {"file": here.file, "line": here.line} if planned else None,
        }

    def op_stack(self, args: dict) -> dict:
        here = self._paused()
        frames = [{"frame": "1", "name": here.function, "file": here.file, "line": here.line},
                  {"frame": "2", "name": "test_area_does_not_change_when_moved", "file": "test_geometry.py", "line": 18}]
        return {"frames": frames[: args.get("levels", 20)]}

    def op_variables(self, args: dict) -> dict:
        here = self._paused()
        if args.get("frame_id") != "1":
            return {"variables": {}} if args.get("names") is not None else {"names": []}
        if args.get("names") is None:
            return {"names": [{"name": n, "type": "str"} for n in here.variables]}
        return {"variables": {n: here.variables[n] for n in args["names"] if n in here.variables}}

    def op_step(self, args: dict) -> dict:
        self._paused()
        self._advance("step")
        return {}

    def op_continue(self, args: dict) -> dict:
        self._paused()
        self._run_to_breakpoint()
        return {}

    def op_end(self, args: dict) -> dict:
        self.ended = True
        return {}

    # -- simulation -------------------------------------------------------

    def _paused(self) -> Location:
        if self.ended or self._position is None or self._position < 0:
            raise _Error("NOT_PAUSED", "the program is not paused")
        return self.trace[self._position]

    def _advance(self, reason: str) -> None:
        self._position += 1
        if self._position >= len(self.trace):
            self.ended = True
            return
        self._reason = reason
        self._stop_count += 1

    def _run_to_breakpoint(self) -> None:
        while True:
            self._position += 1
            if self._position >= len(self.trace):
                self.ended = True
                return
            here = self.trace[self._position]
            if (here.file, here.line) in self._breakpoints:
                self._reason = "breakpoint"
                self._stop_count += 1
                return


class _Error(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message
