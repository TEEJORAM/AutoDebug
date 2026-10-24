"""Command-line interface.

    autodebug serve   [--evidence-dir DIR] [--demo] [--log-level LEVEL]
    autodebug doctor  [--evidence-dir DIR] [--json]
    autodebug config  {vscode,claude-code,claude-desktop,cursor} [--demo] [--evidence-dir DIR] [--name NAME]
    autodebug --version

`serve` speaks MCP over stdio: stdout carries only JSON-RPC, everything else
goes to stderr. The legacy form `autodebug --evidence-dir DIR [--demo]` still
serves.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import secrets
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from autodebug import __version__
from autodebug.adapters import ALL_ADAPTERS
from autodebug.evidence import inside_source_checkout, secure_storage_supported
from autodebug.models import CapabilityState

PROG = "autodebug"
EVIDENCE_ENV = "AUTODEBUG_EVIDENCE_DIR"
CLIENTS = ("vscode", "claude-code", "claude-desktop", "cursor")
MIN_PYTHON = (3, 11)

_DESCRIPTION = """\
AutoDebug: a local MCP server that lets an AI client investigate bugs through
your IDE's debugger, behind plan-bound human approval.

Fake-only build: only the synthetic demo debugger is operational; real IDE
debugger control is disabled until the security gate is approved."""

_EPILOG = """\
quick start:
  autodebug doctor                 check this machine
  autodebug serve --demo           run the server with the synthetic demo case
  autodebug config vscode --demo   print a VS Code .vscode/mcp.json entry

docs: docs/getting-started.md in the AutoDebug repository"""


# -- evidence location ---------------------------------------------------


def default_evidence_dir() -> Path:
    """Per-user, private state location, by platform convention."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif system == "Darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "autodebug"


def resolve_evidence_dir(explicit: str | None) -> Path:
    """`--evidence-dir`, else `$AUTODEBUG_EVIDENCE_DIR`, else the default."""
    raw = explicit or os.environ.get(EVIDENCE_ENV)
    return (Path(raw).expanduser() if raw else default_evidence_dir()).absolute()


def create_run_dir(root: Path) -> Path:
    """Create a fresh private folder for one server run inside `root`."""
    if inside_source_checkout(root):
        raise ValueError(f"evidence directory must be outside the AutoDebug checkout: {root}")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"evidence directory is not a real directory: {root}")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = root / f"run-{stamp}-{secrets.token_hex(3)}"
    run_dir.mkdir(mode=0o700)
    return run_dir


# -- serve ------------------------------------------------------------------


def _serve(args: argparse.Namespace) -> int:
    from autodebug.server import PROTOCOL_VERSION, StdioServer, build_dispatcher

    logging.basicConfig(stream=sys.stderr, level=args.log_level.upper(), format=f"{PROG}: %(levelname)s: %(message)s")
    if args.demo and not secure_storage_supported():
        raise ValueError(f"--demo needs evidence storage, which is not supported on {platform.system()}; "
                         "use Linux, macOS or WSL (see `autodebug doctor`)")
    run_dir = create_run_dir(resolve_evidence_dir(args.evidence_dir))
    dispatcher = build_dispatcher(run_dir, demo=args.demo)
    mode = "demo case AUTODEBUG-DEMO armed" if args.demo else "no approved cases"
    _err(f"{PROG} {__version__} | MCP stdio {PROTOCOL_VERSION} | fake-only, real debuggers disabled | {mode}")
    _err(f"{PROG}: evidence: {run_dir}")
    if sys.stdin.isatty():
        _err(f"{PROG}: waiting for an MCP client on stdin; this is not an interactive shell (Ctrl+C to quit)")
    StdioServer(dispatcher).serve()
    return 0


# -- doctor -----------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    status: str  # "ok" | "warn" | "fail" | "info"
    name: str
    detail: str


