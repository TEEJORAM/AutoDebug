"""Command-line interface.

    autodebug serve   [--evidence-dir DIR] [--demo] [--log-level LEVEL]
    autodebug doctor  [--evidence-dir DIR] [--json]
    autodebug config  {vscode,claude-code,claude-desktop,cursor} [--demo] [--evidence-dir DIR] [--name NAME]
    autodebug guide
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
from autodebug.guide import GUIDE_URL, render_guide
from autodebug.evidence import inside_source_checkout, is_link, is_private_dir, make_private_dir, secure_storage_supported
from autodebug.models import CapabilityState

PROG = "autodebug"
EVIDENCE_ENV = "AUTODEBUG_EVIDENCE_DIR"
CLIENTS = ("vscode", "claude-code", "claude-desktop", "cursor")
MIN_PYTHON = (3, 11)
_WINDOWS = os.name == "nt"

_DESCRIPTION = """\
AutoDebug: a local MCP server that lets an AI client investigate bugs through
your IDE's debugger, behind plan-bound human approval.

Fake-only build: only the synthetic demo debugger is operational; real IDE
debugger control is disabled until the security gate is approved."""

_EPILOG = """\
quick start:
  autodebug doctor                 check this machine
  autodebug guide                  pasteable steps for this OS
  autodebug serve --demo           run the server with the synthetic demo case
  autodebug config vscode --demo --write PROJECT_FOLDER
                                   connect VS Code (writes .vscode/mcp.json)

steps for Windows, macOS and Linux: https://teejoram.github.io/AutoDebug/"""


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
    if is_link(root):
        raise ValueError(f"evidence directory is a link or junction, not a real directory: {root}")
    make_private_dir(root, exist_ok=True)
    if not root.is_dir():
        raise ValueError(f"evidence directory is not a directory: {root}")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = root / f"run-{stamp}-{secrets.token_hex(3)}"
    make_private_dir(run_dir)
    return run_dir


def bridge_folder(root: Path) -> Path:
    """The private folder where AutoDebug Bridge windows announce themselves."""
    from autodebug.bridge.client import bridges_dir

    folder = bridges_dir(root)
    if is_link(folder):
        raise ValueError(f"bridge folder is a link or junction, not a real directory: {folder}")
    make_private_dir(folder, exist_ok=True)
    return folder


# -- serve ------------------------------------------------------------------


def _serve(args: argparse.Namespace) -> int:
    from autodebug.server import PROTOCOL_VERSION, StdioServer, build_dispatcher

    logging.basicConfig(stream=sys.stderr, level=args.log_level.upper(), format=f"{PROG}: %(levelname)s: %(message)s")
    if args.demo and not secure_storage_supported():
        raise ValueError(f"--demo needs evidence storage, which is not available on {platform.system()}")
    root = resolve_evidence_dir(args.evidence_dir)
    run_dir = create_run_dir(root)
    folder = None if args.demo else bridge_folder(root)
    dispatcher = build_dispatcher(run_dir, demo=args.demo, bridges_folder=folder)
    if args.demo:
        _err(f"{PROG} {__version__} | MCP stdio {PROTOCOL_VERSION} | synthetic demo | case AUTODEBUG-DEMO armed")
    else:
        _err(f"{PROG} {__version__} | MCP stdio {PROTOCOL_VERSION} | AutoDebug Bridge for VS Code and Cursor | "
             "nothing runs until you click Approve in the IDE")
        _err(f"{PROG}: bridges: {folder}")
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
    if is_link(root):
        return Check("fail", "Evidence folder", f"{root} is a link or junction; use a real directory")
    if root.exists():
        if not root.is_dir():
            return Check("fail", "Evidence folder", f"{root} is not a directory")
        if not os.access(root, os.W_OK | os.X_OK):
            return Check("fail", "Evidence folder", f"{root} is not writable")
        if secure_storage_supported() and not is_private_dir(root):
            fix = "delete it and AutoDebug recreates it privately" if os.name == "nt" else f"run: chmod 700 '{root}'"
            return Check("warn", "Evidence folder", f"{root} is not private ({fix})")
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
        else Check("fail", "Evidence storage", f"not available on {system}; cases fail closed"),
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
        print(f"Ready. Guide: {GUIDE_URL}")
        print(f"Next: `{invocation()} config vscode --demo --write PROJECT_FOLDER` to connect VS Code.")
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


_JSON_CLIENTS = {"vscode": "servers", "cursor": "mcpServers", "claude-desktop": "mcpServers"}


def client_entry(client: str, spec: dict) -> dict:
    """The server entry in `client`'s documented JSON format."""
    return spec if client == "claude-desktop" else {"type": "stdio", **spec}


