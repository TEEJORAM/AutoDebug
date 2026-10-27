"""One debug session, driven through the extension's relay (docs/design.md).

The extension shows the Approve dialog, runs what it showed, and relays Debug
Adapter Protocol messages. Everything else happens here: choosing and checking
the launch configuration, following the session from the debugger's events,
breakpoint binding, and reading the stack, threads and variables.

`Session.call(op, args)` answers the operations the agent tools use, so
`tools.Debugger` does not depend on how the extension is built.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from autodebug.connection import IDE_NAMES, Connection, DebugError, Window
from autodebug.redact import clean_text, looks_secret

_LOG = logging.getLogger("autodebug")

STEP_COMMANDS = {"over": "next", "into": "stepIn", "out": "stepOut"}
# Extensions to suggest when a launch configuration's debugger is missing.
DEBUGGER_EXTENSIONS = {
    "debugpy": "Python Debugger", "python": "Python Debugger", "cppdbg": "C/C++", "cppvsdbg": "C/C++",
    "lldb": "CodeLLDB", "lldb-dap": "LLDB DAP", "gdb": "Native Debug", "coreclr": "C#", "java": "Debugger for Java",
    "go": "Go", "php": "PHP Debug",
}
PLATFORM_KEYS = {"win32": "windows", "darwin": "osx"}
FINISHED = ("ended", "denied", "build_failed")
OUTPUT_NOTE = ('program output went to the IDE terminal; set "console": "internalConsole" in the launch '
               "configuration to capture it")
_SUBSTITUTION = re.compile(r"\$\{(input|command):([^}]+)\}")


# -- launch configurations and tasks ----------------------------------------------


def apply_platform(item: dict, platform: str) -> dict:
    """The configuration as it runs on `platform`: its windows/osx/linux block applied, then removed."""
    copy = json.loads(json.dumps(item))
    block = copy.get(PLATFORM_KEYS.get(platform, "linux"))
    for key in ("windows", "osx", "linux"):
        copy.pop(key, None)
    if isinstance(block, dict):
        copy.update(block)
    return copy


def _strings(value, leaf: str = ""):
    if isinstance(value, str):
        yield value, leaf
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _strings(item, str(i))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, str(key))


def substitutions(config: dict, attach_pid_allowed: bool = False) -> list[str]:
    """`${input:…}` and `${command:…}` values: they would ask the developer after the approval."""
    found = []
    for text, leaf in _strings(config):
        for kind, name in _SUBSTITUTION.findall(text):
            if not (attach_pid_allowed and kind == "command" and leaf in ("processId", "pid")):
                found.append(f"${{{kind}:{name}}}")
    return found


def _host(value) -> str:
    host = str(value).strip()
    bracket = re.fullmatch(r"\[([^\]]+)\](?::\d+)?", host)
    if bracket:
        host = bracket.group(1)
    else:
        with_port = re.fullmatch(r"(.*):(\d+)", host)
        if with_port and with_port.group(1).count(":") == 0:
            host = with_port.group(1)
    return host.lower()


def remote_problem(config: dict) -> str | None:
    """The setting that would debug another computer, if any."""
    if config.get("pipeTransport"):
        return "pipeTransport"
    connect = config.get("connect") if isinstance(config.get("connect"), dict) else {}
    for name, value in (("host", config.get("host")), ("address", config.get("address")),
                        ("connect.host", connect.get("host")),
                        ("miDebuggerServerAddress", config.get("miDebuggerServerAddress"))):
        if value not in (None, "") and _host(value) not in ("localhost", "127.0.0.1", "::1"):
            return name
    return None


def _depends_on(task: dict) -> list[str]:
    deps = task.get("dependsOn") or []
    deps = deps if isinstance(deps, list) else [deps]
    return [d if isinstance(d, str) else d.get("task") for d in deps if isinstance(d, (str, dict))]


def task_chain(label: str | None, tasks: list[dict], seen: set | None = None) -> list[dict]:
    """The task and every task it depends on."""
    seen = set() if seen is None else seen
    if not label or label in seen:
        return []
    seen.add(label)
    task = next((t for t in tasks if t.get("label") == label), None)
    if task is None:
        return []
    return [task] + [t for dep in _depends_on(task) if dep for t in task_chain(dep, tasks, seen)]


def attach_target(launch: dict, name: str = "") -> str:
    pid = launch.get("processId", launch.get("pid"))
    if pid is not None and "${" not in str(pid):
        return f"Attach to: process {pid} ({name or 'name unknown'})"
    connect = launch.get("connect") if isinstance(launch.get("connect"), dict) else {}
    host = connect.get("host") or launch.get("host") or "localhost"
    port = connect.get("port") or launch.get("port")
    return f"Attach to: the debugger listening on {host}:{port}" if port else "Attach to: the running program"


def process_name(pid: int) -> str:
    """The process's name for the Approve dialog, or '' when it cannot be read."""
    try:
        if sys.platform.startswith("linux"):
            return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
        if sys.platform == "darwin":
            return subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True,
                                  timeout=3).stdout.strip()
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=3).stdout.strip()
        match = re.match(r'"([^"]+)"', out)
        return match.group(1) if match else ""
    except FileNotFoundError:
        if sys.platform.startswith("linux"):
            raise DebugError("NOT_FOUND", f"no process {pid}") from None
        return ""
    except (OSError, subprocess.SubprocessError):
        return ""


