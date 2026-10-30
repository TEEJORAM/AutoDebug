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
HARNESS_FLOOD=n          print n lines of output before the program reaches the loop
HARNESS_LAUNCHER=1       a launcher session (like the JavaScript debugger's): it runs nothing itself
HARNESS_NO_SOURCE=1      the top frame has no file, only code the debugger holds (sourceReference 77)
HARNESS_PLAIN=1          offer only the basic capabilities (no paging, watchpoints, modules, ...)

Requests that only record what they were sent print it as program output ("sent stepIn {...}"), so tests can check
what reached the debugger.
"""

from __future__ import annotations

import base64
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
    {"name": "points", "value": "list", "type": "list", "variablesReference": 20, "memoryReference": "0x2000"},
    {"name": "items", "value": "list of 10000", "type": "list", "variablesReference": 40, "indexedVariables": 10000},
    {"name": "buffer", "value": "bytes", "type": "bytes", "variablesReference": 0, "memoryReference": "0x3000"},
    {"name": "settings", "value": "dict", "type": "dict", "variablesReference": 21},
    {"name": "credentials", "value": "dict", "type": "dict", "variablesReference": 23},
    {"name": "mesh", "value": "Mesh", "type": "Mesh", "variablesReference": 30},
]


MEMORY = {0x2000: bytes(range(2, 66)), 0x3000: b"key=sk-live-abcdefghijklmnopqrstuvwx" + bytes(28)}
SOURCE_77 = "\n".join(f"// generated line {n}" for n in range(1, 31))


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
        self.options: dict[str, dict[int, dict]] = {}
        self.hits: dict[int, int] = {}
        self.watched: list[str] = []
        self.stops: list[int] = []  # positions where the program stopped, for running backwards

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

    def say(self, text: str) -> None:
        self.event("output", {"category": "console", "output": text + "\n"})

    def stop(self, body: dict) -> None:
        self.stops.append(self.pos)
        self.event("stopped", {"threadId": 1, **body})

    def changed_watch(self) -> str | None:
        if self.pos <= 0:
            return None
        before, after = TRACE[self.pos - 1][1], TRACE[self.pos][1]
        return next((n for n in self.watched if n in after and before.get(n) != after.get(n)), None)

    def breakpoint_here(self) -> bool:
        """Whether a breakpoint stops the program at this position: hit conditions count, log points print."""
        line, values = TRACE[self.pos]
        options = self.options.get(_key(self.file()), {}).get(line)
        if options is None:
            return False
        self.hits[line] = self.hits.get(line, 0) + 1
        hit = options.get("hitCondition")
        if hit:
            op, count = ("".join(c for c in hit if not c.isdigit()).strip() or "=="), int("".join(c for c in hit if c.isdigit()))
            if not {"==": self.hits[line] == count, ">=": self.hits[line] >= count, ">": self.hits[line] > count,
                    "%": self.hits[line] % count == 0}.get(op, self.hits[line] == count):
                return False
        if options.get("logMessage"):
            self.say(options["logMessage"].format_map(dict(values.items()) | {"line": line}))
            return False
        return True

    def run(self) -> None:
        self.pos += 1
        while self.pos < len(TRACE):
            name = self.changed_watch()
            if name:
                self.stop({"reason": "data breakpoint", "description": f"{name} changed",
                           "hitBreakpointIds": [900]})
                return
            if self.breakpoint_here():
                exception = self.flag("HARNESS_EXCEPTION") == "1" and not self.exception_sent
                self.exception_sent = True
                self.stop({"reason": "exception" if exception else "breakpoint"})
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
        basic = {"supportsConfigurationDoneRequest": True, "supportsFunctionBreakpoints": True,
                 "supportsExceptionInfoRequest": True, "exceptionBreakpointFilters": [
                     {"filter": "raised", "label": "Raised Exceptions", "default": False, "supportsCondition": True},
                     {"filter": "uncaught", "label": "Uncaught Exceptions", "default": True}]}
        if self.flag("HARNESS_PLAIN") == "1":
            return basic
        return {**basic, **dict.fromkeys(("supportsHitConditionalBreakpoints", "supportsLogPoints", "supportsDataBreakpoints", "supportsModulesRequest", "supportsLoadedSourcesRequest", "supportsDisassembleRequest", "supportsReadMemoryRequest", "supportsBreakpointLocationsRequest", "supportsStepBack", "supportsSteppingGranularity", "supportsSingleThreadExecutionRequests", "supportsStepInTargetsRequest", "supportsValueFormattingOptions", "supportsExceptionOptions", "supportsExceptionFilterOptions", "supportsConditionalBreakpoints"), True)}

    def do_launch(self, args):
        return {}

    do_attach = do_launch

    def do_setBreakpoints(self, args):
        path = (args.get("source") or {}).get("path", "")
        lines = [b.get("line") for b in args.get("breakpoints") or []]
        self.lines[_key(path)] = lines
        self.options[_key(path)] = {b.get("line"): b for b in args.get("breakpoints") or []}
        extra = [b for b in args.get("breakpoints") or [] if set(b) - {"line"}]
        if extra:
            self.say(f"sent setBreakpoints {json.dumps(extra, sort_keys=True)}")
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
        if args.get("filterOptions") or args.get("exceptionOptions"):
            self.say(f"sent setExceptionBreakpoints {json.dumps(args, sort_keys=True)}")
        return {}

    def do_configurationDone(self, args):
        if self.flag("HARNESS_LAUNCHER") == "1":
            return {}

        def go():
            if self.flag("HARNESS_LATE_BP") == "1":
                for bp in self.placed:
                    self.event("breakpoint", {"reason": "changed", "breakpoint": {"id": bp["id"], "verified": True,
                                                                                  "line": bp["line"]}})
            self.event("process", {"name": "python", "systemProcessId": 4242})
            if self.flag("HARNESS_PLAIN") != "1":
                self.event("thread", {"reason": "started", "threadId": 2})
                self.event("module", {"reason": "new", "module": {"id": 1, "name": "geometry", "path": self.file(),
                                                                  "symbolStatus": "Symbols loaded."}})
                self.event("progressStart", {"progressId": "p1", "title": "Loading symbols", "message": "geometry"})
            for n in range(int(self.flag("HARNESS_FLOOD") or 0)):
                self.event("output", {"category": "stdout", "output": f"loading part {n}\n"})
            self.run()
        self.after.append(go)
        return {}

    def do_threads(self, args):
        if self.flag("HARNESS_LAUNCHER") == "1":
            return {"threads": []}
        return {"threads": [{"id": 1, "name": "main"}, {"id": 2, "name": "worker"}]}

    def do_stackTrace(self, args):
        if self.flag("HARNESS_STACK_THROW") == "1":
            raise AdapterError("stack trace failed")
        if self.flag("HARNESS_SLOW_STACK"):
            time.sleep(int(self.flag("HARNESS_SLOW_STACK")) / 1000)
        top = ({"name": "<generated>", "sourceReference": 77} if self.flag("HARNESS_NO_SOURCE") == "1"
               else {"path": self.file()})
        frames = [{"id": 1, "name": "polygon_area", "source": top, "line": self.here()[0],
                   "instructionPointerReference": "0x1010", "moduleId": 1},
                  {"id": 2, "name": "test_area_does_not_change_when_moved",
                   "source": {"path": os.path.join(self.workspace, "test_geometry.py")}, "line": 18}]
        return {"stackFrames": frames[: args.get("levels") or 20]}

    def do_scopes(self, args):
        return {"scopes": [{"name": "Locals", "variablesReference": 7 if args.get("frameId") == 1 else 8, "expensive": False},
                           {"name": "Globals", "variablesReference": 9, "expensive": False},
                           {"name": "Registers", "variablesReference": 50, "expensive": True}]}

    def do_variables(self, args):
        reference = args.get("variablesReference")
        hex_values = bool((args.get("format") or {}).get("hex"))
        if reference == 50:
            return {"variables": [{"name": "rip", "value": "0x1010", "type": "pointer"},
                                  {"name": "rsp", "value": "0x7ffc0000", "type": "pointer"}]}
        if reference == 40:  # items: 10000 squares, paged
            start, count = int(args.get("start") or 0), int(args.get("count") or 10000)
            if args.get("filter") != "indexed" and "start" not in args:
                raise AdapterError("the scripted program pages items: pass start and count")
            return {"variables": [{"name": f"[{i}]", "value": hex(i * i) if hex_values else str(i * i), "type": "int"}
                                  for i in range(start, min(start + count, 10000))]}
        if reference in CHILDREN:
            return {"variables": CHILDREN[reference]}
        if reference != 7:
            return {"variables": [{"name": "self", "value": "<test>", "type": "Test"}]}

        def shown(value):
            return hex(int(value)) if hex_values and value.isdigit() else value
        return {"variables": [{"name": n, "value": shown(v), "type": "str"} for n, v in self.here()[1].items()] + EXTRA}

    # -- watchpoints, modules, code without a file, machine code, memory ---------------------

    def do_dataBreakpointInfo(self, args):
        name = args.get("name")
        if args.get("variablesReference") == 7 and name in ("total", "i"):
            return {"dataId": name, "description": f"{name} (8 bytes)", "accessTypes": ["write", "read", "readWrite"]}
        return {"dataId": None, "description": f"{name} is not in memory the debugger can watch"}

    def do_setDataBreakpoints(self, args):
        self.watched = [b["dataId"] for b in args.get("breakpoints") or []]
        return {"breakpoints": [{"id": 900 + n, "verified": True} for n, _ in enumerate(self.watched)]}

    def do_modules(self, args):
        return {"modules": [{"id": 1, "name": "geometry", "path": self.file(), "symbolStatus": "Symbols loaded."},
                            {"id": 2, "name": "libm.so.6", "path": "/usr/lib/libm.so.6", "version": "2.39",
                             "symbolStatus": "Symbols not found.", "isOptimized": True}], "totalModules": 2}

    def do_loadedSources(self, args):
        return {"sources": [{"name": "geometry.py", "path": self.file()}, {"name": "<generated>", "sourceReference": 77}]}

    def do_source(self, args):
        if int(args.get("sourceReference") or 0) != 77:
            raise AdapterError("no such source")
        return {"content": SOURCE_77 + "\napi_key = 'ghp_" + "a" * 36 + "'"}

    def do_disassemble(self, args):
        base = int(args["memoryReference"], 16) + 4 * int(args.get("instructionOffset") or 0)
        return {"instructions": [{"address": hex(base + 4 * n), "instruction": f"add x{n % 8}, x{n % 8}, #1",
                                  **({"symbol": "polygon_area"} if base + 4 * n == 0x1010 else {})}
                                 for n in range(int(args.get("instructionCount") or 1))]}

    def do_readMemory(self, args):
        start = int(args["memoryReference"], 16) + int(args.get("offset") or 0)
        block = next(((base, data) for base, data in MEMORY.items() if base <= start < base + len(data)), None)
        if block is None:
            return {"address": hex(start), "unreadableBytes": int(args.get("count") or 0)}
        base, data = block
        chunk = data[start - base:start - base + int(args.get("count") or 0)]
        return {"address": hex(start), "data": base64.b64encode(chunk).decode()}

    def do_breakpointLocations(self, args):
        return {"breakpoints": [{"line": n} for n in (12, 15, 16) if args.get("line") <= n <= (args.get("endLine") or args["line"])]}

    def do_stepInTargets(self, args):
        return {"targets": [{"id": 1, "label": "range"}, {"id": 2, "label": "len"}]}

    def do_next(self, args):
        if self.flag("HARNESS_STEP_FAIL") == "1":
            raise AdapterError("adapter rejected the step")
        if set(args) - {"threadId"}:
            self.say(f"sent step {json.dumps(args, sort_keys=True)}")

        def go():
            self.pos += 1
            if self.pos >= len(TRACE):
                self.finish()
            else:
                self.event("stopped", {"reason": "step", "threadId": 1})
        self.after.append(go)
        return {}

    do_stepIn = do_stepOut = do_next

    def do_stepBack(self, args):
        def go():
            self.pos = max(0, self.pos - 1)
            self.stop({"reason": "step"})
        self.after.append(go)
        return {}

    def do_reverseContinue(self, args):
        def go():
            earlier = [p for p in self.stops if p < self.pos]
            self.pos = earlier[-1] if earlier else 0
            self.stop({"reason": "breakpoint"})
        self.after.append(go)
        return {}

    def do_continue(self, args):
        if set(args) - {"threadId"}:
            self.say(f"sent continue {json.dumps(args, sort_keys=True)}")

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