def render_config(client: str, name: str, spec: dict) -> tuple[str, str]:
    """Return `(output, where_to_put_it)` for one client."""
    cmd = invocation()
    if client == "claude-code":
        parts = ["claude", "mcp", "add"]
        for key, value in spec.get("env", {}).items():
            parts += ["--env", f"{key}={value}"]
        parts += ["--transport", "stdio", name, "--", spec["command"], *spec["args"]]
        return _quote(parts), "Run this in your project folder (add `--scope user` for all projects)."
    body = {_JSON_CLIENTS[client]: {name: client_entry(client, spec)}}
    where = {
        "vscode": f"Or let AutoDebug write it: `{cmd} config vscode --demo --write PROJECT_FOLDER`.",
        "cursor": f"Or let AutoDebug write it: `{cmd} config cursor --demo --write PROJECT_FOLDER`.",
        "claude-desktop": f"Or let AutoDebug write it: `{cmd} config claude-desktop --demo --write`, "
                          "then restart Claude Desktop.",
    }[client]
    return json.dumps(body, indent=2), where


def config_path(client: str, project: str) -> Path:
    """Where `config --write` puts `client`'s configuration."""
    if client in ("vscode", "cursor"):
        folder = Path(project or ".").expanduser().absolute()
        if not folder.is_dir():
            raise ValueError(f"project folder not found: {folder}")
        return folder / (".vscode" if client == "vscode" else ".cursor") / "mcp.json"
    if client == "claude-desktop":
        if project:
            raise ValueError("claude-desktop has one global configuration; use --write without a folder")
        system = platform.system()
        if system == "Windows":
            base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        elif system == "Darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            raise ValueError(f"no known Claude Desktop configuration location on {system}")
        return base / "Claude" / "claude_desktop_config.json"
    raise ValueError("Claude Code is configured with `claude mcp add`; run the command printed without --write")


def _read_json(path: Path) -> dict:
    raw = path.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    try:
        data = json.loads(raw.decode(encoding)) if raw.strip() else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is not plain JSON ({exc}); add the entry by hand") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object; add the entry by hand")
    return data


def write_config(path: Path, top_key: str, name: str, entry: dict) -> None:
    """Add or replace `name` under `top_key`, keeping every other setting.
    Writes UTF-8 atomically; an existing UTF-16 or BOM file is converted."""
    data = _read_json(path) if path.exists() else {}
    servers = data.setdefault(top_key, {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path}: '{top_key}' is not a JSON object; add the entry by hand")
    servers[name] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _config(args: argparse.Namespace) -> int:
    spec = server_spec(demo=args.demo, evidence_dir=args.evidence_dir)
    if args.write is not None:
        path = config_path(args.client, args.write)
        write_config(path, _JSON_CLIENTS[args.client], args.name, client_entry(args.client, spec))
        _err(f"{PROG}: wrote {path}")
        next_step = {
            "vscode": "In VS Code: Command Palette > MCP: List Servers > autodebug > Start Server.",
            "cursor": "Open Cursor Settings and enable autodebug under MCP.",
            "claude-desktop": "Quit and restart Claude Desktop.",
        }[args.client]
        _err(f"{PROG}: next: {next_step}")
    else:
        output, where = render_config(args.client, args.name, spec)
        print(output)
        _err(f"\n{PROG}: {where}")
    if not secure_storage_supported():
        _err(f"{PROG}: warning: evidence storage is not available on {platform.system()}; "
             "the server starts but every case fails.")
    return 0


# -- guide ------------------------------------------------------------------


def _guide(_args: argparse.Namespace) -> int:
    print(render_guide(platform.system(), invocation()))
    return 0


# -- entry point --------------------------------------------------------------


def invocation() -> str:
    """How the user ran AutoDebug, so printed hints can be pasted as-is."""
    if os.path.basename(sys.argv[0]) == "__main__.py":
        return "py -m autodebug" if _WINDOWS else "python3 -m autodebug"
    return PROG


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

    guide = sub.add_parser("guide", help="print setup steps for this operating system",
                           description="Print pasteable setup steps and the GitHub Pages guide URL. Creates nothing.")
    guide.set_defaults(handler=_guide)

    config = sub.add_parser("config", help="print or write MCP client configuration",
                            description="Print a ready-to-use configuration entry for an MCP client, "
                                        "or write it into the client's configuration file with --write.")
    config.add_argument("client", choices=CLIENTS)
    config.add_argument("--demo", action="store_true", help="configure the server to start the synthetic demo")
    _add_evidence_option(config)
    config.add_argument("--name", default="autodebug", help="server name shown in the client (default: autodebug)")
    config.add_argument("--write", nargs="?", const="", metavar="PROJECT_FOLDER",
                        help="write the entry into the client's config file, keeping other servers "
                             "(vscode/cursor: PROJECT_FOLDER, default current folder; claude-desktop: no folder)")
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
        _err(f"{PROG}: error: choose a command: serve, doctor, config or guide (see `{PROG} --help`)")
        return 2
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as exc:
        _err(f"{PROG}: error: {exc}")
        return 1