def missing_program(launch: dict, folder: str, building: bool) -> str | None:
    """The launch configuration's program when it is not on disk and nothing will build it first, else None.
    Only paths that can be resolved here are checked: absolute, or under ${workspaceFolder}."""
    if building or launch.get("request") != "launch" or launch.get("preLaunchTask"):
        return None
    program = launch.get("program")
    if not isinstance(program, str) or not program.strip():
        return None
    for variable in ("${workspaceFolder}", "${workspaceRoot}"):
        program = program.replace(variable, folder)
    if "${" in program or not os.path.isabs(program):
        return None
    path = Path(program)
    if path.exists() or (os.name == "nt" and not path.suffix and path.with_suffix(".exe").exists()):
        return None
    return program


def prepare_launch(raw: dict, process_id, platform: str) -> dict:
    """The launch configuration exactly as it will run, or a DebugError saying why it cannot."""
    launch = apply_platform(raw, platform)
    if launch.get("request") not in ("launch", "attach"):
        raise DebugError("BAD_REQUEST", "request must be launch or attach")
    attach = launch["request"] == "attach"
    if process_id is not None:
        if not attach:
            raise DebugError("BAD_REQUEST", "process_id is only for attach configurations")
        if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id < 1:
            raise DebugError("BAD_REQUEST", "process_id must be a positive integer")
        field = "pid" if launch.get("type") == "lldb" else "processId"
        current = launch.get(field)
        numeric = isinstance(current, int) or (isinstance(current, str) and current.isdigit())
        placeholder = isinstance(current, str) and _SUBSTITUTION.search(current) and current.startswith("${command:")
        if (numeric and int(current) != process_id) or (not numeric and not placeholder and current is not None):
            raise DebugError("BAD_REQUEST", "process_id contradicts the fixed PID")
        launch[field] = process_id
    elif attach and any(leaf in ("processId", "pid") and "${command:" in text for text, leaf in _strings(launch)):
        raise DebugError("BAD_REQUEST", "this configuration picks a process; pass process_id")
    tokens = substitutions(launch, attach)
    if tokens:
        raise DebugError("BAD_REQUEST", f"refuses {', '.join(tokens)}: they would ask the developer after approval")
    remote = remote_problem(launch)
    if remote:
        raise DebugError("BAD_REQUEST", f"AutoDebug debugs only programs on this computer ({remote})")
    return launch


MAX_ARGS = 32
MAX_ARG = 1000


def program_arguments(launch: dict, values) -> list[str]:
    """Replace the launch configuration's program arguments with `values` (the agent's), after checking them.
    Visual Studio takes one command line, so there they are joined with Windows quoting."""
    if launch.get("request") != "launch":
        raise DebugError("BAD_REQUEST", "args are only for launch configurations; an attached program is already running")
    if not isinstance(values, list) or len(values) > MAX_ARGS:
        raise DebugError("BAD_REQUEST", f"args is a list of at most {MAX_ARGS} arguments")
    for index, value in enumerate(values):
        if not isinstance(value, str) or len(value) > MAX_ARG:
            raise DebugError("BAD_REQUEST", f"args[{index}] must be text of at most {MAX_ARG} characters")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise DebugError("BAD_REQUEST", f"args[{index}] contains a line break or control character; "
                                            "put multi-line input in a file in the workspace instead")
        if "${" in value:
            raise DebugError("BAD_REQUEST", f"args[{index}] contains a ${{...}} variable; pass the value itself")
        if looks_secret(value):
            raise DebugError("BAD_REQUEST", f"args[{index}] looks like a secret (a key or token). Use a made-up test "
                                            "value; never copy secrets or customer data from a ticket")
    launch["args"] = [subprocess.list2cmdline(values)] if launch.get("type") == "visualstudio" and values else list(values)
    return launch["args"]


def one_line(text: object, limit: int) -> str:
    """Ticket names and similar shown in the Approve dialog: one line, no control characters, capped."""
    return " ".join(clean_text(text, limit).split())


# -- variable paths ----------------------------------------------------------------


def split_path(name: str) -> list[str]:
    """`mesh.verts[2].co` and `scene->objects[2]` as their parts."""
    parts = []
    for piece in str(name).replace("->", ".").split("."):
        parts += [a or b for a, b in re.findall(r"([^\[\].]+)|\[(\d+)\]", piece)]
    return [p for p in parts if p]


