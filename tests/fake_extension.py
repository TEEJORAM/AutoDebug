"""A fake AutoDebug extension speaking the real protocol, for Python tests.

It simulates one program as a list of executed lines: launching runs to the
first breakpoint, `step` moves one line, `continue` runs to the next breakpoint
or the end. `approve()` / `deny()` stand in for the developer's click.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Line:
    file: str
    line: int
    variables: dict = field(default_factory=dict)
    function: str = "polygon_area"


DEMO = (
    Line("geometry.py", 12, {"points": "[(2, 1), (3, 1), (3, 2), (2, 2)]", "total": "0.0"}),
    Line("geometry.py", 15, {"i": "0", "total": "0.0", "password": "'hunter2'"}),
    Line("geometry.py", 12, {"i": "0", "total": "-1.0"}),
    Line("geometry.py", 15, {"i": "1", "total": "-1.0"}),
    Line("geometry.py", 12, {"i": "1", "total": "2.0"}),
    Line("geometry.py", 15, {"i": "2", "total": "2.0"}),
    Line("geometry.py", 16, {"total": "4.0"}),
)
LAUNCH = [{"name": "Debug tests", "type": "debugpy", "request": "launch", "module": "unittest", "args": ["-v"]}]


class FakeExtension:
    def __init__(self, folder: Path, workspace: str, *, ide: str = "cursor", trace=DEMO, build_exit: int = 0,
                 launch=None, tasks=None, write: bool = True) -> None:
        self.folder = Path(folder)
        self.workspace = workspace
        self.ide = ide
        self.window = f"{ide}-fake-{secrets.token_hex(3)}"
        self.token = secrets.token_hex(32)
        self.trace = trace
        self.build_exit = build_exit
        self.launch = LAUNCH if launch is None else launch
        self.tasks = tasks or [{"label": "build", "command": "make"}]
        self.calls: list[tuple[str, dict]] = []
        self._cond = threading.Condition()
        self.session: dict | None = None
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
        data = {"protocol": 2, "port": self.port, "token": self.token, "window": self.window, "ide": self.ide,
                "folders": [self.workspace], "version": "0.2.0-fake", **overrides}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return path

    def approve(self) -> None:
        self._answer(True)

    def deny(self) -> None:
        self._answer(False)

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
            conn.sendall(json.dumps({"hello": "ok", "protocol": 2, "window": self.window}).encode() + b"\n")
            for line in reader:
                message = json.loads(line)
                conn.sendall(json.dumps(self._dispatch(message)).encode() + b"\n")
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

    # -- session --------------------------------------------------------------

    def _update(self, **changes) -> None:
        with self._cond:
            self.session.update(changes)
            self.session["version"] += 1
            self._cond.notify_all()

    def _snapshot(self) -> dict:
        s = self.session
        if s is None:
            return {"version": 0, "status": "none"}
        here = self.trace[s["pos"]] if s["status"] == "paused" else None
        return {"version": s["version"], "status": s["status"], "reason": s.get("reason"),
                "location": {"file": here.file, "line": here.line} if here else None,
                "exit_code": s.get("exit_code"), "message": s.get("message"),
                "steps_used": s["steps"], "max_steps": s["max_steps"], "build": s.get("build"),
                "breakpoints": [{"file": f, "line": n, "verified": True, "message": ""} for f, n in s["breakpoints"]]}

    def _need(self, *statuses) -> dict:
        if self.session is None:
            raise _Error("NOT_FOUND", "no debug session")
        if statuses and self.session["status"] not in statuses:
            raise _Error("NOT_PAUSED" if self.session["status"] == "running" else "BAD_REQUEST",
                         f"the session is {self.session['status']}")
        return self.session

    def _answer(self, approved: bool) -> None:
        s = self.session
        if s is None or s["status"] != "awaiting_approval":
            return
        if not approved:
            self._update(status="denied", reason="the developer did not approve")
            return
        if s["task"]:
            failed = self.build_exit != 0
            s["build"] = {"task": s["task"], "status": "failed" if failed else "succeeded", "exit_code": self.build_exit}
            if failed:
                self._update(status="build_failed", exit_code=self.build_exit, message="see the terminal")
                return
        s["pos"] = -1
        self._run_to_breakpoint("breakpoint")

    def _run_to_breakpoint(self, reason: str) -> None:
        s = self.session
        for pos in range(s["pos"] + 1, len(self.trace)):
            here = self.trace[pos]
            if (here.file, here.line) in s["breakpoints"]:
                s["pos"] = pos
                self._update(status="paused", reason=reason)
                return
        self._update(status="ended", reason="the program exited", exit_code=1)

    def op_info(self, args):
        return {"window": self.window, "ide": self.ide, "folders": [self.workspace], "version": "0.2.0-fake"}

    def op_targets(self, args):
        return {"folder": self.workspace,
                "launch": [{"name": c["name"], "type": c["type"], "request": c["request"],
                            "program": c.get("module"), "args": c.get("args", [])} for c in self.launch],
                "tasks": self.tasks}

    def op_start(self, args):
        if self.session and self.session["status"] not in ("ended", "denied", "build_failed"):
            raise _Error("BUSY", "a debug session is already active")
        if args.get("launch") not in {c["name"] for c in self.launch}:
            raise _Error("NOT_FOUND", f"no launch configuration named \"{args.get('launch')}\"")
        if args.get("task") and args["task"] not in {t["label"] for t in self.tasks}:
            raise _Error("NOT_FOUND", f"no task labelled \"{args['task']}\"")
        for b in args.get("breakpoints", []):
            if b["file"].startswith("..") or os.path.isabs(b["file"]):
                raise _Error("OUTSIDE_WORKSPACE", f"{b['file']} is outside the workspace")
        self.session = {"version": 0, "status": "awaiting_approval", "pos": -1, "steps": 0,
                        "max_steps": args.get("max_steps", 50), "task": args.get("task"), "args": args,
                        "breakpoints": [(b["file"], b["line"]) for b in args.get("breakpoints", [])]}
        self._update()
        return {"state": self._snapshot()}

    def op_state(self, args):
        with self._cond:
            if self.session and self.session["version"] <= args.get("since", 0) and args.get("wait_ms"):
                self._cond.wait(args["wait_ms"] / 1000)
        return {"state": self._snapshot()}

    def op_stack(self, args):
        s = self._need("paused")
        here = self.trace[s["pos"]]
        frames = [{"id": 1, "name": here.function, "file": here.file, "line": here.line},
                  {"id": 2, "name": "test_area_does_not_change_when_moved", "file": "test_geometry.py", "line": 18}]
        return {"frames": frames[: args.get("levels", 20)]}

    def op_variables(self, args):
        s = self._need("paused")
        values = self.trace[s["pos"]].variables if args.get("frame", 1) == 1 else {"self": "<test>"}
        names = args.get("names")
        chosen = [n for n in names if n in values] if names else list(values)
        return {"variables": [{"name": n, "type": "str", "value": values[n]} for n in chosen]}

    def op_step(self, args):
        s = self._need("paused")
        if s["steps"] >= s["max_steps"]:
            raise _Error("LIMIT", "the step limit is used up")
        s["steps"] += 1
        if s["pos"] + 1 >= len(self.trace):
            self._update(status="ended", reason="the program exited", exit_code=1)
        else:
            s["pos"] += 1
            self._update(status="paused", reason="step")
        return {"state": self._snapshot()}

    def op_continue(self, args):
        self._need("paused")
        self._update(status="running", reason=None)
        threading.Timer(0.05, self._run_to_breakpoint, args=("breakpoint",)).start()
        return {"state": self._snapshot()}

    def op_pause(self, args):
        self._need("running")
        return {"state": self._snapshot()}

    def op_breakpoints(self, args):
        s = self._need("starting", "running", "paused")
        remove = {(b["file"], b["line"]) for b in args.get("remove", [])}
        s["breakpoints"] = [b for b in s["breakpoints"] if b not in remove]
        for b in args.get("add", []):
            if (b["file"], b["line"]) not in s["breakpoints"]:
                s["breakpoints"].append((b["file"], b["line"]))
        self._update()
        return {"state": self._snapshot()}

    def op_stop(self, args):
        if self.session and self.session["status"] != "ended":
            self._update(status="ended", reason="stopped by the agent")
        return {"state": self._snapshot()}


class _Error(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message
