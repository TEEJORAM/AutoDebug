"""One debug session, driven through the extension's relay (docs/design.md).

The extension shows the Approve dialog, runs what it showed, and relays Debug
Adapter Protocol messages. Everything else happens here: choosing and checking
the launch configuration, following the session from the debugger's events,
breakpoint binding, and reading the stack, threads and variables.

`Session.call(op, args)` answers the operations the agent tools use, so
`tools.Debugger` does not depend on how the extension is built.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from autodebug.build import build_type, describe
from autodebug.connection import IDE_NAMES, Connection, DebugError, Window
from autodebug.redact import REDACTED, clean_text, is_secret_name, looks_secret

_LOG = logging.getLogger("autodebug")

STEP_COMMANDS = {"over": "next", "into": "stepIn", "out": "stepOut", "back": "stepBack"}
#: A hit condition: a count, optionally with the comparison the debugger applies (>=, >, ==, <=, <, %).
_HIT = re.compile(r"\s*(>=|<=|==|>|<|%)?\s*\d{1,9}\s*")
#: What a log message may show between braces: a variable or a path into one, never an expression.
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_VARIABLE_PATH = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|->[A-Za-z_$][\w$]*|\[\d{1,9}\])*")
#: Test runners `test` knows: how a launch configuration runs one test.
TEST_RUNNERS = "pytest, unittest, go test, jest or vitest"
MAX_MEMORY = 256
MAX_ACTIVITY = 50
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
    if building or launch.get("preLaunchTask") or program_exists(launch, folder) is not False:
        return None
    program = launch["program"]
    for variable in ("${workspaceFolder}", "${workspaceRoot}"):
        program = program.replace(variable, folder)
    return program


def program_exists(launch: dict, folder: str) -> bool | None:
    """Whether the launch configuration's program is on disk; None when its path cannot be resolved here."""
    if launch.get("request") != "launch":
        return None
    program = launch.get("program")
    if not isinstance(program, str) or not program.strip():
        return None
    for variable in ("${workspaceFolder}", "${workspaceRoot}"):
        program = program.replace(variable, folder)
    if "${" in program or not os.path.isabs(program):
        return None
    path = Path(program)
    return path.exists() or (os.name == "nt" and not path.suffix and path.with_suffix(".exe").exists())


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


def test_arguments(launch: dict, test: object) -> list[str]:
    """The program arguments that run only `test` with the launch configuration's test runner."""
    if not isinstance(test, str) or not test.strip() or len(test) > 300:
        raise DebugError("BAD_REQUEST", "test is the name of one test, at most 300 characters")
    if test.startswith("-") or any(ord(ch) < 32 or ord(ch) == 127 for ch in test) or "${" in test:
        raise DebugError("BAD_REQUEST", "test is a test name or id, not an option, a variable or several lines")
    if launch.get("request") != "launch":
        raise DebugError("BAD_REQUEST", "test is only for launch configurations")
    module = str(launch.get("module") or "")
    program = str(launch.get("program") or "").replace("\\", "/").lower()
    runner = program.rsplit("/", 1)[-1]
    if module == "pytest" or runner in ("pytest", "py.test") or "/pytest/" in program:
        return [test]
    if module == "unittest":
        return [test]
    if launch.get("type") == "go" and launch.get("mode") == "test":
        name = test.rsplit("/", 1)[-1] if "/" in test and not test.startswith("Test") else test
        return ["-test.run", f"^{re.escape(name)}$"]
    if "jest" in runner or "/jest/" in program:
        return ["--runInBand", "-t", test]
    if "vitest" in runner or "/vitest/" in program:
        return ["run", "-t", test]
    raise DebugError("BAD_REQUEST", f'launch configuration "{launch.get("name")}" does not run a test runner AutoDebug '
                                    f"knows ({TEST_RUNNERS}); pass args with the runner's own option instead")