def _evidence_check(root: Path) -> Check:
    if inside_source_checkout(root):
        return Check("fail", "Evidence folder", f"{root} is inside the AutoDebug checkout; choose another")
    if root.is_symlink():
        return Check("fail", "Evidence folder", f"{root} is a symlink; use a real directory")
    if root.exists():
        if not root.is_dir():
            return Check("fail", "Evidence folder", f"{root} is not a directory")
        if not os.access(root, os.W_OK | os.X_OK):
            return Check("fail", "Evidence folder", f"{root} is not writable")
        info = root.stat()
        if hasattr(os, "getuid") and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            return Check("warn", "Evidence folder", f"{root} is not private (run: chmod 700 '{root}')")
        return Check("ok", "Evidence folder", str(root))
    parent = root.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not os.access(parent, os.W_OK | os.X_OK):
        return Check("fail", "Evidence folder", f"{root} cannot be created ({parent} is not writable)")
    return Check("ok", "Evidence folder", f"{root} (created on first run)")


def run_checks(evidence_dir: Path) -> list[Check]:
    version = ".".join(map(str, sys.version_info[:3]))
    system = platform.system()
    checks = [
        Check("ok", "Python", version) if sys.version_info >= MIN_PYTHON
        else Check("fail", "Python", f"{version}; AutoDebug needs 3.11 or newer"),
        Check("info", "Platform", f"{system} {platform.release()}"),
        Check("ok", "Evidence storage", "supported") if secure_storage_supported()
        else Check("fail", "Evidence storage", f"not supported on {system}; cases fail closed (use Linux, macOS or WSL)"),
        _evidence_check(evidence_dir),
        Check("ok", "Demo debugger", "synthetic, ready for `serve --demo`"),
    ]
    targets = [
        cls.ide_id for cls in ALL_ADAPTERS
        if cls().probe_capabilities(backend=None, host_os=system).state is not CapabilityState.NOT_APPLICABLE
    ]
    checks.append(Check("info", "IDE adapters", f"{', '.join(targets) or 'none'} target this OS; "
                                                "mock-only, no native debugger client yet"))
    checks.append(Check("info", "Real debuggers", "disabled until the T05 security gate is approved"))
    return checks


_SYMBOLS = {"ok": ("✔", "ok"), "warn": ("!", "warn"), "fail": ("✘", "FAIL"), "info": ("·", "-")}
_COLORS = {"ok": "32", "warn": "33", "fail": "31", "info": "2"}


def _use_color(stream) -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb" or not stream.isatty():
        return False
    return os.name != "nt" or "WT_SESSION" in os.environ or "TERM" in os.environ


