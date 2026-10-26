"""Command line: `setup`, `agents`, `run`, `doctor`, `serve`, `hub`."""

from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from autodebug import __version__, install
from autodebug.connection import discover, state_folder, version_problem

IDES = {"cursor": "Cursor", "vscode": "VS Code", "visualstudio": "Visual Studio"}


def _ok(text: str) -> None:
    print(f"  ok    {text}")


def _bad(text: str) -> None:
    print(f"  FIX   {text}")


#: What `setup` can connect: the three IDEs with an extension, plus agents that only need the MCP entry.
TARGETS = {**IDES, "claude": "Claude Code"}
#: The one step per app that setup cannot do for you (nothing for Claude Code).
LEFT_FOR_YOU = {
    "cursor": "Cursor: Developer: Reload Window in every window. The agent then has the tools as "
              "extension-autodebug, already switched on.",
    "vscode": "VS Code: Developer: Reload Window. The first time the agent uses AutoDebug, allow it to start.",
    "visualstudio": "Visual Studio: open your solution. For Copilot in Visual Studio: chat → Tools → tick autodebug "
                    "(Visual Studio starts MCP tools switched off). Cursor and Claude Code need nothing more.",
}


def detect() -> list[str]:
    """The IDEs and agents installed on this computer that setup can connect."""
    found = [ide for ide in ("vscode", "cursor") if install.ide_command(ide)]
    if install.vsix_installer():
        found.append("visualstudio")
    if install.claude_present():
        found.append("claude")
    return found


def _setup_visual_studio(args: argparse.Namespace) -> tuple[bool, list[str]]:
    failed = False
    if not args.no_install:
        installer = install.vsix_installer()
        if installer is None:
            _bad("could not find Visual Studio 2022 or 2026 (vswhere.exe found no installation)")
            failed = True
        elif install.visual_studio_running():
            _bad("Visual Studio is open; close every Visual Studio window (File → Exit), then run setup again")
            failed = True
        else:
            try:
                vsix = Path(args.vsix).expanduser().resolve() if args.vsix else install.download_vs_extension(
                    __version__, state_folder() / "extension")
                if not vsix.is_file():
                    raise ValueError(f"there is no file {vsix}")
            except (OSError, ValueError) as exc:
                _bad(f"could not get the extension ({exc}). Download AutoDebug.VisualStudio.vsix for version "
                     f"{__version__} from {install.VS_RELEASE.format(version=__version__)} and run: "
                     f"{you_run()} setup visualstudio --vsix <file>")
                vsix = None
                failed = True
            if vsix is not None:
                result = install.install_vs_extension(installer, vsix)
                if result.returncode == 0:
                    _ok("extension installed in Visual Studio")
                elif result.returncode == install.VSIX_BLOCKED:
                    _bad("Visual Studio or one of its helper processes is still running; wait a few seconds after "
                         "closing it, then run setup again")
                    failed = True
                else:
                    _bad(f"VSIXInstaller could not install it (exit code {result.returncode}); its log is the newest "
                         r"dd_VSIXInstaller_*.log in %TEMP%")
                    failed = True
    path = install.write_config("visualstudio", args.folder)
    _ok(f"Visual Studio: MCP server added to {path} (for Copilot in Visual Studio)")
    return failed, [LEFT_FOR_YOU["visualstudio"]]


def _setup_editor(ide: str, args: argparse.Namespace) -> tuple[bool, list[str]]:
    """VS Code or Cursor: install the extension with the IDE's own command, then write the MCP entry."""
    name = IDES[ide]
    failed = False
    if not args.no_install:
        vsix = install.build_vsix(state_folder() / "extension")
        command = install.ide_command(ide)
        if command is None:
            _bad(f"could not find the `{'code' if ide == 'vscode' else 'cursor'}` command. In {name}: "
                 f"Extensions → ··· → Install from VSIX… → {vsix}")
            failed = True
        else:
            result = install.install_extension(command, vsix)
            if result.returncode == 0:
                _ok(f"extension installed in {name}")
            else:
                _bad(f"{name} could not install the extension: {(result.stderr or result.stdout).strip()[:300]}")
                failed = True
    if ide == "cursor":
        # The extension registers the server with Cursor itself (switched on, every tool); an mcp.json entry
        # would start switched off and make the extension stand aside, so remove the one older setups wrote.
        for folder in [None] + ([args.folder] if args.folder else []):
            removed = install.remove_config(ide, folder)
            if removed:
                _ok(f"Cursor: removed the old autodebug entry from {removed}")
        _ok(f"Cursor: the extension registers the MCP server itself (from {install.server_file()})")
        return failed, [LEFT_FOR_YOU[ide]]
    path = install.write_config(ide, args.folder)
    _ok(f"{name}: MCP server added to {path} ({'this project' if args.folder else 'every project'})")
    return failed, [LEFT_FOR_YOU[ide]]


