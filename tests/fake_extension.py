"""A fake AutoDebug extension speaking the real relay protocol, for Python tests
that run without Node.js. It plays VS Code's side of the Debug Adapter Protocol
against the scripted program in tests/fake_adapter.py, in-process.
`approve()` / `deny()` stand in for the developer's click.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
from pathlib import Path

from tests.fake_adapter import AdapterError, Program

LAUNCH = [{"name": "Debug tests", "type": "debugpy", "request": "launch", "module": "unittest", "args": ["-v"]}]
ALLOWED = {"threads", "stackTrace", "scopes", "variables", "next", "stepIn", "stepOut", "continue", "pause",
           "exceptionInfo", "setExceptionBreakpoints"}
STEPS = ("next", "stepIn", "stepOut")


class _Error(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class FakeExtension:
    def __init__(self, folder: Path, workspace: str, *, ide: str = "cursor", build_exit: int = 0, launch=None,
                 tasks=None, write: bool = True, editor_breakpoints=()) -> None:
        self.folder = Path(folder)
        self.workspace = workspace
        self.ide = ide
        self.window = f"{ide}-fake-{secrets.token_hex(3)}"
        self.token = secrets.token_hex(32)
        self.build_exit = build_exit
        self.launch = LAUNCH if launch is None else launch
        self.tasks = tasks or [{"label": "build", "command": "make"}]
        self.editor_breakpoints = list(editor_breakpoints)  # (file relative to the workspace, line)
        self.calls: list[tuple[str, dict]] = []
        self._cond = threading.Condition(threading.RLock())
        self.events: list[dict] = []
        self.seq = 0
        self.session: dict | None = None
        self.program: Program | None = None
        self._dap_seq = 1
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port = self._server.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()
        if write:
            self.write_file()

    # -- test controls -------------------------------------------------------

    def write_file(self, **overrides) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.folder, 0o700)
        path = self.folder / f"{self.window}.json"
        data = {"protocol": 4, "port": self.port, "token": self.token, "window": self.window, "ide": self.ide,
                "folders": [self.workspace], "version": "0.4.0-fake", **overrides}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return path

    def approve(self) -> None:
        with self._cond:
            s = self.session
            if s is None or s["phase"] != "awaiting_approval":
                return
            self._emit({"kind": "approval", "approved": True, "reason": "the developer clicked Approve"})
            self._run(s)

    def deny(self, reason: str = "the developer did not approve") -> None:
        with self._cond:
            s = self.session
            if s is not None and s["phase"] == "awaiting_approval":
                s["phase"] = "denied"
                self._emit({"kind": "approval", "approved": False, "reason": reason})

    def close(self) -> None:
        try:
            self._server.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._server.close()

    # -- server ----------------------------------------------------------------

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        reader = conn.makefile("rb")
        try:
            hello = json.loads(reader.readline() or b"{}")
            if hello.get("hello") != self.token:
                return
            conn.sendall(json.dumps({"hello": "ok", "protocol": 4, "window": self.window}).encode() + b"\n")
            for line in reader:
                conn.sendall(json.dumps(self._dispatch(json.loads(line))).encode() + b"\n")
        except (OSError, ValueError):
            pass
        finally:
            reader.close()
            conn.close()

    def _dispatch(self, message: dict) -> dict:
        op, args = message.get("op"), message.get("args") or {}
        self.calls.append((op, args))
        try:
            handler = getattr(self, f"op_{op}", None)
            if handler is None:
                raise _Error("BAD_REQUEST", f"unknown operation {op}")
            return {"id": message.get("id"), "ok": True, "result": handler(args)}
        except _Error as exc:
            return {"id": message.get("id"), "ok": False, "error": {"code": exc.code, "message": exc.message}}

    # -- VS Code's side of the Debug Adapter Protocol ------------------------------

    def _emit(self, event: dict) -> None:
        with self._cond:
            self.seq += 1
            self.events.append({"seq": self.seq, **event})
            self._cond.notify_all()

    def _from_adapter(self, message: dict) -> None:
        self._emit({"kind": "dap", "direction": "from_adapter", "message": message})
        if message.get("event") == "terminated" and self.session:
            self._ended(self.session, "the debug session ended")

    def _request(self, command: str, args: dict, forward: bool = False) -> dict:
        seq = self._dap_seq
        self._dap_seq += 1
        if forward:
            self._emit({"kind": "dap", "direction": "to_adapter",
                        "message": {"type": "request", "seq": seq, "command": command, "arguments": args}})
        body = self.program.handle(command, args)
        if command in ("initialize", "setBreakpoints", "setFunctionBreakpoints"):
            self._from_adapter({"type": "response", "request_seq": seq, "command": command, "success": True, "body": body})
        self.program.flush()
        return body

    def _lines(self) -> list[dict]:
        editor = [{"file": os.path.join(self.workspace, f), "line": n} for f, n in self.editor_breakpoints]
        return editor + self.session["breakpoints"]

    def _sync(self, files: set[str]) -> None:
        for file in sorted(files):
            lines = [b["line"] for b in self._lines() if b["file"] == file]
            self._request("setBreakpoints", {"source": {"path": file}, "breakpoints": [{"line": n} for n in lines]},
                          forward=True)

    def _run(self, s: dict) -> None:
        if s["task"]:
            s["phase"] = "building"
            self._emit({"kind": "build", "task": s["task"], "status": "running", "exit_code": None})
            if self.build_exit != 0:
                s["phase"] = "build_failed"
                self._emit({"kind": "build", "task": s["task"], "status": "failed", "exit_code": self.build_exit})
                return
            self._emit({"kind": "build", "task": s["task"], "status": "succeeded", "exit_code": 0})
        s["phase"] = "starting"
        self._emit({"kind": "starting"})
        self.program = Program(self.workspace, self._from_adapter, env={})
        self._request("initialize", {"clientID": "vscode", "adapterID": "fake"})
        self._request(s["launch"].get("request", "launch"), s["launch"])
        self._sync({b["file"] for b in self._lines()})
        self._request("setFunctionBreakpoints", {"breakpoints": [{"name": f["name"]} for f in s["functions"]]},
                      forward=True)
        s["phase"] = "debugging"
        self._emit({"kind": "started"})
        self._request("configurationDone", {})

    def _ended(self, s: dict, reason: str) -> None:
        if s["phase"] not in ("ended", "denied", "build_failed"):
            s["phase"] = "ended"
            self._emit({"kind": "ended", "reason": reason, "exit_code": None})

    # -- relay operations ------------------------------------------------------------

    def op_info(self, args):
        return {"window": self.window, "ide": self.ide, "folders": [self.workspace], "version": "0.4.0-fake",
                "platform": sys.platform, "debugger_types": ["debugpy"]}

    def op_workspace(self, args):
        return {"folder": self.workspace, "launch": self.launch, "tasks": self.tasks}

    def op_approve(self, args):
        with self._cond:
            if self.session and self.session["phase"] in ("awaiting_approval", "building", "starting", "debugging"):
                raise _Error("BUSY", "a debug session is already active")
            roots = [os.path.abspath(r) for r in [self.workspace, *args.get("source_folders", [])]]
            for b in args.get("breakpoints", []):
                full = os.path.abspath(b["file"])
                if not any(os.path.commonpath([r, full]) == r for r in roots):
                    raise _Error("OUTSIDE_WORKSPACE", f"{b['file']} is outside the approved folders")
            ids = [f"b{i}" for i, _ in enumerate(args.get("breakpoints", []), 1)]
            fids = [f"f{i}" for i, _ in enumerate(args.get("functions", []), 1)]
            self.session = {"phase": "awaiting_approval", "task": args.get("task"), "launch": args["launch"],
                            "args": args, "steps": 0, "max_steps": args.get("max_steps") or 100, "next": 100,
                            "breakpoints": [{"id": i, "file": b["file"], "line": b["line"]}
                                            for i, b in zip(ids, args.get("breakpoints", []))],
                            "functions": [{"id": i, "name": n} for i, n in zip(fids, args.get("functions", []))]}
            return {"session": 1, "breakpoint_ids": ids, "function_ids": fids}

    def op_events(self, args):
        since = int(args.get("since") or 0)
        with self._cond:
            if self.seq <= since and args.get("wait_ms"):
                self._cond.wait(args["wait_ms"] / 1000)
            events = [e for e in self.events if e["seq"] > since][:500]
            return {"events": events, "next": events[-1]["seq"] if events else min(since, self.seq),
                    "latest": self.seq, "dropped": False}

    def _live(self) -> dict:
        s = self.session
        if s is None or s["phase"] not in ("starting", "debugging"):
            raise _Error("NOT_FOUND", "no debug session is running")
        return s

    def op_dap(self, args):
        with self._cond:
            s = self._live()
            command = args.get("command")
            if command not in ALLOWED:
                raise _Error("BAD_REQUEST", f"the debugger request {command} is not allowed")
            if command in STEPS:
                if s["steps"] >= s["max_steps"]:
                    raise _Error("LIMIT", "the step limit is used up")
                s["steps"] += 1
            try:
                return {"body": self._request(command, args.get("arguments") or {})}
            except AdapterError as exc:
                if command in STEPS:
                    s["steps"] -= 1
                raise _Error("IDE_ERROR", str(exc)) from None

    def op_breakpoints(self, args):
        with self._cond:
            s = self._live()
            remove = set(args.get("remove", []))
            touched = {b["file"] for b in s["breakpoints"] if b["id"] in remove}
            s["breakpoints"] = [b for b in s["breakpoints"] if b["id"] not in remove]
            s["functions"] = [f for f in s["functions"] if f["id"] not in remove]
            ids, fids = [], []
            for b in args.get("add", []):
                s["next"] += 1
                ids.append(f"b{s['next']}")
                s["breakpoints"].append({"id": ids[-1], "file": b["file"], "line": b["line"]})
                touched.add(b["file"])
            for name in args.get("add_functions", []):
                s["next"] += 1
                fids.append(f"f{s['next']}")
                s["functions"].append({"id": fids[-1], "name": name})
            self._sync(touched)
            return {"breakpoint_ids": ids, "function_ids": fids}

    def op_editor_breakpoints(self, args):
        return {"breakpoints": [{"file": os.path.join(self.workspace, f), "line": n} for f, n in self.editor_breakpoints]}

    def op_notify(self, args):
        return {}

    def op_stop(self, args):
        with self._cond:
            if self.session:
                self._ended(self.session, str(args.get("reason") or "stopped by the agent"))
            return {}
