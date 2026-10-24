"""Command line: `setup`, `serve`, `doctor`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from autodebug import __version__, install
from autodebug.connection import PROTOCOL, bridges_folder, discover, state_folder

IDES = {"cursor": "Cursor", "vscode": "VS Code"}
PROMPT = ("Help me debug AutoDebugDemo: moving a shape changes its area. Use the autodebug tools to find the "
          "root cause and write a report.")


def _ok(text: str) -> None:
    print(f"  ok    {text}")


def _bad(text: str) -> None:
    print(f"  FIX   {text}")


def _setup(args: argparse.Namespace) -> int:
    name = IDES[args.ide]
    print(f"Setting up AutoDebug for {name}\n")
    failed = False
    if not args.no_install:
        vsix = install.build_vsix(state_folder() / "extension")
        command = install.ide_command(args.ide)
        if command is None:
            _bad(f"could not find the `{'code' if args.ide == 'vscode' else 'cursor'}` command. In {name}: "
                 f"Extensions → ··· → Install from VSIX… → {vsix}")
            failed = True
        else:
            result = install.install_extension(command, vsix)
            if result.returncode == 0:
                _ok(f"extension installed in {name}")
            else:
                _bad(f"{name} could not install the extension: {(result.stderr or result.stdout).strip()[:300]}")
                failed = True
    path = install.write_config(args.ide, args.folder)
    scope = "this project" if args.folder else "every project"
    _ok(f"MCP server `autodebug` added to {path} ({scope})")
    print(f"""
Next, in {name}:
  1. Command Palette → Developer: Reload Window. The status bar shows "AutoDebug".
  2. {"Cursor Settings → MCP: turn on autodebug." if args.ide == "cursor" else "Command Palette → MCP: List Servers → autodebug → Start Server."}
  3. Open your project folder and ask the agent, for example:
     "{PROMPT}"
  4. Click Approve when {name} asks.""")
    return 1 if failed else 0


def _serve(args: argparse.Namespace) -> int:
    logging.basicConfig(stream=sys.stderr, level=args.log_level.upper(), format="autodebug: %(message)s")
    from autodebug.mcp_server import Server

    if sys.stdin.isatty():
        print("autodebug serve is started by your IDE's MCP settings; it is not interactive. Ctrl+C to quit.",
              file=sys.stderr)
    Server().serve()
    return 0


def _doctor(args: argparse.Namespace) -> int:
    print(f"AutoDebug {__version__} doctor\n")
    problems = 0
    if sys.version_info >= (3, 11):
        _ok(f"Python {sys.version.split()[0]}")
    else:
        _bad(f"Python {sys.version.split()[0]}: AutoDebug needs 3.11 or newer")
        problems += 1
    for ide, name in IDES.items():
        for folder in [None] + ([args.folder] if args.folder else []):
            entry = install.configured_entry(ide, folder)
            where = install.config_file(ide, folder)
            if entry is None:
                if folder is None:
                    print(f"  -     {name}: not set up ({where})")
                continue
            if "--demo" in entry.get("args", []) or entry.get("args", [])[-1:] != ["serve"]:
                _bad(f"{name}: {where} starts an old server command; run `autodebug setup {ide}"
                     + (f" {folder}" if folder else "") + "`")
                problems += 1
            elif entry.get("command") != sys.executable:
                _bad(f"{name}: {where} uses {entry.get('command')}, not this Python; run `autodebug setup {ide}`")
                problems += 1
            else:
                _ok(f"{name}: {where}")
    windows = discover()
    stale = [p for p in bridges_folder().glob("*.json") if _old_protocol(p)] if bridges_folder().is_dir() else []
    if windows:
        for window in windows:
            _ok(f"{IDES.get(window.ide, window.ide)} window open: {', '.join(window.folders)}")
    else:
        print("  -     no VS Code or Cursor window is running the extension (open your project in the IDE)")
    if stale:
        _bad("an older AutoDebug extension is still running; run `autodebug setup` again and reload the window")
        problems += 1
    print("\nReady." if not problems else f"\n{problems} thing(s) to fix.")
    return 1 if problems else 0


def _old_protocol(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("protocol") != PROTOCOL
    except (OSError, ValueError):
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autodebug",
        description="Let an AI agent debug your program with VS Code's or Cursor's own debugger.",
        epilog="Start here: autodebug setup cursor   (or: autodebug setup vscode)",
    )
    parser.add_argument("--version", action="version", version=f"autodebug {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    setup = commands.add_parser("setup", help="install the extension and connect the IDE's AI agent")
    setup.add_argument("ide", choices=sorted(IDES))
    setup.add_argument("folder", nargs="?", help="write the MCP entry for this project only")
    setup.add_argument("--no-install", action="store_true", help="only write the MCP entry")
    setup.set_defaults(handler=_setup)
    serve = commands.add_parser("serve", help="run the MCP server (the IDE starts this for you)")
    serve.add_argument("--log-level", default="warning", choices=("debug", "info", "warning", "error"))
    serve.set_defaults(handler=_serve)
    doctor = commands.add_parser("doctor", help="check the setup")
    doctor.add_argument("folder", nargs="?", help="also check this project's MCP files")
    doctor.set_defaults(handler=_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