def _can_encode(stream, text: str) -> bool:
    try:
        text.encode(stream.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _doctor(args: argparse.Namespace) -> int:
    checks = run_checks(resolve_evidence_dir(args.evidence_dir))
    ready = not any(c.status == "fail" for c in checks)
    if args.json:
        print(json.dumps({"version": __version__, "ready": ready, "checks": [c.__dict__ for c in checks]}, indent=2))
        return 0 if ready else 1
    out = sys.stdout
    fancy = _can_encode(out, "✔✘·")
    color = _use_color(out)
    width = max(len(c.name) for c in checks)
    print(f"AutoDebug doctor ({PROG} {__version__})\n")
    for check in checks:
        symbol = _SYMBOLS[check.status][0 if fancy else 1].ljust(1 if fancy else 4)
        if color:
            symbol = f"\033[{_COLORS[check.status]}m{symbol}\033[0m"
        print(f"  {symbol} {check.name:<{width}}  {check.detail}")
    print()
    if ready:
        print(f"Ready. Next: `{PROG} serve --demo`, or `{PROG} config vscode --demo` to connect a client.")
    else:
        print("Not ready: fix the failed checks above. See docs/getting-started.md.")
    return 0 if ready else 1


# -- config -----------------------------------------------------------------


def _source_pythonpath() -> str | None:
    """`src/` when running from a source checkout rather than an install."""
    import autodebug

    src = Path(autodebug.__file__).resolve().parents[1]
    if src.name == "src" and (src.parent / "pyproject.toml").is_file():
        return str(src)
    return None


def server_spec(*, demo: bool, evidence_dir: str | None) -> dict:
    """The command a client should launch, with an absolute interpreter."""
    args = ["-m", "autodebug", "serve"]
    if evidence_dir:
        args += ["--evidence-dir", str(Path(evidence_dir).expanduser().absolute())]
    if demo:
        args.append("--demo")
    spec: dict = {"command": sys.executable, "args": args}
    pythonpath = _source_pythonpath()
    if pythonpath:
        spec["env"] = {"PYTHONPATH": pythonpath}
    return spec


def _quote(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def render_config(client: str, name: str, spec: dict) -> tuple[str, str]:
    """Return `(output, where_to_put_it)` for one client."""
    if client == "claude-code":
        parts = ["claude", "mcp", "add"]
        for key, value in spec.get("env", {}).items():
            parts += ["--env", f"{key}={value}"]
        parts += ["--transport", "stdio", name, "--", spec["command"], *spec["args"]]
        return _quote(parts), "Run this in your project folder (add `--scope user` for all projects)."
    if client == "vscode":
        body = {"servers": {name: {"type": "stdio", **spec}}}
        where = "Save as .vscode/mcp.json in your workspace, or run 'MCP: Open User Configuration' and merge it."
    elif client == "cursor":
        body = {"mcpServers": {name: {"type": "stdio", **spec}}}
        where = "Save as .cursor/mcp.json in your project, or ~/.cursor/mcp.json for all projects."
    else:
        body = {"mcpServers": {name: spec}}
        location = {
            "Windows": r"%APPDATA%\Claude\claude_desktop_config.json",
            "Darwin": "~/Library/Application Support/Claude/claude_desktop_config.json",
        }.get(platform.system(), "claude_desktop_config.json")
        where = f"Merge into {location} (Settings > Developer > Edit Config), then restart Claude Desktop."
    return json.dumps(body, indent=2), where


def _config(args: argparse.Namespace) -> int:
    spec = server_spec(demo=args.demo, evidence_dir=args.evidence_dir)
    output, where = render_config(args.client, args.name, spec)
    print(output)
    _err(f"\n{PROG}: {where}")
    if not secure_storage_supported():
        _err(f"{PROG}: warning: evidence storage is not supported on {platform.system()}; "
             "the server starts but every case fails. Run AutoDebug on Linux, macOS or WSL.")
    return 0


# -- entry point --------------------------------------------------------------


def _err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _add_evidence_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--evidence-dir", metavar="DIR",
        help=f"private evidence folder outside any checkout (default: ${EVIDENCE_ENV} or {default_evidence_dir()})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description=_DESCRIPTION, epilog=_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    serve = sub.add_parser("serve", help="run the MCP server on stdio (used by MCP clients)",
                           description="Run the MCP stdio server. Each run stores evidence in a new private folder.")
    _add_evidence_option(serve)
    serve.add_argument("--demo", action="store_true",
                       help="seed and arm the synthetic AUTODEBUG-DEMO case (30-minute local approval, no real debugger)")
    serve.add_argument("--log-level", default="warning", choices=("debug", "info", "warning", "error"),
                       help="stderr log level (default: warning)")
    serve.set_defaults(handler=_serve)

    doctor = sub.add_parser("doctor", help="check Python, platform, evidence folder and adapters",
                            description="Check whether this machine can run AutoDebug. Creates nothing.")
    _add_evidence_option(doctor)
    doctor.add_argument("--json", action="store_true", help="machine-readable output")
    doctor.set_defaults(handler=_doctor)

    config = sub.add_parser("config", help="print MCP client configuration",
                            description="Print a ready-to-use configuration entry for an MCP client.")
    config.add_argument("client", choices=CLIENTS)
    config.add_argument("--demo", action="store_true", help="configure the server to start the synthetic demo")
    _add_evidence_option(config)
    config.add_argument("--name", default="autodebug", help="server name shown in the client (default: autodebug)")
    config.set_defaults(handler=_config)
    return parser


def _legacy_serve_argv(argv: list[str]) -> list[str]:
    """Map the legacy `autodebug --evidence-dir DIR [--demo]` to `serve`."""
    if argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        return ["serve", *argv]
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_legacy_serve_argv(list(sys.argv[1:] if argv is None else argv)))
    if getattr(args, "handler", None) is None:
        parser.print_usage(sys.stderr)
        _err(f"{PROG}: error: choose a command: serve, doctor or config (see `{PROG} --help`)")
        return 2
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as exc:
        _err(f"{PROG}: error: {exc}")
        return 1