def _setup_claude(args: argparse.Namespace) -> tuple[bool, list[str]]:
    path = install.write_config("claude", args.folder)
    _ok(f"Claude Code: MCP server added to {path} ({'this project' if args.folder else 'every project'})")
    return False, []


def _self_update(args: argparse.Namespace) -> int | None:
    """Before connecting anything: when PyPI has a newer AutoDebug, install it and run setup again with
    the new code. Returns that run's exit code, or None to go on with this version (no newer one, a source
    checkout, offline, --no-update, or the update failed, which is reported)."""
    if args.no_update or _from_checkout() or os.environ.get("AUTODEBUG_UPDATED") == "1":
        return None
    latest = install.latest_version()
    if not latest or not install.is_newer(latest, __version__):
        return None
    print(f"Updating AutoDebug {__version__} → {latest} (the older copy is replaced)")
    try:
        result = install.upgrade_self(latest)
    except (OSError, subprocess.SubprocessError) as exc:
        result = subprocess.CompletedProcess([], 1, "", str(exc))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:] or [""]
        _bad(f"could not update automatically ({detail[0][:200]}); run: {_upgrade_command(latest)}. "
             f"Going on with {__version__}.")
        return None
    _ok(f"AutoDebug {latest} installed; continuing with it\n")
    again = [sys.executable, "-m", "autodebug", "setup", *args.argv[1:]]
    sys.stdout.flush()  # our lines first, then the new version's
    return subprocess.run(again, env=dict(os.environ, AUTODEBUG_UPDATED="1"), check=False).returncode


def _setup(args: argparse.Namespace) -> int:
    updated = _self_update(args)
    if updated is not None:
        return updated
    target, folder = args.ide, args.folder
    if target and target not in TARGETS and target != "all":
        if folder:
            raise ValueError(f"unknown IDE {target!r}; use one of: {', '.join(TARGETS)}")
        target, folder = None, target  # `autodebug setup C:\path\to\project`
    args.folder = folder
    targets = detect() if target in (None, "all") else [target]
    if not targets:
        _bad("found none of VS Code, Cursor, Visual Studio 2022/2026 or Claude Code; install one, or name it: "
             f"{you_run()} setup cursor|vscode|visualstudio|claude")
        return 1
    print(f"Setting up AutoDebug {__version__} for {', '.join(TARGETS[t] for t in targets)}\n")
    install.write_server_file()
    failed, left = False, []
    for name in targets:
        if name == "visualstudio":
            bad, steps = _setup_visual_studio(args)
        elif name == "claude":
            bad, steps = _setup_claude(args)
        else:
            bad, steps = _setup_editor(name, args)
        failed |= bad
        left += steps
    if folder:
        _ok(f"agent instructions written to {install.write_agent_instructions(folder, run_command())}")
    open_folders = [f for window in discover() for f in window.folders]
    for path in install.refresh_agent_instructions(run_command(), open_folders):
        _ok(f"agent instructions updated to this AutoDebug in {path}")
    if args.no_update or _from_checkout():  # otherwise _self_update already looked
        _update_notice()
    print("\nLeft for you:" if left else "\nNothing left to set up.")
    for number, step in enumerate(left, 1):
        print(f"  {number}. {step}")
    print(f"""
Then open your project, start a new agent chat and ask, for example:
  "Use the autodebug tools to find why <the bug> happens and write a report."
Click Approve when the IDE asks. Check everything with: {you_run()} doctor""")
    return 1 if failed else 0


def _upgrade_command(version: str | None = None) -> str:
    """The manual update command, with an exact version so pip's cached package list cannot hold it back."""
    if _from_checkout():
        return "git pull in the AutoDebug folder"
    pinned = f"autodebug=={version}" if version else "autodebug"
    if you_run() == "py -m autodebug":
        return f"py -m pip install --upgrade --no-cache-dir {pinned}"
    return f"pipx install --force {pinned} (or: pip install --upgrade --no-cache-dir {pinned})"


def _update_notice() -> bool:
    """Say when PyPI has a newer AutoDebug than this one; True when it does."""
    latest = install.latest_version()
    if latest and install.is_newer(latest, __version__):
        how = (f"{_upgrade_command(latest)}" if _from_checkout()
               else f"{you_run()} setup installs it and reconnects everything")
        _bad(f"AutoDebug {latest} is available (this is {__version__}): {how}")
        return True
    return False


