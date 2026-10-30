"""Launch configurations: how one runs on this computer, what is refused before the Approve dialog, and the
program arguments the agent may set (docs/design.md, "Approval" and "Working from a ticket")."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from autodebug.connection import DebugError
from autodebug.redact import looks_secret

#: Test runners `test` knows: how a launch configuration runs one test.
TEST_RUNNERS = "pytest, unittest, go test, jest or vitest"


# Extensions to suggest when a launch configuration's debugger is missing.
DEBUGGER_EXTENSIONS = {
    "debugpy": "Python Debugger", "python": "Python Debugger", "cppdbg": "C/C++", "cppvsdbg": "C/C++",
    "lldb": "CodeLLDB", "lldb-dap": "LLDB DAP", "gdb": "Native Debug", "coreclr": "C#", "java": "Debugger for Java",
    "go": "Go", "php": "PHP Debug",
}


PLATFORM_KEYS = {"win32": "windows", "darwin": "osx"}


_SUBSTITUTION = re.compile(r"\$\{(input|command):([^}]+)\}")


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