def _child_matches(child: dict, part: str) -> bool:
    return child.get("name") in (part, f"[{part}]")


def _key(file: str) -> str:
    return os.path.normcase(os.path.abspath(str(file)))


def _within(root: str, full: str) -> bool:
    try:
        rel = os.path.relpath(full, root)
    except ValueError:  # another drive on Windows
        return False
    return rel == "." or not (rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel))


# -- the session -------------------------------------------------------------------


def connect(window: Window) -> "Session":
    return Session(Connection(window))


class Session:
    """The agent's view of one IDE window and its debug session."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.window = connection.window
        self.s: dict | None = None
        self.version = 0
        self.cursor = 0

    def close(self) -> None:
        self.connection.close()

    def _relay(self, op: str, args: dict | None = None, timeout: float = 15.0) -> dict:
        return self.connection.call(op, args or {}, timeout=timeout)

    def call(self, op: str, args: dict | None = None, timeout: float = 30.0) -> dict:
        handler = {
            "targets": self.targets, "start": self.start, "state": self.state, "stack": self.stack,
            "variables": self.variables, "threads": self.threads, "exceptions": self.exceptions, "step": self.step,
            "continue": self.resume, "pause": self.pause, "breakpoints": self.breakpoints, "stop": self.stop,
        }.get(op)
        if handler is None:
            raise DebugError("BAD_REQUEST", f"unknown operation {op}")
        return handler(args or {})

    # -- targets -----------------------------------------------------------------

    def targets(self, args: dict) -> dict:
        info = self._relay("info")
        ws = self._relay("workspace", {"folder": args.get("folder")})
        types = info.get("debugger_types")
        launch = []
        for config in ws.get("launch", []):
            prepared = apply_platform(config, info.get("platform", sys.platform))
            launch.append({
                "name": config.get("name"), "type": config.get("type"), "request": config.get("request"),
                "program": prepared.get("program"), "module": prepared.get("module"), "args": prepared.get("args") or [],
                "console": prepared.get("console"), "available": None if types is None else config.get("type") in types,
                "preLaunchTask": config.get("preLaunchTask"), "postDebugTask": config.get("postDebugTask"),
                "attach": attach_target(prepared) if config.get("request") == "attach" else None,
            })
        tasks = [{"label": t.get("label"), "command": " ".join(str(p) for p in [t.get("command"), *(t.get("args") or [])] if p)}
                 for t in ws.get("tasks", [])]
        return {"folder": ws.get("folder"), "launch": launch, "tasks": tasks}

    # -- start: everything is checked here, then the extension asks the developer ---------------

    def start(self, args: dict) -> dict:
        info = self._relay("info")
        platform = info.get("platform", sys.platform)
        ide = IDE_NAMES.get(info.get("ide"), "the IDE")
        where = " in Visual Studio's startup project" if info.get("ide") == "visualstudio" else " in .vscode/launch.json"
        ws = self._relay("workspace", {"folder": args.get("folder")})
        folder = ws["folder"]
        found = next((c for c in ws.get("launch", []) if c.get("name") == args.get("launch")), None)
        if found is None:
            raise DebugError("NOT_FOUND", f'no launch configuration named "{args.get("launch")}"{where}; see list_targets')
        launch = prepare_launch(found, args.get("process_id"), platform)
        program_args = program_arguments(launch, args["args"]) if args.get("args") is not None else None
        types = info.get("debugger_types")
        if types is not None and launch.get("type") not in types:
            if ide == "Cursor" and launch.get("type") in ("cppdbg", "cppvsdbg"):
                raise DebugError("NOT_FOUND", 'Cursor cannot run the Microsoft C/C++ debugger. Use a CodeLLDB '
                                              'configuration ("type": "lldb") instead.')
            extension = DEBUGGER_EXTENSIONS.get(launch.get("type"))
            raise DebugError("NOT_FOUND", f'{ide} has no debugger for type "{launch.get("type")}". Ask the developer to '
                                          f"install {f'the {extension} extension' if extension else 'the extension for it'}"
                                          " and reload the window.")
        tasks = [apply_platform(t, platform) for t in ws.get("tasks", [])]
        if args.get("task") and not any(t.get("label") == args["task"] for t in tasks):
            raise DebugError("NOT_FOUND", f'no build task labelled "{args["task"]}"; see list_targets')
        missing = missing_program(launch, folder, bool(args.get("task")))
        if missing:
            labels = [t.get("label") for t in tasks if t.get("label")]
            fix = (f"call start_session again with build_task set to one of: {', '.join(repr(l) for l in labels[:5])}"
                   if labels else "ask the developer to build it")
            raise DebugError("NOT_BUILT", f"{missing} does not exist yet, so the debugger cannot start it. "
                                          f"Nothing was shown to the developer. To build it first, {fix}.")
        used = [t for label in (args.get("task"), launch.get("preLaunchTask"), launch.get("postDebugTask"))
                for t in task_chain(label, tasks)]
        tokens = list(dict.fromkeys(token for t in used for token in substitutions(t)))
        if tokens:
            raise DebugError("BAD_REQUEST", f"refuses {', '.join(tokens)}: they would ask the developer after approval")
        extras = self._source_folders(args.get("source_folders") or [])
        roots = [folder, *extras]
        breakpoints = [self._breakpoint(b, folder, roots) for b in args.get("breakpoints") or []]
        functions = [str(name)[:300] for name in args.get("function_breakpoints") or []]
        max_steps = max(1, min(int(args.get("max_steps") or 100), 1000))
        label = launch["name"]
        notes = [f"Goal: {str(args.get('goal') or '')[:500]}"] if args.get("goal") else []
        if args.get("reproduce"):
            notes.append("This run only reproduces the bug: no breakpoints from the agent; the program runs to its end.")
        if args.get("ticket"):
            notes.append(f"Ticket: {one_line(args['ticket'], 200)}")
            notes.append("The agent worked from this ticket. Ticket text can come from anyone: approve only if the "
                         "program, arguments and breakpoints below are what you expect.")
        if program_args is not None:
            notes.append(f"Program arguments chosen by the AI agent (they replace the configuration's): "
                         f"{json.dumps(args['args'], ensure_ascii=False)}")
        if launch["request"] == "attach":
            pid = launch.get("processId", launch.get("pid"))
            name = process_name(int(pid)) if pid is not None and str(pid).isdigit() else ""
            label = name or label
            notes.append(attach_target(launch, name))
        latest = int(self._relay("events", {"since": 2 ** 50, "wait_ms": 0}).get("latest") or 0)
        answer = self._relay("approve", {
            "folder": folder, "launch": launch, "task": args.get("task"), "notes": notes, "label": label,
            "breakpoints": [{"file": b["full"], "line": b["line"], "condition": b["condition"]} for b in breakpoints],
            "functions": functions, "source_folders": extras, "max_steps": max_steps,
            "max_minutes": args.get("max_minutes"), "build_minutes": args.get("build_minutes"),
        })
        for b, ident in zip(breakpoints, answer.get("breakpoint_ids", [])):
            b["id"] = ident
        self.cursor = latest
        self.s = {
            "status": "awaiting_approval", "reason": None, "location": None, "exit_code": None, "message": None,
            "steps_used": 0, "max_steps": max_steps, "build": None, "thread_id": None, "thread_name": None,
            "exception": None, "output": [], "partial": "", "folder": folder, "launch": launch, "roots": roots,
            "breakpoints": breakpoints,
            "functions": [{"name": n, "id": i} for n, i in zip(functions, answer.get("function_ids", []))],
            "verified": {}, "by_id": {}, "pending": {}, "capabilities": {}, "asked": None, "connected": False,
        }
        self._changed()
        return {"state": self.snapshot()}

    def _source_folders(self, folders: list) -> list[str]:
        if len(folders) > 10:
            raise DebugError("BAD_REQUEST", "source_folders accepts at most 10 folders")
        resolved = []
        for folder in folders:
            if not isinstance(folder, str) or not os.path.isabs(folder):
                raise DebugError("BAD_REQUEST", "source_folders must be absolute paths")
            if not os.path.isdir(folder):
                raise DebugError("NOT_FOUND", f"source folder not found: {folder}")
            resolved.append(os.path.abspath(folder))
        return resolved

    def _breakpoint(self, b: dict, folder: str, roots: list[str]) -> dict:
        line = b.get("line")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            raise DebugError("BAD_REQUEST", "breakpoint lines are positive integers")
        file = b.get("file")
        if not isinstance(file, str) or not file.strip():
            raise DebugError("BAD_REQUEST", "a breakpoint needs a file")
        if os.path.isabs(file):
            full = os.path.abspath(file)
            if not any(_within(root, full) for root in roots):
                raise DebugError("OUTSIDE_WORKSPACE", f"{file} is outside the workspace; pass source_folders for "
                                                      "folders outside the workspace")
        else:
            full = os.path.abspath(os.path.join(folder, file))
            if not _within(folder, full) or os.path.normcase(full) == os.path.normcase(os.path.abspath(folder)):
                raise DebugError("OUTSIDE_WORKSPACE", f"{file} is outside {folder}; pass source_folders for folders "
                                                      "outside the workspace")
        if not os.path.isfile(full):
            raise DebugError("NOT_FOUND", f"no file {file}")
        condition = str(b["condition"])[:500] if b.get("condition") else None
        return {"file": self._relative(full, folder), "full": full, "line": line, "condition": condition, "id": None}

    # -- following the session --------------------------------------------------------

    def _changed(self, **changes) -> None:
        if self.s is not None:
            self.s.update(changes)
        self.version += 1

    def _relative(self, full: str | None, folder: str | None = None) -> str | None:
        if not full:
            return None
        folder = folder or self.s["folder"]
        return Path(os.path.relpath(full, folder)).as_posix() if _within(folder, full) else full

    def _pump(self, wait_ms: int = 0) -> None:
        """Read the relay's new events and apply them."""
        while True:
            answer = self._relay("events", {"since": self.cursor, "wait_ms": wait_ms}, timeout=wait_ms / 1000 + 10)
            events = answer.get("events") or []
            if answer.get("dropped"):
                _LOG.warning("some debugger events were dropped before they could be read")
            if events:
                self.cursor = int(answer.get("next") or self.cursor)
                self._apply(events)
            if len(events) < 500:
                return
            wait_ms = 0

    def _apply(self, events: list[dict]) -> None:
        s = self.s
        if s is None:
            return
        stop = None
        for event in events:
            kind = event.get("kind")
            if kind == "approval":
                if event.get("approved"):
                    self._changed(status="starting")
                else:
                    self._changed(status="denied", reason=event.get("reason"))
            elif kind == "build":
                self._build(event)
            elif kind == "starting":
                self._changed(status="starting")
            elif kind == "started":
                s["connected"] = True
                if s["status"] == "starting":
                    self._changed(status="running")
            elif kind == "not_started":
                self._finish("the debugger did not start", message="check the Debug Console")
            elif kind == "error":
                s["message"] = str(event.get("message") or "")[:500]
            elif kind == "ended":
                self._finish(event.get("reason") or "the debug session ended", event.get("exit_code"))
            elif kind == "dap":
                s["connected"] = True
                stop = self._message(event.get("direction"), event.get("message") or {}, stop)
        if stop is not None and s["status"] not in FINISHED:
            self._locate(stop["threadId"], stop.get("reason"))

    def _build(self, event: dict) -> None:
        task, status = event.get("task"), event.get("status")
        if status == "running":
            self._changed(status="building", build={"task": task, "status": "running", "exit_code": None})
        elif status == "succeeded":
            self._changed(build={"task": task, "status": "succeeded", "exit_code": 0})
        else:
            minutes = event.get("minutes") or 0
            message = {"timeout": f"the build took longer than {minutes} minute{'' if minutes == 1 else 's'}",
                       "unavailable": f'task "{task}" is not available'}.get(status, "see the task output in the terminal")
            self._changed(status="build_failed", exit_code=event.get("exit_code"), message=message,
                          build={"task": task, "status": "failed", "exit_code": event.get("exit_code")})

    def _message(self, direction: str, m: dict, stop: dict | None) -> dict | None:
        """Apply one Debug Adapter Protocol message; returns the stop still to locate, if any."""
        s = self.s
        kind, body = m.get("type"), m.get("body") or {}
        if direction == "to_adapter" and kind == "request":
            arguments = m.get("arguments") or {}
            if m.get("command") == "setBreakpoints" and isinstance(arguments.get("source"), dict):
                s["pending"][m.get("seq")] = ("lines", arguments["source"].get("path"),
                                              [b.get("line") for b in arguments.get("breakpoints") or []])
            elif m.get("command") == "setFunctionBreakpoints":
                s["pending"][m.get("seq")] = ("functions", None, [b.get("name") for b in arguments.get("breakpoints") or []])
            return stop
        if kind == "response":
            if m.get("command") == "initialize":
                s["capabilities"] = body
            sent = s["pending"].pop(m.get("request_seq"), None)
            if sent:
                what, file, items = sent
                for bp, item in zip(body.get("breakpoints") or [], items):
                    key = f"fn:{item}" if what == "functions" else f"{_key(file)}:{item}"
                    s["verified"][key] = bp
                    if bp.get("id") is not None:
                        s["by_id"][bp["id"]] = key
                self._changed()
            return stop
        if kind != "event":
            return stop
        event = m.get("event")
        if event == "breakpoint" and isinstance(body.get("breakpoint"), dict):
            bp = body["breakpoint"]
            key = s["by_id"].get(bp.get("id"))
            if key:
                s["verified"][key] = {**s["verified"].get(key, {}), **bp}
                self._changed()
        elif event == "output":
            self._capture(body)
        elif event == "stopped":
            s["thread_id"] = body.get("threadId")
            return {"threadId": body.get("threadId"), "reason": body.get("reason")}
        elif event == "continued":
            if s["status"] not in FINISHED:
                self._changed(status="running", location=None, reason=None, exception=None)
            return None
        elif event == "exited":
            if s["status"] != "ended":
                s["exit_code"] = body.get("exitCode")
        elif event == "terminated":
            self._finish("the program exited")
            return None
        return stop

    def _capture(self, body: dict) -> None:
        s = self.s
        if body.get("category") == "telemetry" or not isinstance(body.get("output"), str):
            return
        lines = re.split(r"\r?\n", s["partial"] + body["output"])
        s["partial"] = lines.pop()
        s["output"] += [line[:500] for line in lines if line.strip()]
        del s["output"][:-60]

    def _locate(self, thread_id, reason) -> None:
        s = self.s
        exception = None
        if reason == "exception" and s["capabilities"].get("supportsExceptionInfoRequest"):
            try:
                body = self._dap("exceptionInfo", {"threadId": thread_id})
                exception = {"id": body.get("exceptionId"), "description": body.get("description") or ""}
            except DebugError:
                pass
        location = None
        try:
            frames = self._dap("stackTrace", {"threadId": thread_id, "startFrame": 0, "levels": 1}).get("stackFrames") or []
            if frames:
                location = {"file": self._relative((frames[0].get("source") or {}).get("path")), "line": frames[0].get("line")}
        except DebugError as exc:
            _LOG.warning("error handling stopped: %s", exc.message)
        self._changed(status="paused", reason=reason, location=location, exception=exception)

    def _finish(self, reason: str, exit_code=..., message: str | None = None) -> None:
        s = self.s
        if s is None or s["status"] == "ended":
            return
        if s["partial"].strip():
            s["output"].append(s["partial"][:500])
            s["partial"] = ""
        changes = {"status": "ended", "reason": reason, "location": None}
        if exit_code is not ... and exit_code is not None:
            changes["exit_code"] = exit_code
        if message:
            changes["message"] = message
        self._changed(**changes)

    def _dap(self, command: str, arguments: dict, timeout_ms: int = 10000) -> dict:
        return self._relay("dap", {"command": command, "arguments": arguments, "timeout_ms": timeout_ms},
                           timeout=timeout_ms / 1000 + 5).get("body") or {}

    def current(self, *statuses: str) -> dict:
        if self.s is None:
            raise DebugError("NOT_FOUND", "no debug session; call start_session first")
        self._pump(0)
        status = self.s["status"]
        if statuses and status not in statuses:
            raise DebugError("NOT_PAUSED" if status == "running" else "BAD_REQUEST", f"the session is {status}")
        return self.s

    # -- the state the tools see -----------------------------------------------------------

    def _verified(self, key: str) -> bool:
        return bool(self.s["verified"].get(key, {}).get("verified"))

    def _note(self, key: str, line: int | None) -> str:
        s = self.s
        bp = s["verified"].get(key)
        if bp is None:
            return "not confirmed by the debugger yet" if s["connected"] else "set when the program starts"
        if bp.get("verified"):
            return f"moved to line {bp['line']}" if line and bp.get("line") and bp["line"] != line else ""
        message = str(bp.get("message") or "")
        if s["status"] in ("starting", "running", "paused"):
            return (f"not bound yet ({message}); it may bind when its module loads" if message
                    else "not bound yet; it may bind when its module loads")
        return message or "not bound"

    def _editor_breakpoints(self) -> list[dict]:
        try:
            listed = self._relay("editor_breakpoints").get("breakpoints") or []
        except DebugError:
            return []
        out = []
        for b in listed:
            if b.get("function"):
                key = f"fn:{b['function']}"
                out.append({"function": b["function"], "source": "editor", "verified": self._verified(key), "message": ""})
            elif b.get("file"):
                key = f"{_key(b['file'])}:{b.get('line')}"
                out.append({"file": self._relative(b["file"]), "line": b.get("line"), "source": "editor",
                            "verified": self._verified(key), "message": self._note(key, b.get("line"))})
        return out

    def snapshot(self) -> dict:
        s = self.s
        if s is None:
            return {"version": 0, "status": "none"}
        session = [{"file": b["file"], "line": b["line"], "source": "session",
                    "verified": self._verified(f"{_key(b['full'])}:{b['line']}"),
                    "message": self._note(f"{_key(b['full'])}:{b['line']}", b["line"])} for b in s["breakpoints"]]
        functions = [{"function": f["name"], "source": "session", "verified": self._verified(f"fn:{f['name']}"),
                      "message": ""} for f in s["functions"]]
        ended = s["status"] == "ended"
        return {
            "version": self.version, "status": s["status"], "reason": s["reason"], "location": s["location"],
            "exit_code": s["exit_code"], "message": s["message"], "steps_used": s["steps_used"],
            "max_steps": s["max_steps"], "build": s["build"],
            "thread": None if s["thread_id"] is None else {"id": s["thread_id"], "name": s["thread_name"]},
            "exception": s["exception"], "breakpoints": session + functions + self._editor_breakpoints(),
            "output": s["output"][-20:] if s["status"] in ("ended", "paused") else [],
            "output_note": OUTPUT_NOTE if ended and not s["output"] and str(s["launch"].get("console") or "").endswith("Terminal")
            else None,
        }

    def state(self, args: dict) -> dict:
        if self.s is None:
            return {"state": self.snapshot()}
        text = args.get("ask_developer")
        if text is not None:
            text = str(text)
            if len(text) > 300:
                raise DebugError("BAD_REQUEST", "ask_developer is at most 300 characters")
            if text and text != self.s["asked"]:
                self._relay("notify", {"text": text})
                self.s["asked"] = text
        since = int(args.get("since") or 0)
        deadline = time.monotonic() + max(0, min(int(args.get("wait_ms") or 0), 60000)) / 1000
        self._pump(0)
        while self.version <= since:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._pump(int(min(remaining, 25) * 1000))
        return {"state": self.snapshot()}

    # -- inspection ----------------------------------------------------------------------

    def stack(self, args: dict) -> dict:
        s = self.current("paused")
        levels = max(1, min(int(args.get("levels") or 20), 200))
        start = max(0, int(args.get("start_frame") or 0))
        body = self._dap("stackTrace", {"threadId": s["thread_id"], "startFrame": start, "levels": levels})
        frames = [{"id": f.get("id"), "name": f.get("name"),
                   "file": self._relative((f.get("source") or {}).get("path")) or "(no source)", "line": f.get("line")}
                  for f in (body.get("stackFrames") or [])[:levels]]
        total = body.get("totalFrames")
        return {"frames": frames, "total": start + len(frames) if total is None else total}

    def threads(self, args: dict) -> dict:
        s = self.current("paused", "running")
        threads = [{"id": t.get("id"), "name": t.get("name")} for t in (self._dap("threads", {}).get("threads") or [])[:500]]
        select = args.get("select")
        if select is not None:
            if s["status"] != "paused":
                raise DebugError("NOT_PAUSED", "select a thread only while paused")
            chosen = next((t for t in threads if t["id"] == select), None)
            if chosen is None:
                raise DebugError("NOT_FOUND", f"no thread {select}")
            s["thread_id"], s["thread_name"] = chosen["id"], chosen["name"]
            self._locate(chosen["id"], s["reason"])
        elif s["thread_id"] is not None:
            current = next((t for t in threads if t["id"] == s["thread_id"]), None)
            if current:
                s["thread_name"] = current["name"]
        return {"threads": threads, "current": s["thread_id"], "state": self.snapshot()}

    def exceptions(self, args: dict) -> dict:
        s = self.current()
        if not s["connected"] or s["status"] in FINISHED or s["status"] in ("awaiting_approval", "building"):
            raise DebugError("NOT_FOUND", "the debugger is not connected yet")
        filters = s["capabilities"].get("exceptionBreakpointFilters") or []
        offered = [{"id": f.get("filter"), "label": f.get("label"), "default": bool(f.get("default"))} for f in filters]
        enable = args.get("enable")
        if isinstance(enable, list):
            known = [f["id"] for f in offered]
            unknown = [i for i in enable if i not in known]
            if unknown:
                raise DebugError("BAD_REQUEST", f"unknown exception filters: {', '.join(unknown)}; offered: "
                                                f"{', '.join(known) or 'none'}")
            self._dap("setExceptionBreakpoints", {"filters": enable})
        return {"filters": offered}

    def variables(self, args: dict) -> dict:
        s = self.current("paused")
        frame = args.get("frame")
        if not isinstance(frame, int):
            frames = self._dap("stackTrace", {"threadId": s["thread_id"], "startFrame": 0, "levels": 1}).get("stackFrames") or []
            if not frames:
                raise DebugError("NOT_FOUND", "the debugger shows no stack frame")
            frame = frames[0]["id"]
        depth = max(0, min(int(args.get("depth") or 0), 3))
        scopes = self._dap("scopes", {"frameId": frame}).get("scopes") or []
        wanted = [str(n) for n in args["names"]] if isinstance(args.get("names"), list) else None
        searched = [sc for sc in scopes if not sc.get("expensive") and sc.get("variablesReference")]
        found: dict[str, dict] = {}
        for scope in searched if wanted else searched[:1]:
            for variable in (self._children(scope["variablesReference"]))[:200]:
                name = variable.get("name")
                if name not in found and not re.fullmatch(r"(special|function) variables", str(name)):
                    found[name] = variable
        budget = {"nodes": 0}
        if wanted is None:
            chosen = list(found.values())
        else:
            chosen = []
            for name in wanted:
                variable = self._lookup(found, name)
                if variable is not None:
                    chosen.append({**variable, "name": name})
        return {"frame": frame, "variables": [self._expand(v, depth, wanted is not None, budget) for v in chosen]}

    def _children(self, reference: int) -> list[dict]:
        return self._dap("variables", {"variablesReference": reference}).get("variables") or []

    def _lookup(self, roots: dict[str, dict], name: str) -> dict | None:
        parts = split_path(name)
        if not parts:
            return None
        current = roots.get(name) or roots.get(parts[0])
        if current is None:
            return None
        if name in roots:
            return current
        for part in parts[1:]:
            if not current.get("variablesReference"):
                return None
            current = next((c for c in self._children(current["variablesReference"]) if _child_matches(c, part)), None)
            if current is None:
                return None
        return current

    def _expand(self, variable: dict, depth: int, named: bool, budget: dict) -> dict:
        node = {"name": variable.get("name"), "type": variable.get("type") or "", "value": str(variable.get("value"))}
        if budget["nodes"] >= 1000:
            return {**node, "expandable": True}
        budget["nodes"] += 1
        if not variable.get("variablesReference"):
            return node
        if depth <= 0:
            return {**node, "expandable": True}
        children = self._children(variable["variablesReference"])
        node["children"] = []
        for child in children[:50 if named else 20]:
            if budget["nodes"] >= 1000:
                break
            node["children"].append(self._expand(child, depth - 1, named, budget))
        if len(children) > len(node["children"]):
            node["more"] = len(children) - len(node["children"])
            node["expandable"] = True
        return node

    # -- control ---------------------------------------------------------------------

    def step(self, args: dict) -> dict:
        s = self.current("paused")
        command = STEP_COMMANDS.get(args.get("kind"))
        if command is None:
            raise DebugError("BAD_REQUEST", "kind is over, into or out")
        if s["steps_used"] >= s["max_steps"]:
            raise DebugError("LIMIT", f"the approved limit of {s['max_steps']} steps is used up")
        wait_ms = max(0, min(int(args.get("wait_ms") or 15000), 60000))
        paused_at = (s["location"], s["reason"])
        s["steps_used"] += 1
        self._changed(status="running", location=None, reason=None)
        before = self.version
        try:
            self._dap(command, {"threadId": s["thread_id"]})
        except DebugError:
            s["steps_used"] -= 1
            self._changed(status="paused", location=paused_at[0], reason=paused_at[1])
            raise
        deadline = time.monotonic() + wait_ms / 1000
        while (self.version <= before or s["status"] == "running") and s["status"] != "ended":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._pump(int(min(remaining, 25) * 1000))
        return {"state": self.snapshot()}

    def resume(self, args: dict) -> dict:
        s = self.current("paused")
        self._changed(status="running", location=None, reason=None, exception=None)
        self._dap("continue", {"threadId": s["thread_id"]})
        return {"state": self.snapshot()}

    def pause(self, args: dict) -> dict:
        s = self.current("running")
        thread_id = s["thread_id"]
        if thread_id is None:
            threads = self._dap("threads", {}).get("threads") or []
            thread_id = threads[0]["id"] if threads else None
        self._dap("pause", {"threadId": thread_id})
        return {"state": self.snapshot()}

    def breakpoints(self, args: dict) -> dict:
        s = self.current("starting", "running", "paused")
        remove = {(b.get("file"), b.get("line")) for b in args.get("remove") or []}
        remove_keys = set()
        for file, line in remove:
            if isinstance(file, str):
                full = file if os.path.isabs(file) else os.path.join(s["folder"], file)
                remove_keys.add(f"{_key(full)}:{line}")
        gone = [b for b in s["breakpoints"] if f"{_key(b['full'])}:{b['line']}" in remove_keys]
        gone_functions = [f for f in s["functions"] if f["name"] in set(args.get("remove_functions") or [])]
        added = [b for b in (self._breakpoint(b, s["folder"], s["roots"]) for b in args.get("add") or [])
                 if not any(x["full"] == b["full"] and x["line"] == b["line"] for x in s["breakpoints"])]
        new_functions = list(dict.fromkeys(str(n) for n in args.get("add_functions") or []
                                           if n not in {f["name"] for f in s["functions"]}))
        answer = self._relay("breakpoints", {
            "remove": [b["id"] for b in gone + gone_functions if b.get("id")],
            "add": [{"file": b["full"], "line": b["line"], "condition": b["condition"]} for b in added],
            "add_functions": new_functions,
        })
        for b, ident in zip(added, answer.get("breakpoint_ids", [])):
            b["id"] = ident
        s["breakpoints"] = [b for b in s["breakpoints"] if b not in gone] + added
        s["functions"] = [f for f in s["functions"] if f not in gone_functions] + [
            {"name": n, "id": i} for n, i in zip(new_functions, answer.get("function_ids", []))]
        self._changed()
        return {"state": self.snapshot()}

    def stop(self, args: dict) -> dict:
        s = self.s
        if s is None:
            return {"state": self.snapshot()}
        attach = s["launch"].get("request") == "attach"
        reason = "the debugger detached and the program keeps running" if attach else "stopped by the agent"
        if s["status"] not in FINISHED:
            self._finish(reason)
        self._relay("stop", {"reason": reason}, timeout=20)  # the extension ignores it when nothing is running
        return {"state": self.snapshot()}