def _agents(args: argparse.Namespace) -> int:
    path = install.write_agent_instructions(args.folder, run_command())
    _ok(f"AutoDebug section written to {path}")
    print(f"  Agents that read AGENTS.md (Cursor, Copilot, Codex, ...) now know to run `{run_command()} run ...`\n"
          "  when the MCP tools are missing. Claude Code reads CLAUDE.md: add the line @AGENTS.md there.")
    return 0


def _serve(args: argparse.Namespace) -> int:
    logging.basicConfig(stream=sys.stderr, level=args.log_level.upper(), format="autodebug: %(message)s")
    from autodebug import hub
    from autodebug.mcp_server import Server

    if sys.stdin.isatty():
        print("autodebug serve is started by your IDE's MCP settings; it is not interactive. Ctrl+C to quit.",
              file=sys.stderr)
    if args.direct:
        Server().serve()
        return 0
    local: list = []

    def runner(name: str, arguments: dict) -> tuple[dict, bool]:
        """Tools run in the shared service, so `autodebug run` sees the same session; without it, here."""
        if not local:
            try:
                return hub.call(name, arguments)
            except hub.ServiceError as exc:
                logging.getLogger("autodebug").warning("%s; running tools in this process instead", exc)
                local.append(Server())
        return local[0]._local(name, arguments)

    Server(runner=runner).serve()
    return 0


def _hub(args: argparse.Namespace) -> int:
    logging.basicConfig(stream=sys.stderr, level="INFO", format="%(asctime)s autodebug service: %(message)s")
    from autodebug import hub

    running = hub.status()
    if running and (running.get("version"), running.get("code")) == (__version__, hub.code_id()):
        print(f"the AutoDebug service is already running (process {running.get('pid')})", file=sys.stderr)
        return 0
    service = hub.Hub(idle_seconds=args.idle_minutes * 60)
    logging.getLogger("autodebug").info("version %s listening on 127.0.0.1:%s", __version__, service.port)
    service.serve()
    return 0


def _from_checkout() -> bool:
    package = Path(__file__).resolve().parent
    return package.parent.name == "src" and (package.parents[1] / "pyproject.toml").is_file()


def _quoted(parts: list[str]) -> str:
    if not any(" " in part for part in parts):
        return " ".join(parts)
    quoted = " ".join(f'"{part}"' if " " in part else part for part in parts)
    return f"& {quoted}" if os.name == "nt" else quoted  # PowerShell runs a quoted program only after &