def check_hit_condition(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _HIT.fullmatch(value):
        raise DebugError("BAD_REQUEST", "hit_condition is a count such as 5, >=5 or %10")
    return value.strip()


def check_log_message(value: object) -> str | None:
    """A log point's message. Braces may name a variable or a path into one ({total}, {mesh.verts[2].co}), so the
    debugger only reads values; anything else in braces would be an expression it evaluates."""
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 300 or any(ord(ch) < 32 for ch in value):
        raise DebugError("BAD_REQUEST", "log_message is one line of at most 300 characters")
    for inner in _PLACEHOLDER.findall(value):
        if not _VARIABLE_PATH.fullmatch(inner.strip()):
            raise DebugError("BAD_REQUEST", f"log_message may show variables by name only, like {{total}} or "
                                            f"{{mesh.verts[2].co}}; {{{inner}}} is an expression")
    return value


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
    name = str(child.get("name"))
    if name in (part, f"[{part}]"):
        return True
    # Debuggers number elements their own way: [5000], 5000, or debugpy's zero-padded 05000.
    digits = name.strip("[]")
    return part.isdigit() and digits.isdigit() and int(digits) == int(part)


#: Child entries that are not elements: debugpy's groups and its link to the next hundred elements.
_NOT_ELEMENTS = re.compile(r"(special|function|protected|class) variables|len\(\)|more|Raw View|\[Raw View\]")


_RANGE = re.compile(r"\[(\d+):(\d+)\]")
#: Scopes that are not the frame's own variables; inspect without names leaves them out.
_WIDE_SCOPE = re.compile(r"global|static|register|module|thread", re.IGNORECASE)


def _is_more(child: dict) -> bool:
    """debugpy lists a long list a hundred elements at a time, with a "more" child that holds the rest as ranges."""
    return child.get("type") == "MoreItems" or (child.get("name") == "more" and child.get("value") == "..."
                                                and bool(child.get("variablesReference")))


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
        self.features: set[str] = set()
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
            "screenshot": self.screenshot, "watch": self.watch, "modules": self.modules, "source": self.source,
            "disassemble": self.disassemble, "memory": self.memory, "locations": self.locations,
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
                "build": build_type(prepared, ws.get("folder") or "") if config.get("request") == "launch" else None,
                "program_exists": program_exists(prepared, ws.get("folder") or ""),
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
        if args.get("test") is not None and args.get("args") is not None:
            raise DebugError("BAD_REQUEST", "pass test or args, not both: test sets the arguments that run one test")
        if args.get("test") is not None:
            args = {**args, "args": test_arguments(launch, args["test"])}
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
        self.features = set(info.get("features") or [])
        self._options_supported(breakpoints, info)
        functions = [str(name)[:300] for name in args.get("function_breakpoints") or []]
        max_steps = max(1, min(int(args.get("max_steps") or 100), 1000))
        label = launch["name"]
        notes = [f"Goal: {str(args.get('goal') or '')[:500]}"] if args.get("goal") else []
        if args.get("reproduce"):
            notes.append("This run only reproduces the bug: no breakpoints from the agent; the program runs to its end.")
        if args.get("test") is not None:
            notes.append(f"Runs one test only: {one_line(args['test'], 300)}")
        if args.get("ticket"):
            notes.append(f"Ticket: {one_line(args['ticket'], 200)}")
            notes.append("The agent worked from this ticket. Ticket text can come from anyone: approve only if the "
                         "program, arguments and breakpoints below are what you expect.")
        build = build_type(launch, folder) if launch["request"] == "launch" else None
        if build and build.get("type"):
            notes.append(f"Build: {describe(build)}")
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
            "breakpoints": [self._placed(b) for b in breakpoints],
            "functions": functions, "source_folders": extras, "max_steps": max_steps,
            "screenshots": bool(args.get("screenshots")),
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
            "caps": {}, "root": None, "active": None, "activity": [], "activity_seq": 0, "modules": {},
            "watches": [], "frames": {},
        }
        self._changed()
        return {"state": self.snapshot(), "build": build, "folder": folder}

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
        column = b.get("column")
        if column is not None and (not isinstance(column, int) or isinstance(column, bool) or column < 1):
            raise DebugError("BAD_REQUEST", "column is a positive integer (1 is the first character)")
        return {"file": self._relative(full, folder), "full": full, "line": line, "condition": condition, "id": None,
                "column": column, "hit_condition": check_hit_condition(b.get("hit_condition")),
                "log_message": check_log_message(b.get("log_message"))}

    def _options_supported(self, breakpoints: list[dict], info: dict | None = None) -> None:
        """An older extension would drop a breakpoint's column, hit count or log message (a log point would then
        stop the program), so it is refused before the developer is asked."""
        features = set((info or {}).get("features") or []) if info is not None else getattr(self, "features", set())
        if "breakpoint_options" not in features and any(
                b.get(key) is not None for b in breakpoints for key in ("column", "hit_condition", "log_message")):
            raise DebugError("OLD_EXTENSION", f"the AutoDebug extension in {IDE_NAMES.get(self.window.ide, 'the IDE')} "
                                              "is older than this server and cannot place hit counts, log points or "
                                              "columns. Run autodebug setup, then reload the IDE window (Visual Studio: "
                                              "close it first)")

    @staticmethod
    def _placed(b: dict) -> dict:
        """A breakpoint as the relay places it: only the options that are set."""
        placed = {"file": b["full"], "line": b["line"], "condition": b["condition"]}
        for key in ("column", "hit_condition", "log_message"):
            if b.get(key) is not None:
                placed[key] = b[key]
        return placed

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
                stop = self._message(event.get("direction"), event.get("message") or {}, stop, event.get("session"))
            elif kind == "child_started":
                self._activity(f"debug session started: {one_line(event.get('name') or 'child', 120)}")
            elif kind == "child_ended":
                if s["active"] == event.get("session"):
                    s["active"] = s["root"]
                self._activity(f"debug session ended: {one_line(event.get('name') or 'child', 120)}")
        if stop is not None and s["status"] not in FINISHED:
            self._locate(stop["threadId"], stop.get("reason"), stop.get("description"))

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

    def _message(self, direction: str, m: dict, stop: dict | None, session: str | None = None) -> dict | None:
        """Apply one Debug Adapter Protocol message; returns the stop still to locate, if any.
        `session` names the debug session it belongs to: a program can run in child sessions (Node.js, browsers,
        Python subprocesses), and each has its own sequence numbers, threads and capabilities."""
        s = self.s
        kind, body = m.get("type"), m.get("body") or {}
        if s["root"] is None and session is not None:
            s["root"] = session
        if direction == "to_adapter" and kind == "request":
            arguments = m.get("arguments") or {}
            pending = f"{session}:{m.get('seq')}"
            if m.get("command") == "setBreakpoints" and isinstance(arguments.get("source"), dict):
                s["pending"][pending] = ("lines", arguments["source"].get("path"),
                                         [b.get("line") for b in arguments.get("breakpoints") or []])
            elif m.get("command") == "setFunctionBreakpoints":
                s["pending"][pending] = ("functions", None, [b.get("name") for b in arguments.get("breakpoints") or []])
            return stop
        if kind == "response":
            if m.get("command") == "initialize":
                s["caps"][session] = body
                if session in (None, s["root"]) or not s["capabilities"]:
                    s["capabilities"] = body
            sent = s["pending"].pop(f"{session}:{m.get('request_seq')}", None)
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
            s["active"] = session if session is not None else s["root"]
            return {"threadId": body.get("threadId"), "reason": body.get("reason"), "description": body.get("description")}
        elif event == "capabilities" and isinstance(body.get("capabilities"), dict):
            s["caps"][session] = {**s["caps"].get(session, {}), **body["capabilities"]}
        elif event in ("thread", "process", "module", "loadedSource", "progressStart", "progressEnd"):
            self._event_activity(event, body)
        elif event == "continued":
            if s["status"] not in FINISHED:
                self._changed(status="running", location=None, reason=None, exception=None)
            return None
        elif event == "exited":
            if s["status"] != "ended":
                s["exit_code"] = body.get("exitCode")
        elif event == "terminated":
            if session in (None, s["root"]):  # a child session ending (a subprocess) does not end the program
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

    def _activity(self, text: str) -> None:
        s = self.s
        s["activity_seq"] += 1
        s["activity"].append({"seq": s["activity_seq"], "text": text})
        del s["activity"][:-MAX_ACTIVITY]

    def _event_activity(self, event: str, body: dict) -> None:
        """Threads, processes and modules that start and end, and long debugger work, for the agent to see."""
        s = self.s
        if event == "thread":
            self._activity(f"thread {body.get('threadId')} {body.get('reason') or 'changed'}")
        elif event == "process":
            pid = body.get("systemProcessId")
            self._activity(f"process {one_line(body.get('name') or '', 200)}" + (f" ({pid})" if pid else "")
                           + f" {body.get('startMethod') or 'started'}")
        elif event == "module":
            module = body.get("module") if isinstance(body.get("module"), dict) else {}
            key, reason = str(module.get("id")), body.get("reason") or "new"
            if reason == "removed":
                s["modules"].pop(key, None)
            else:
                s["modules"][key] = {**s["modules"].get(key, {}), **module}
            if len(s["modules"]) <= 30 or reason != "new":
                status = f" ({module['symbolStatus']})" if module.get("symbolStatus") else ""
                self._activity(f"module {one_line(module.get('name') or key, 200)} {'loaded' if reason == 'new' else reason}"
                               f"{status}")
        elif event == "loadedSource":
            source = body.get("source") if isinstance(body.get("source"), dict) else {}
            if source.get("sourceReference") and not source.get("path"):
                self._activity(f"source without a file loaded: {one_line(source.get('name') or '', 200)}")
        elif event == "progressStart":
            self._activity(f"debugger: {one_line(body.get('title') or '', 200)}"
                           + (f" ({one_line(body.get('message'), 200)})" if body.get("message") else ""))

    def _caps(self) -> dict:
        """The capabilities of the debug session the program stopped in (a child session, if any)."""
        s = self.s
        return s["caps"].get(s["active"]) or s["caps"].get(s["root"]) or s["capabilities"]

    def _need(self, capability: str, what: str) -> None:
        if not self._caps().get(capability):
            kind = self.s["launch"].get("type")
            raise DebugError("NOT_SUPPORTED", f"this debugger ({kind}) cannot {what}")

    def _locate(self, thread_id, reason, description: str | None = None) -> None:
        s = self.s
        exception = None
        if reason == "exception" and self._caps().get("supportsExceptionInfoRequest"):
            try:
                body = self._dap("exceptionInfo", {"threadId": thread_id})
                exception = {"id": body.get("exceptionId"), "description": body.get("description") or ""}
            except DebugError:
                pass
        location = None
        try:
            frames = self._dap("stackTrace", {"threadId": thread_id, "startFrame": 0, "levels": 1}).get("stackFrames") or []
            if frames:
                source = frames[0].get("source") or {}
                file = self._relative(source.get("path")) or f"(no file) {source.get('name') or frames[0].get('name') or ''}".strip()
                location = {"file": file, "line": frames[0].get("line")}
        except DebugError as exc:
            _LOG.warning("error handling stopped: %s", exc.message)
        if reason == "data breakpoint" and description:
            reason = f"data breakpoint: {one_line(description, 200)}"
        s["frames"] = {}
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
        request = {"command": command, "arguments": arguments, "timeout_ms": timeout_ms}
        if self.s is not None and self.s.get("active") is not None:
            request["session"] = self.s["active"]
        try:
            return self._relay("dap", request, timeout=timeout_ms / 1000 + 5).get("body") or {}
        except DebugError as exc:
            if exc.code == "BAD_REQUEST" and "is not allowed" in exc.message:
                raise DebugError("OLD_EXTENSION", f"the AutoDebug extension in {IDE_NAMES.get(self.window.ide, 'the IDE')}"
                                                  f" is older than this server and cannot send {command}. Run autodebug "
                                                  "setup, then reload the IDE window (Visual Studio: close it first)") from None
            raise

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
                    "message": self._note(f"{_key(b['full'])}:{b['line']}", b["line"]),
                    **{k: b[k] for k in ("column", "condition", "hit_condition", "log_message") if b.get(k) is not None}}
                   for b in s["breakpoints"]]
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
            "activity": s["activity"][-10:],
            "watches": [{"name": w["name"], "access": w["access"], "verified": w.get("verified", False),
                         "message": w.get("message") or ""} for w in s["watches"]],
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
        frames = []
        for f in (body.get("stackFrames") or [])[:levels]:
            source = f.get("source") or {}
            frame = {"id": f.get("id"), "name": f.get("name"), "file": self._relative(source.get("path")) or "(no source)",
                     "line": f.get("line")}
            if not source.get("path") and source.get("sourceReference"):
                frame["source_reference"] = source["sourceReference"]
                frame["source_name"] = source.get("name") or ""
            if f.get("instructionPointerReference"):
                frame["instruction"] = f["instructionPointerReference"]
            if f.get("moduleId") is not None:
                frame["module"] = s["modules"].get(str(f["moduleId"]), {}).get("name") or str(f["moduleId"])
            s["frames"][f.get("id")] = frame
            frames.append(frame)
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
        """List the debugger's exception filters; enable some (each with a condition where the debugger takes one),
        and with `types` stop only for those exception types."""
        s = self.current()
        if not s["connected"] or s["status"] in FINISHED or s["status"] in ("awaiting_approval", "building"):
            raise DebugError("NOT_FOUND", "the debugger is not connected yet")
        caps = self._caps()
        filters = caps.get("exceptionBreakpointFilters") or []
        offered = [{"id": f.get("filter"), "label": f.get("label"), "default": bool(f.get("default")),
                    "condition": bool(f.get("supportsCondition"))} for f in filters]
        enable, types = args.get("enable"), args.get("types")
        if isinstance(enable, list) or types:
            known = {f["id"]: f for f in offered}
            chosen = [e if isinstance(e, dict) else {"id": e} for e in enable or []]
            unknown = [str(c.get("id")) for c in chosen if c.get("id") not in known]
            if unknown:
                raise DebugError("BAD_REQUEST", f"unknown exception filters: {', '.join(unknown)}; offered: "
                                                f"{', '.join(known) or 'none'}")
            request: dict = {"filters": [c["id"] for c in chosen if not c.get("condition")]}
            conditioned = [c for c in chosen if c.get("condition")]
            if conditioned:
                if not caps.get("supportsExceptionFilterOptions"):
                    raise DebugError("NOT_SUPPORTED", "this debugger takes no conditions on exception filters")
                missing = [c["id"] for c in conditioned if not known[c["id"]]["condition"]]
                if missing:
                    raise DebugError("NOT_SUPPORTED", f"filter {', '.join(missing)} takes no condition")
                request["filterOptions"] = [{"filterId": c["id"], "condition": str(c["condition"])[:300]}
                                            for c in conditioned]
            if types:
                if not caps.get("supportsExceptionOptions"):
                    raise DebugError("NOT_SUPPORTED", "this debugger cannot stop for chosen exception types; enable a "
                                                      "filter and check the exception at the stop")
                mode = {"unhandled": "unhandled", "always": "always"}.get(args.get("mode") or "always")
                if mode is None:
                    raise DebugError("BAD_REQUEST", "mode is always or unhandled")
                names = [str(t)[:200] for t in types]
                path = [{"names": names}]
                if s["launch"].get("type") in ("debugpy", "python"):
                    path.insert(0, {"names": ["Python Exceptions"]})
                request["exceptionOptions"] = [{"path": path, "breakMode": mode}]
            self._dap("setExceptionBreakpoints", request)
        return {"filters": offered, "types_supported": bool(caps.get("supportsExceptionOptions"))}

    # -- variables -----------------------------------------------------------------------

    def _frame_id(self, args: dict) -> int:
        s = self.s
        frame = args.get("frame")
        if isinstance(frame, int):
            return frame
        frames = self._dap("stackTrace", {"threadId": s["thread_id"], "startFrame": 0, "levels": 1}).get("stackFrames") or []
        if not frames:
            raise DebugError("NOT_FOUND", "the debugger shows no stack frame")
        return frames[0]["id"]

    def _format(self, args: dict) -> dict | None:
        if not args.get("hex"):
            return None
        self._need("supportsValueFormattingOptions", "show values in hex")
        return {"hex": True}

    def variables(self, args: dict) -> dict:
        """Variables of a frame. `scope` reads one scope by name (also the slow ones: globals, registers); `start`
        and `count` page through a large array or list; `hex` asks the debugger for hexadecimal values."""
        self.current("paused")
        frame = self._frame_id(args)
        fmt = self._format(args)
        depth = max(0, min(int(args.get("depth") or 0), 3))
        scopes = self._dap("scopes", {"frameId": frame}).get("scopes") or []
        listed = [{"name": sc.get("name"), "expensive": bool(sc.get("expensive"))} for sc in scopes]
        wanted = [str(n) for n in args["names"]] if isinstance(args.get("names"), list) else None
        scope_name = args.get("scope")
        if scope_name:
            searched = [sc for sc in scopes if str(sc.get("name", "")).lower() == str(scope_name).lower()]
            if not searched:
                raise DebugError("NOT_FOUND", f"no scope {scope_name}; this frame has: "
                                              f"{', '.join(str(sc.get('name')) for sc in scopes) or 'none'}")
        else:
            searched = [sc for sc in scopes if not sc.get("expensive") and sc.get("variablesReference")]
            if not wanted:
                # The frame's own variables (gdb lists Arguments and Locals apart), not globals or registers.
                own = [sc for sc in searched if not _WIDE_SCOPE.search(str(sc.get("name")))]
                searched = own or searched[:1]
        found: dict[str, dict] = {}
        for scope in searched:
            for variable in (self._children(scope["variablesReference"], fmt))[:500 if scope_name else 200]:
                name = variable.get("name")
                if name not in found and not re.fullmatch(r"(special|function) variables", str(name)):
                    found[name] = variable
        budget = {"nodes": 0}
        page = None
        if args.get("start") is not None or args.get("count") is not None:
            if not wanted or len(wanted) != 1:
                raise DebugError("BAD_REQUEST", "start and count page through one variable: pass exactly one name")
            page = (max(0, int(args.get("start") or 0)), max(1, min(int(args.get("count") or 50), 200)))
        if wanted is None:
            chosen = list(found.values())
        else:
            chosen = []
            for name in wanted:
                variable = self._lookup(found, name, fmt)
                if variable is not None:
                    chosen.append({**variable, "name": name})
        if page is not None:
            return {"frame": frame, "scopes": listed,
                    "variables": [self._page(v, page[0], page[1], fmt) for v in chosen]}
        return {"frame": frame, "scopes": listed,
                "variables": [self._expand(v, depth, wanted is not None, budget, fmt) for v in chosen]}

    def _children(self, reference: int, fmt: dict | None = None, start: int | None = None,
                  count: int | None = None, indexed: bool = False) -> list[dict]:
        request: dict = {"variablesReference": reference}
        if fmt:
            request["format"] = fmt
        if start is not None:
            request.update({"start": start, "count": count or 1})
            if indexed:
                request["filter"] = "indexed"
        return self._dap("variables", request).get("variables") or []

    def _child(self, parent: dict, part: str, fmt: dict | None) -> dict | None:
        """One child by name. An index into a large array is read on its own when the debugger pages, and found
        by following debugpy's "more" links otherwise."""
        if part.isdigit() and parent.get("indexedVariables"):
            for child in self._children(parent["variablesReference"], fmt, int(part), 1, indexed=True):
                if _child_matches(child, part):
                    return child
        if part.isdigit():
            found, _ = self._slice(parent["variablesReference"], int(part), int(part) + 1, fmt, [200])
            return found[0] if found else None
        return next((c for c in self._children(parent["variablesReference"], fmt) if _child_matches(c, part)), None)

    def _slice(self, reference: int, start: int, end: int, fmt: dict | None, budget: list[int]) -> tuple[list[dict], int | None]:
        """The elements with index start..end-1 of a list or array, and its length when the debugger says it.
        Follows debugpy's "more" child and its [a:b] ranges, reading only the ranges that hold those elements."""
        elements, total, position = [], None, 0
        for child in self._children(reference, fmt):
            name = str(child.get("name"))
            bounds = _RANGE.fullmatch(name)
            if _is_more(child) or (bounds and child.get("variablesReference")):
                if bounds and (int(bounds.group(2)) <= start or int(bounds.group(1)) >= end):
                    continue
                if budget[0] <= 0:
                    break
                budget[0] -= 1
                elements += self._slice(child["variablesReference"], start, end, fmt, budget)[0]
                continue
            if name == "len()" and str(child.get("value")).isdigit():
                total = int(child["value"])
                continue
            if _NOT_ELEMENTS.fullmatch(name):
                continue
            digits = name.strip("[]")
            index = int(digits) if digits.isdigit() else position
            position += 1
            if start <= index < end:
                elements.append(child)
        return elements, total

    def _lookup(self, roots: dict[str, dict], name: str, fmt: dict | None = None) -> dict | None:
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
            current = self._child(current, part, fmt)
            if current is None:
                return None
        return current

    def _page(self, variable: dict, start: int, count: int, fmt: dict | None) -> dict:
        node = {"name": variable.get("name"), "type": variable.get("type") or "", "value": str(variable.get("value"))}
        if not variable.get("variablesReference"):
            return node
        total = variable.get("indexedVariables")
        if total:
            children = self._children(variable["variablesReference"], fmt, start, min(count, max(0, total - start)), True)
        else:
            children, known = self._slice(variable["variablesReference"], start, start + count, fmt, [200])
            total = known if known is not None else (len(children) + start if len(children) < count else None)
        node["children"] = [{"name": c.get("name"), "type": c.get("type") or "", "value": str(c.get("value")),
                             **({"expandable": True} if c.get("variablesReference") else {})} for c in children]
        node["page"] = {"start": start, "count": len(children), "total": total}
        return node

    def _expand(self, variable: dict, depth: int, named: bool, budget: dict, fmt: dict | None = None) -> dict:
        node = {"name": variable.get("name"), "type": variable.get("type") or "", "value": str(variable.get("value"))}
        if budget["nodes"] >= 1000:
            return {**node, "expandable": True}
        budget["nodes"] += 1
        if not variable.get("variablesReference"):
            return node
        if variable.get("indexedVariables"):
            node["size"] = variable["indexedVariables"]
        if depth <= 0:
            return {**node, "expandable": True}
        limit = 50 if named else 20
        if variable.get("indexedVariables"):
            children = self._children(variable["variablesReference"], fmt, 0, min(limit, variable["indexedVariables"]), True)
            total = variable["indexedVariables"] + (variable.get("namedVariables") or 0)
        else:
            children = self._children(variable["variablesReference"], fmt)
            total = len(children)
        node["children"] = []
        for child in children[:limit]:
            if budget["nodes"] >= 1000:
                break
            node["children"].append(self._expand(child, depth - 1, named, budget, fmt))
        if total > len(node["children"]):
            node["more"] = total - len(node["children"])
            node["expandable"] = True
        return node

    # -- watchpoints, modules, code without a file, machine code and memory --------------------

    def _variable(self, name: str, frame: int) -> tuple[dict | None, int, str]:
        """A variable by path in `frame`: (it, the reference of the container that holds it, its name there)."""
        scopes = [sc for sc in self._dap("scopes", {"frameId": frame}).get("scopes") or [] if sc.get("variablesReference")]
        parts = split_path(name)
        if not parts:
            raise DebugError("BAD_REQUEST", f"{name!r} is not a variable name or path")
        for scope in scopes:
            if scope.get("expensive") and len(scopes) > 1:
                continue
            container = scope["variablesReference"]
            current = next((v for v in self._children(container) if v.get("name") == parts[0]), None)
            if current is None:
                continue
            for part in parts[1:]:
                if not current.get("variablesReference"):
                    return None, 0, ""
                container = current["variablesReference"]
                current = self._child(current, part, None)
                if current is None:
                    return None, 0, ""
            return current, container, current.get("name") or parts[-1]
        return None, 0, ""

    def watch(self, args: dict) -> dict:
        """Data breakpoints: stop when a variable's value changes (or is read). The debugger watches the memory
        itself; nothing is evaluated."""
        s = self.current("paused")
        add, remove = args.get("add") or [], {str(n) for n in args.get("remove") or []}
        if add:
            self._need("supportsDataBreakpoints", "stop when a value changes (data breakpoints)")
        frame = self._frame_id(args)
        watches = [w for w in s["watches"] if w["name"] not in remove]
        for item in add:
            name = str(item.get("name") or "")
            access = item.get("access") or "write"
            if access not in ("write", "read", "readWrite"):
                raise DebugError("BAD_REQUEST", "access is write, read or readWrite")
            variable, container, child = self._variable(name, frame)
            if variable is None:
                raise DebugError("NOT_FOUND", f"no variable {name} in this frame")
            info = self._dap("dataBreakpointInfo", {"variablesReference": container, "name": child, "frameId": frame})
            if not info.get("dataId"):
                raise DebugError("NOT_SUPPORTED", f"the debugger cannot watch {name}: "
                                                  f"{one_line(info.get('description') or 'no reason given', 200)}")
            types = info.get("accessTypes")
            if types and access not in types:
                raise DebugError("NOT_SUPPORTED", f"the debugger can watch {name} only for: {', '.join(types)}")
            watches = [w for w in watches if w["name"] != name]
            watches.append({"name": name, "access": access, "data_id": info["dataId"],
                            "description": one_line(info.get("description") or name, 200)})
        if len(watches) > 8:
            raise DebugError("LIMIT", "at most 8 watched values at a time (processors have few hardware watchpoints)")
        answer = self._dap("setDataBreakpoints", {"breakpoints": [{"dataId": w["data_id"], "accessType": w["access"]}
                                                                  for w in watches]}) if (add or remove) else {}
        for w, bp in zip(watches, answer.get("breakpoints") or []):
            w["verified"], w["message"] = bool(bp.get("verified")), str(bp.get("message") or "")
        s["watches"] = watches
        self._changed()
        return {"watches": [{"name": w["name"], "access": w["access"], "verified": w.get("verified", False),
                             "what": w["description"], **({"note": w["message"]} if w.get("message") else {})}
                            for w in watches]}

    def modules(self, args: dict) -> dict:
        """Loaded modules (libraries, DLLs, packages) with path, version and whether symbols loaded; with
        `sources`, the source files the debugger loaded, including code that has no file."""
        s = self.current("paused", "running")
        listed = None
        if self._caps().get("supportsModulesRequest"):
            try:
                listed = self._dap("modules", {"startModule": 0, "moduleCount": 0}).get("modules")
            except DebugError:
                listed = None
        if listed is None:
            listed = list(s["modules"].values())
        wanted = str(args.get("filter") or "").lower()
        modules = [{"name": m.get("name"), "path": m.get("path"), "version": m.get("version"),
                    "symbols": m.get("symbolStatus"), "optimized": m.get("isOptimized"),
                    "user_code": m.get("isUserCode")}
                   for m in listed if not wanted or wanted in f"{m.get('name')} {m.get('path')}".lower()]
        result = {"modules": [{k: v for k, v in m.items() if v is not None} for m in modules[:300]],
                  "total": len(modules)}
        if args.get("sources"):
            self._need("supportsLoadedSourcesRequest", "list loaded sources")
            sources = self._dap("loadedSources", {}).get("sources") or []
            result["sources"] = [{"name": src.get("name"), "path": self._relative(src.get("path")),
                                  "source_reference": src.get("sourceReference")}
                                 for src in sources[:500] if not wanted or wanted in str(src.get("name")).lower()]
        return result

    def source(self, args: dict) -> dict:
        """The code of a frame that has no file (generated, decompiled or evaluated code), as the debugger shows it."""
        s = self.current("paused")
        reference = args.get("source_reference")
        line = None
        if reference is None:
            frame_id = args.get("frame")
            frame = s["frames"].get(frame_id) if frame_id is not None else None
            if frame is None:
                frames = self.stack({"levels": max(1, int(args.get("frame_index") or 0) + 1)})["frames"]
                index = int(args.get("frame_index") or 0)
                if index >= len(frames):
                    raise DebugError("BAD_REQUEST", f"the stack has {len(frames)} frames")
                frame = frames[index]
            if frame["file"] != "(no source)":
                return {"file": frame["file"], "line": frame["line"],
                        "note": "this frame's code is in a file; read the file itself"}
            reference, line = frame.get("source_reference"), frame.get("line")
            if not reference:
                raise DebugError("NOT_FOUND", "the debugger has no code for this frame; try disassemble")
        body = self._dap("source", {"sourceReference": int(reference), "source": {"sourceReference": int(reference)}})
        lines = clean_text(body.get("content") or "", 400000).splitlines()
        first = max(1, (line or 1) - 40)
        shown = lines[first - 1:first + 119]
        return {"source_reference": reference, "line": line, "total_lines": len(lines),
                "code": [f"{n:>5}{'>' if n == line else ' '} {text[:300]}" for n, text in enumerate(shown, start=first)]}

    def _instruction(self, args: dict) -> tuple[str, int]:
        """The memory reference of a frame's current instruction."""
        s = self.s
        index = int(args.get("frame_index") or 0)
        frames = self.stack({"levels": index + 1})["frames"]
        if index >= len(frames):
            raise DebugError("BAD_REQUEST", f"the stack has {len(frames)} frames")
        reference = frames[index].get("instruction")
        if not reference:
            raise DebugError("NOT_SUPPORTED", f"this debugger ({s['launch'].get('type')}) gives no instruction address")
        return reference, index

    def disassemble(self, args: dict) -> dict:
        """Machine code around a frame's current instruction, for crashes in code without source or in
        optimized builds."""
        self.current("paused")
        self._need("supportsDisassembleRequest", "disassemble")
        reference, _ = self._instruction(args)
        before = max(0, min(int(args.get("before") if args.get("before") is not None else 8), 50))
        after = max(1, min(int(args.get("after") if args.get("after") is not None else 16), 100))
        def address(value) -> int | None:
            try:
                return int(str(value), 16)
            except ValueError:
                return None

        here = address(reference)
        items = self._dap("disassemble", {"memoryReference": reference, "instructionOffset": -before,
                                          "instructionCount": before + after, "resolveSymbols": True}).get("instructions") or []
        if before and not any(address(i.get("address")) == here for i in items):
            # Some debuggers (gdb 15) cannot go backwards from an address: start at the current instruction instead.
            items = self._dap("disassemble", {"memoryReference": reference, "instructionOffset": 0,
                                              "instructionCount": after, "resolveSymbols": True}).get("instructions") or []
        rows = []
        for item in items:
            row = {"address": item.get("address"), "instruction": clean_text(item.get("instruction"), 200)}
            if item.get("symbol"):
                row["symbol"] = clean_text(item["symbol"], 200)
            location = item.get("location") if isinstance(item.get("location"), dict) else {}
            if location.get("path") and item.get("line"):
                row["source"] = f"{self._relative(location['path'])}:{item['line']}"
            if here is not None and address(item.get("address")) == here:
                row["current"] = True
            rows.append(row)
        return {"instructions": rows}

    def memory(self, args: dict) -> dict:
        """Raw bytes of a variable (or at a frame's instruction), as hex. At most 256 bytes; bytes whose text looks
        like a key or token, and variables with secret names, are hidden."""
        s = self.current("paused")
        self._need("supportsReadMemoryRequest", "read memory")
        count = max(1, min(int(args.get("count") or 64), MAX_MEMORY))
        offset = int(args.get("offset") or 0)
        name = args.get("name")
        if name:
            variable, _, _ = self._variable(str(name), self._frame_id(args))
            if variable is None:
                raise DebugError("NOT_FOUND", f"no variable {name} in this frame")
            if is_secret_name(str(name)) or any(is_secret_name(part) for part in split_path(str(name))):
                return {"name": name, "bytes": REDACTED}
            reference = variable.get("memoryReference")
            if not reference:
                raise DebugError("NOT_SUPPORTED", f"the debugger gives no memory address for {name}")
        else:
            reference, _ = self._instruction(args)
        body = self._dap("readMemory", {"memoryReference": reference, "offset": offset, "count": count})
        data = base64.b64decode(body.get("data") or "")[:count]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
        if looks_secret(text) or looks_secret(data.decode("utf-8", "ignore")):
            return {"address": body.get("address") or reference, "bytes": REDACTED}
        rows = [f"{(offset + i):+06x}  {' '.join(f'{b:02x}' for b in data[i:i + 16]):<47}  {text[i:i + 16]}"
                for i in range(0, len(data), 16)]
        result = {"address": body.get("address") or reference, "count": len(data), "rows": rows}
        if body.get("unreadableBytes"):
            result["unreadable"] = body["unreadableBytes"]
        return result

    def locations(self, args: dict) -> dict:
        """The lines in a range where a breakpoint can bind."""
        s = self.current("starting", "running", "paused")
        self._need("supportsBreakpointLocationsRequest", "list the lines where breakpoints bind")
        b = self._breakpoint({"file": args.get("file"), "line": args.get("line")}, s["folder"], s["roots"])
        end = max(b["line"], int(args.get("end_line") or b["line"] + 20))
        body = self._dap("breakpointLocations", {"source": {"path": b["full"]}, "line": b["line"], "endLine": end})
        lines = sorted({loc.get("line") for loc in body.get("breakpoints") or [] if loc.get("line")})
        return {"file": b["file"], "lines": lines}

    # -- control ---------------------------------------------------------------------

    def _move(self, command: str, request: dict, wait_ms: int, step: bool) -> dict:
        s = self.s
        paused_at = (s["location"], s["reason"])
        if step:
            if s["steps_used"] >= s["max_steps"]:
                raise DebugError("LIMIT", f"the approved limit of {s['max_steps']} steps is used up")
            s["steps_used"] += 1
        self._changed(status="running", location=None, reason=None, exception=None)
        before = self.version
        try:
            self._dap(command, request)
        except DebugError:
            if step:
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

    def step(self, args: dict) -> dict:
        s = self.current("paused")
        command = STEP_COMMANDS.get(args.get("kind"))
        if command is None:
            raise DebugError("BAD_REQUEST", "kind is over, into, out or back")
        if s["steps_used"] >= s["max_steps"]:
            raise DebugError("LIMIT", f"the approved limit of {s['max_steps']} steps is used up")
        request: dict = {"threadId": s["thread_id"]}
        if command == "stepBack":
            self._need("supportsStepBack", "step backwards (it needs a recording debugger such as rr)")
        if args.get("single_thread"):
            self._need("supportsSingleThreadExecutionRequests", "step one thread while the others stay paused")
            request["singleThread"] = True
        if args.get("instruction"):
            self._need("supportsSteppingGranularity", "step one machine instruction")
            request["granularity"] = "instruction"
        target = args.get("target")
        if target:
            if command != "stepIn":
                raise DebugError("BAD_REQUEST", "target is for kind into: the call to step into")
            self._need("supportsStepInTargetsRequest", "step into a chosen call")
            frame = self._frame_id({})
            targets = self._dap("stepInTargets", {"frameId": frame}).get("targets") or []
            labels = [str(t.get("label")) for t in targets]
            chosen = next((t for t in targets if str(t.get("label")) == target), None) or next(
                (t for t in targets if str(target).lower() in str(t.get("label")).lower()), None)
            if chosen is None:
                raise DebugError("NOT_FOUND", f"no call {target!r} on this line; calls here: {', '.join(labels) or 'none'}")
            request["targetId"] = chosen.get("id")
        wait_ms = max(0, min(int(args.get("wait_ms") or 15000), 60000))
        return self._move(command, request, wait_ms, step=True)

    def resume(self, args: dict) -> dict:
        s = self.current("paused")
        request: dict = {"threadId": s["thread_id"]}
        command = "continue"
        if args.get("reverse"):
            self._need("supportsStepBack", "run backwards (it needs a recording debugger such as rr)")
            command = "reverseContinue"
        if args.get("single_thread"):
            self._need("supportsSingleThreadExecutionRequests", "run one thread while the others stay paused")
            request["singleThread"] = True
        self._changed(status="running", location=None, reason=None, exception=None)
        self._dap(command, request)
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
        self._options_supported(added)
        new_functions = list(dict.fromkeys(str(n) for n in args.get("add_functions") or []
                                           if n not in {f["name"] for f in s["functions"]}))
        answer = self._relay("breakpoints", {
            "remove": [b["id"] for b in gone + gone_functions if b.get("id")],
            "add": [self._placed(b) for b in added],
            "add_functions": new_functions,
        })
        for b, ident in zip(added, answer.get("breakpoint_ids", [])):
            b["id"] = ident
        s["breakpoints"] = [b for b in s["breakpoints"] if b not in gone] + added
        s["functions"] = [f for f in s["functions"] if f not in gone_functions] + [
            {"name": n, "id": i} for n, i in zip(new_functions, answer.get("function_ids", []))]
        self._changed()
        return {"state": self.snapshot()}

    def screenshot(self, args: dict) -> dict:
        """A picture of the IDE window at this stop, saved under the workspace's autodebug-reports/screenshots."""
        s = self.current("paused")
        name = re.sub(r"[^A-Za-z0-9_.-]", "-", str(args.get("name") or "stop"))[:80]
        file = os.path.join(s["folder"], "autodebug-reports", "screenshots", f"{name}.png")
        return self._relay("screenshot", {"file": file}, timeout=40)

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
