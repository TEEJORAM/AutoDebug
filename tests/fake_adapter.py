"""A scripted debug adapter: geometry.py's loop for a moved unit square, over the
Debug Adapter Protocol. Tests run it as a subprocess (`python fake_adapter.py
<workspace>`, stdio, Content-Length framing) or in-process through `Program`.

Environment flags (set by the tests) change its behaviour:
HARNESS_LATE_BP=1        breakpoints bind only after the program "loads"
HARNESS_BP_MESSAGE=text  breakpoints stay unbound with this message
HARNESS_EXCEPTION=1      the first stop is an exception
HARNESS_STEP_FAIL=1      step requests fail
HARNESS_STACK_THROW=1    stackTrace fails
HARNESS_SLOW_STACK=ms    stackTrace takes this long
HARNESS_STOP_THEN_CONTINUE=1  continue reports a stop and at once a resume
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable

TRACE = [
    (12, {"points": "[(2, 1), (3, 1), (3, 2), (2, 2)]", "total": "0.0"}),
    (15, {"i": "0", "total": "0.0", "password": "'hunter2'"}),
    (12, {"i": "0", "total": "-1.0"}),
    (15, {"i": "1", "total": "-1.0"}),
    (12, {"i": "1", "total": "2.0"}),
    (15, {"i": "2", "total": "2.0"}),
    (16, {"i": "2", "total": "4.0"}),
]
CHILDREN = {
    9: [{"name": "Point", "value": "tuple[float, float]", "type": "GenericAlias"}],
    20: [{"name": "0", "value": "(2, 1)", "type": "tuple"}, {"name": "[2]", "value": "(3, 2)", "type": "tuple"}],
    21: [{"name": "api_token", "value": "secret-token-value", "type": "str"}],
    23: [{"name": "note", "value": "visible-child", "type": "str"}],
    30: [{"name": "verts", "value": "list", "type": "list", "variablesReference": 31}],
    31: [{"name": "2", "value": "Vert", "type": "Vert", "variablesReference": 32}, {"name": "[0]", "value": "Vert0", "type": "Vert"}],
    32: [{"name": "co", "value": "(1, 2, 3)", "type": "Vector"}],
}
EXTRA = [
    {"name": "points", "value": "list", "type": "list", "variablesReference": 20},
    {"name": "settings", "value": "dict", "type": "dict", "variablesReference": 21},
    {"name": "credentials", "value": "dict", "type": "dict", "variablesReference": 23},
    {"name": "mesh", "value": "Mesh", "type": "Mesh", "variablesReference": 30},
]


class AdapterError(Exception):
    pass


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class Program:
    """The scripted program. `emit(message)` receives every event it sends."""

    def __init__(self, workspace: str, emit: Callable[[dict], None], env=os.environ) -> None:
        self.workspace = workspace
        self.emit = emit
        self.env = env
        self.pos = -1
        self.lines: dict[str, list[int]] = {}
        self.placed: list[dict] = []
        self.after: list[Callable[[], None]] = []
        self.exception_sent = False
        self.done = False
        self.next_id = 100

    def flag(self, name: str) -> str:
        return self.env.get(name, "")

    def event(self, event: str, body: dict | None = None) -> None:
        self.emit({"type": "event", "event": event, "body": body or {}})

    def file(self) -> str:
        return os.path.join(self.workspace, "geometry.py")

    def here(self) -> tuple[int, dict]:
        return TRACE[self.pos] if 0 <= self.pos < len(TRACE) else TRACE[-1]

    def flush(self) -> None:
        """Run what happens after a response has been sent."""
        while self.after:
            self.after.pop(0)()

    def run(self) -> None:
        stops = self.lines.get(_key(self.file()), [])
        self.pos += 1
        while self.pos < len(TRACE):
            if TRACE[self.pos][0] in stops:
                exception = self.flag("HARNESS_EXCEPTION") == "1" and not self.exception_sent
                self.exception_sent = True
                self.event("stopped", {"reason": "exception" if exception else "breakpoint", "threadId": 1})
                return
            self.pos += 1
        self.finish()

    def finish(self) -> None:
        if self.done:
            return
        self.done = True
        self.event("output", {"category": "stderr",
                              "output": "FAIL: test_area_does_not_change_when_moved\nAssertionError: 2.0 != 1.0\n"})
        self.event("exited", {"exitCode": 1})
        self.event("terminated")

    def handle(self, command: str, args: dict) -> dict:
        handler = getattr(self, f"do_{command}", None)
        if handler is None:
            raise AdapterError(f"the scripted adapter has no {command}")
        return handler(args or {}) or {}

    # -- requests ------------------------------------------------------------------

    def do_initialize(self, args):
        self.after.append(lambda: self.event("initialized"))
        return {"supportsConfigurationDoneRequest": True, "supportsFunctionBreakpoints": True,
                "supportsExceptionInfoRequest": True, "exceptionBreakpointFilters": [
                    {"filter": "raised", "label": "Raised Exceptions", "default": False},
                    {"filter": "uncaught", "label": "Uncaught Exceptions", "default": True}]}

    def do_launch(self, args):
        return {}

    do_attach = do_launch

    def do_setBreakpoints(self, args):
        path = (args.get("source") or {}).get("path", "")
        lines = [b.get("line") for b in args.get("breakpoints") or []]
        self.lines[_key(path)] = lines
        late, message = self.flag("HARNESS_LATE_BP") == "1", self.flag("HARNESS_BP_MESSAGE")
        answer = []
        for line in lines:
            bp = {"id": self.next_id, "verified": not late and not message, "line": line}
            if message:
                bp["message"] = message
            self.next_id += 1
            self.placed.append(bp)
            answer.append(bp)
        return {"breakpoints": answer}

    def do_setFunctionBreakpoints(self, args):
        return {"breakpoints": [{"verified": False, "message": "not supported by the scripted program"}
                                for _ in args.get("breakpoints") or []]}

    def do_setExceptionBreakpoints(self, args):
        return {}

    def do_configurationDone(self, args):
        def go():
            if self.flag("HARNESS_LATE_BP") == "1":
                for bp in self.placed:
                    self.event("breakpoint", {"reason": "changed", "breakpoint": {"id": bp["id"], "verified": True,
                                                                                  "line": bp["line"]}})
            self.event("process", {"name": "python", "systemProcessId": 4242})
            self.run()
        self.after.append(go)
        return {}

    def do_threads(self, args):
        return {"threads": [{"id": 1, "name": "main"}, {"id": 2, "name": "worker"}]}

    def do_stackTrace(self, args):
        if self.flag("HARNESS_STACK_THROW") == "1":
            raise AdapterError("stack trace failed")
        if self.flag("HARNESS_SLOW_STACK"):
            time.sleep(int(self.flag("HARNESS_SLOW_STACK")) / 1000)
        frames = [{"id": 1, "name": "polygon_area", "source": {"path": self.file()}, "line": self.here()[0]},
                  {"id": 2, "name": "test_area_does_not_change_when_moved",
                   "source": {"path": os.path.join(self.workspace, "test_geometry.py")}, "line": 18}]
        return {"stackFrames": frames[: args.get("levels") or 20]}

    def do_scopes(self, args):
        return {"scopes": [{"name": "Locals", "variablesReference": 7 if args.get("frameId") == 1 else 8, "expensive": False},
                           {"name": "Globals", "variablesReference": 9, "expensive": False}]}

    def do_variables(self, args):
        reference = args.get("variablesReference")
        if reference in CHILDREN:
            return {"variables": CHILDREN[reference]}
        if reference != 7:
            return {"variables": [{"name": "self", "value": "<test>", "type": "Test"}]}
        return {"variables": [{"name": n, "value": v, "type": "str"} for n, v in self.here()[1].items()] + EXTRA}

    def do_next(self, args):
        if self.flag("HARNESS_STEP_FAIL") == "1":
            raise AdapterError("adapter rejected the step")

        def go():
            self.pos += 1
            if self.pos >= len(TRACE):
                self.finish()
            else:
                self.event("stopped", {"reason": "step", "threadId": 1})
        self.after.append(go)
        return {}

    do_stepIn = do_stepOut = do_next

    def do_continue(self, args):
        def go():
            if self.flag("HARNESS_STOP_THEN_CONTINUE") == "1":
                self.pos = min(self.pos + 1, len(TRACE) - 1)
                self.event("stopped", {"reason": "breakpoint", "threadId": 1})
                self.event("continued", {"threadId": 1})
            else:
                self.run()
        self.after.append(go)
        return {"allThreadsContinued": True}

    def do_pause(self, args):
        self.after.append(lambda: self.event("stopped", {"reason": "pause", "threadId": 1}))
        return {}

    def do_exceptionInfo(self, args):
        return {"exceptionId": "AssertionError", "description": "2.0 != 1.0", "breakMode": "always"}

    def do_disconnect(self, args):
        def go():
            if not self.done:
                self.done = True
                self.event("terminated")
        self.after.append(go)
        return {}


def main() -> None:
    workspace = sys.argv[1]
    lock = threading.Lock()
    out = sys.stdout.buffer
    seq = [1]

    def send(message: dict) -> None:
        with lock:
            message = {**message, "seq": seq[0]}
            seq[0] += 1
            body = json.dumps(message).encode("utf-8")
            out.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
            out.flush()

    program = Program(workspace, send)
    stdin = sys.stdin.buffer
    while True:
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            byte = stdin.read(1)
            if not byte:
                return
            header += byte
        length = int(header.split(b"Content-Length:")[1].split(b"\r\n")[0])
        request = json.loads(stdin.read(length))
        command = request.get("command")
        try:
            body, ok, error = program.handle(command, request.get("arguments") or {}), True, None
        except AdapterError as exc:
            body, ok, error = {}, False, str(exc)
        response = {"type": "response", "request_seq": request.get("seq"), "command": command, "success": ok, "body": body}
        if error:
            response["message"] = error
        send(response)
        program.flush()
        if command == "disconnect":
            return


if __name__ == "__main__":
    main()