def _py_is_this_python() -> bool:
    """Whether the Windows `py` launcher starts this same Python, so `py -m autodebug` runs this AutoDebug."""
    launcher = shutil.which("py") if os.name == "nt" else None
    if not launcher:
        return False
    try:
        done = subprocess.run([launcher, "-c", "import sys; print(sys.executable)"], capture_output=True, text=True,
                              timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return os.path.normcase(done.stdout.strip()) == os.path.normcase(sys.executable)


def run_command() -> str:
    """How an agent's terminal runs this AutoDebug, written into AGENTS.md and the MCP instructions: the
    `autodebug` command when it is on PATH, else this Python with `-m autodebug` (a checkout: its folder)."""
    if _from_checkout():
        return _quoted([Path(sys.executable).as_posix(), Path(__file__).resolve().parent.as_posix()])
    if shutil.which("autodebug"):
        return "autodebug"
    return _quoted([Path(sys.executable).as_posix(), "-m", "autodebug"])


@functools.cache
def you_run() -> str:
    """The command to tell the developer in messages: what works in their terminal on this computer.
    On Windows pip puts `autodebug.exe` in a folder that is not on PATH, but `py -m autodebug` works."""
    if not _from_checkout() and shutil.which("autodebug"):
        return "autodebug"
    if _py_is_this_python():
        return "py -m autodebug"
    return run_command()


def _coerce(key: str, text: str, schema: dict):
    """One `key=value` from the command line, read by the tool's schema so no JSON quoting is needed:
    breakpoints=geometry.cpp:16,util.cpp:4  variables=total,i  max_steps=50  after=false."""
    if text[:1] in "[{" and schema.get("type") in ("array", "object"):
        return json.loads(text)
    kind = schema.get("type")
    if kind == "integer":
        return int(text)
    if kind == "number":
        return float(text)
    if kind == "boolean":
        if text.lower() in ("true", "yes", "1", "on"):
            return True
        if text.lower() in ("false", "no", "0", "off"):
            return False
        raise ValueError(f"{key} must be true or false")
    if kind == "object" and {"file", "line"} <= schema.get("properties", {}).keys():
        file, _, line = text.rpartition(":")
        if not file or not line.isdigit():
            raise ValueError(f"{key} must be file:line, e.g. {key}=geometry.cpp:16")
        return {"file": file, "line": int(line)}
    if kind == "array":
        return [_coerce(key, part.strip(), schema["items"]) for part in text.split(",") if part.strip()]
    return text


def parse_tool_arguments(name: str, pairs: list[str]) -> dict:
    from autodebug.mcp_server import TOOLS

    properties = TOOLS[name][1]["properties"]
    arguments: dict = {}
    for pair in pairs:
        key, equals, text = pair.partition("=")
        if not equals:
            raise ValueError(f"expected key=value, got {pair!r}")
        if key not in properties:
            raise ValueError(f"{name} has no argument {key!r}; it takes: {', '.join(properties) or 'nothing'}")
        value = _coerce(key, text, properties[key])
        if isinstance(value, list) and isinstance(arguments.get(key), list):
            arguments[key] += value  # a repeated key adds to the list
        else:
            arguments[key] = value
    return arguments


def tool_guide() -> str:
    from autodebug.mcp_server import INSTRUCTIONS, TOOLS

    command = run_command()
    lines = [f"Usage: {command} run <tool> key=value ...   (prints the tool's JSON result)", "",
             "The same tools as the AutoDebug MCP server, in the same session. Values need no JSON:",
             "  breakpoints=geometry.cpp:16,other.cpp:4   variables=total,i   after=false", "",
             "Example:",
             f'  {command} run list_targets ide=visualstudio',
             f'  {command} run start_session ide=visualstudio "launch_configuration=geometry (Debug|x64)" '
             'breakpoints=geometry.cpp:16 "goal=find why moving a shape changes its area"', "", "Tools:"]
    for name, (description, schema) in TOOLS.items():
        required = set(schema.get("required", ()))
        keys = " ".join(k if k in required else f"[{k}]" for k in schema["properties"])
        lines.append(f"  {name} {keys}".rstrip())
        lines.append(f"      {description}")
    lines += ["", "How to debug:", INSTRUCTIONS]
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> int:
    from autodebug import hub
    from autodebug.mcp_server import TOOLS, argument_problem

    if not args.tool or args.tool in ("help", "-h", "--help"):
        print(tool_guide())
        return 0 if args.tool else 2
    if args.tool not in TOOLS:
        print(f"autodebug: unknown tool {args.tool!r}; tools: {', '.join(TOOLS)}", file=sys.stderr)
        return 2
    try:
        arguments = parse_tool_arguments(args.tool, args.arguments)
    except ValueError as exc:
        print(f"autodebug: {exc}", file=sys.stderr)
        return 2
    problem = argument_problem(arguments, TOOLS[args.tool][1])
    if problem:
        print(f"autodebug: {args.tool}: {problem}", file=sys.stderr)
        return 2
    try:
        result, is_error = hub.call(args.tool, arguments)
    except hub.ServiceError as exc:
        print(json.dumps({"error": "NO_SERVICE", "message": str(exc)}, indent=1))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 1 if is_error else 0


def _doctor(args: argparse.Namespace) -> int:
    print(f"AutoDebug {__version__} doctor\n")
    problems = 0
    where = "a source checkout" if _from_checkout() else "installed"
    _ok(f"AutoDebug {__version__}, {where} at {Path(__file__).resolve().parent}, run with {sys.executable}")
    _ok(f"in a terminal: {you_run()}")
    if _update_notice():
        problems += 1
    if sys.version_info >= (3, 11):
        _ok(f"Python {sys.version.split()[0]}")
    else:
        _bad(f"Python {sys.version.split()[0]}: AutoDebug needs 3.11 or newer")
        problems += 1
    server = install.read_config(install.server_file())
    if server.get("command") == sys.executable:
        _ok(f"VS Code and Cursor windows can register the server themselves ({install.server_file()})")
    else:
        print(f"  -     {install.server_file()} is missing or names another Python; run `{you_run()} setup` so "
              "VS Code and Cursor windows can register the server themselves")
    for ide, name in TARGETS.items():
        for folder in [None] + ([args.folder] if args.folder else []):
            entry = install.configured_entry(ide, folder)
            where = install.config_file(ide, folder)
            if ide == "cursor":  # the extension registers the server; an mcp.json entry only gets in its way
                if entry is not None:
                    _bad(f"Cursor: {where} still starts autodebug, so Cursor shows it switched off; run "
                         f"`{you_run()} setup cursor` to let the extension register it instead")
                    problems += 1
                continue
            if entry is None:
                if folder is None:
                    print(f"  -     {name}: not set up ({where})")
                continue
            if "--demo" in entry.get("args", []) or entry.get("args", [])[-1:] != ["serve"]:
                _bad(f"{name}: {where} starts an old server command; run `{you_run()} setup {ide}"
                     + (f" {folder}" if folder else "") + "`")
                problems += 1
            elif entry.get("command") != sys.executable:
                _bad(f"{name}: {where} uses {entry.get('command')}, not this Python; run `{you_run()} setup {ide}`")
                problems += 1
            else:
                _ok(f"{name}: {where}")
    windows = discover()
    for window in windows:
        if window.current:
            _ok(f"{IDES.get(window.ide, window.ide)} window open: {', '.join(window.folders)}")
        else:
            _bad(version_problem(window).message.replace("Ask the developer to run", "Run").replace(
                "Ask the developer to update", "Update"))
            problems += 1
    if not windows:
        print("  -     no VS Code, Cursor or Visual Studio window is running the extension (open your project in the IDE)")
    from autodebug import hub

    try:
        hub.connect_service()
        running = hub.status() or {}
        _ok(f"AutoDebug service {running.get('version')} running (process {running.get('pid')})"
            + ("; a debug session is open" if running.get("busy") else ""))
    except hub.ServiceError as exc:
        _bad(str(exc))
        problems += 1
    print(f"  ok    terminal command for agents: {run_command()} run help")
    if args.folder:
        agents_md = Path(args.folder).resolve() / "AGENTS.md"
        if install.has_agent_instructions(args.folder) and install.agent_instructions(run_command()) not in \
                agents_md.read_text(encoding="utf-8"):
            _bad(f"{agents_md} tells agents to run another AutoDebug; run `{you_run()} setup {args.folder}`")
            problems += 1
        elif install.has_agent_instructions(args.folder):
            _ok(f"agent instructions in {agents_md}")
        else:
            _bad(f"no AutoDebug section in {Path(args.folder).resolve() / 'AGENTS.md'}; run `{you_run()} agents {args.folder}`")
            problems += 1
    print("\nReady." if not problems else f"\n{problems} thing(s) to fix.")
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autodebug",
        description="Let an AI agent debug your program with the debugger of VS Code, Cursor or Visual Studio.",
        epilog="Start here: autodebug setup",
    )
    parser.add_argument("--version", action="version", version=f"autodebug {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    setup = commands.add_parser("setup", help="connect every IDE and agent found (or the one named)")
    setup.add_argument("ide", nargs="?", metavar="ide", help="cursor, vscode, visualstudio or claude (default: all found)")
    setup.add_argument("folder", nargs="?", help="a project folder: its own MCP entries and AGENTS.md")
    setup.add_argument("--no-install", action="store_true", help="only write the MCP entry")
    setup.add_argument("--no-update", action="store_true", help="do not install a newer AutoDebug from PyPI first")
    setup.add_argument("--vsix", help="Visual Studio: install this extension package instead of downloading it")
    setup.set_defaults(handler=_setup)
    run = commands.add_parser("run", help="call a debugging tool from a terminal (`run help` lists them)",
                              add_help=False)
    run.add_argument("tool", nargs="?")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    run.set_defaults(handler=_run)
    serve = commands.add_parser("serve", help="run the MCP server (the IDE starts this for you)")
    serve.add_argument("--log-level", default="warning", choices=("debug", "info", "warning", "error"))
    serve.add_argument("--direct", action="store_true", help="run tools in this process, not the shared service")
    serve.set_defaults(handler=_serve)
    service = commands.add_parser("hub", help="run the AutoDebug service (started for you when needed)")
    service.add_argument("--idle-minutes", type=float, default=30)
    service.set_defaults(handler=_hub)
    agents = commands.add_parser("agents", help="write the AutoDebug section of <folder>/AGENTS.md for agents")
    agents.add_argument("folder")
    agents.set_defaults(handler=_agents)
    doctor = commands.add_parser("doctor", help="check the setup")
    doctor.add_argument("folder", nargs="?", help="also check this project's MCP files")
    doctor.set_defaults(handler=_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.argv = list(sys.argv[1:] if argv is None else argv)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"autodebug: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
