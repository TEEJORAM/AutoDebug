"""Find AutoDebug extension windows and talk to them (docs/design.md, "Extension protocol")."""

from __future__ import annotations

import json
import os
import re
import socket
import stat
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

PROTOCOL = 4
HOST = "127.0.0.1"
MAX_LINE = 1024 * 1024


class DebugError(Exception):
    """An error the agent should see: a code from docs/design.md and a message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def state_folder() -> Path:
    """Per-user folder shared with the extension (`AUTODEBUG_HOME` overrides)."""
    if os.environ.get("AUTODEBUG_HOME"):
        return Path(os.environ["AUTODEBUG_HOME"])
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "autodebug"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "autodebug"
    return Path(os.environ.get("XDG_STATE_HOME") or home / ".local" / "state") / "autodebug"


def bridges_folder() -> Path:
    return state_folder() / "bridges"


@dataclass(frozen=True)
class Window:
    """One IDE window running the extension. The token stays in this process."""

    window: str
    ide: str
    folders: tuple[str, ...]
    port: int
    token: str
    version: str
    protocol: int = PROTOCOL

    @property
    def current(self) -> bool:
        """Whether this window's extension speaks this server's protocol."""
        return self.protocol == PROTOCOL

    def __repr__(self) -> str:
        return f"Window({self.window!r}, {self.ide}, {list(self.folders)})"


def _private(path: Path) -> bool:
    if os.name == "nt":
        return True  # %LOCALAPPDATA% is already per-user.
    info = path.stat()
    return info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077


def discover(folder: Path | None = None) -> list[Window]:
    """Every window whose connection file is valid, private and still reachable, including windows
    whose extension speaks another protocol version (`Window.current` is False for those)."""
    folder = folder or bridges_folder()
    windows = []
    for path in sorted(Path(folder).glob("*.json")) if Path(folder).is_dir() else ():
        try:
            if path.is_symlink() or path.stat().st_size > 65536 or not _private(path):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            window = Window(str(data["window"]), str(data["ide"]), tuple(map(str, data["folders"])),
                            int(data["port"]), str(data["token"]), str(data.get("version", "")), int(data["protocol"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", window.token):
            continue
        if _reachable(window.port):
            windows.append(window)
    return windows


def _reachable(port: int) -> bool:
    try:
        socket.create_connection((HOST, port), timeout=0.5).close()
        return True
    except OSError:
        return False


def same_folder(a: str, b: str) -> bool:
    def norm(p: str) -> str:
        p = os.path.normpath(p.rstrip("/\\") or p)
        return p.lower() if sys.platform == "win32" or re.match(r"[A-Za-z]:", p) else p
    return norm(a) == norm(b)


IDE_NAMES = {"cursor": "Cursor", "vscode": "VS Code", "visualstudio": "Visual Studio"}


def outdated_extension(window: Window) -> str | None:
    """Visual Studio's extension ships with each AutoDebug version (its version is AutoDebug's). An older one
    speaks the same protocol but lacks newer features (screenshots, the debug window layout), so say so."""
    if window.ide != "visualstudio" or not window.version:
        return None
    from autodebug import __version__
    from autodebug.install import is_newer

    try:
        older = is_newer(__version__, window.version)
    except ValueError:
        return None
    if not older:
        return None
    return (f"Visual Studio's AutoDebug extension is {window.version}, older than AutoDebug {__version__}: "
            "screenshots, the debug window layout (Locals or Autos, Call Stack) and the newer debugging tools "
            "(.NET, exception filters, registers, watchpoints, console output) need the new one. Ask the "
            "developer to close every Visual Studio window and run `autodebug setup` (Windows: "
            "`py -m autodebug setup`), then open the solution again.")


def version_problem(window: Window) -> DebugError:
    """Why a window whose extension speaks another protocol cannot be used, and how to fix it."""
    from autodebug import __version__

    ide = IDE_NAMES.get(window.ide, window.ide)
    found = (f"The {ide} window with {', '.join(window.folders)} open is running AutoDebug extension "
             f"{window.version or '(unknown version)'} (protocol {window.protocol}); this server is {__version__} "
             f"(protocol {PROTOCOL}).")
    if window.protocol < PROTOCOL and window.ide == "visualstudio":
        fix = " Ask the developer to run `autodebug setup visualstudio`, then restart Visual Studio."
    elif window.protocol < PROTOCOL:
        fix = (f" Ask the developer to run `autodebug setup {window.ide}`, then in that window run Developer: Reload "
               f"Window, or quit and reopen {ide}. Restarting only the extension host keeps the old extension.")
    else:
        fix = " Ask the developer to update the server: `git pull`, then `python -m pip install -e .` in the AutoDebug folder."
    return DebugError("OLD_EXTENSION", found + fix)


def preferences_file() -> Path:
    return state_folder() / "preferences.json"


def preferred_ide() -> str | None:
    """The IDE the developer debugs in when several are open (`autodebug setup --debug-in`), or None."""
    try:
        value = json.loads(preferences_file().read_text(encoding="utf-8")).get("debug_in")
    except (OSError, ValueError, AttributeError):
        return None
    return value if value in IDE_NAMES else None


def set_preferred_ide(ide: str | None) -> Path:
    path = preferences_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    if ide:
        data["debug_in"] = ide
    else:
        data.pop("debug_in", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def matching(windows: list[Window], folder: str | None, ide: str | None = None) -> list[Window]:
    """Current windows of `ide` (if given) with `folder` open (if given)."""
    return [w for w in windows if w.current and (not ide or w.ide == ide)
            and (not folder or any(same_folder(f, folder) for f in w.folders))]


def choose(windows: list[Window], folder: str | None, ide: str | None = None) -> Window:
    """The window to debug in: of `ide` if given, with `folder` open if given, else the only one."""
    if ide:
        windows = [w for w in windows if w.ide == ide]

    def with_folder(found: list[Window]) -> list[Window]:
        return [w for w in found if any(same_folder(f, folder) for f in w.folders)] if folder else found

    matches = with_folder([w for w in windows if w.current])
    if not matches:
        stale = with_folder([w for w in windows if not w.current])
        if stale:
            raise version_problem(stale[0])
        where = f" with {folder} open" if folder else ""
        which = IDE_NAMES.get(ide, ide) if ide else "VS Code, Cursor or Visual Studio"
        raise DebugError("NO_WINDOW", f"no {which} window{where} is running the AutoDebug extension. Call open_ide "
                                      "with the solution or project folder: it opens the IDE once and waits for it. "
                                      "Do not start the IDE yourself. If the IDE is open, run `autodebug setup` "
                                      "(the extension may be missing).")
    if len(matches) > 1:
        listed = "; ".join(f"{w.ide}: {', '.join(w.folders)}" for w in matches)
        raise DebugError("AMBIGUOUS_WINDOW", f"several windows match ({listed}); pass ide and/or workspace_folder")
    return matches[0]


class Connection:
    """An authenticated connection to one window. Requests are serialized."""

    def __init__(self, window: Window, timeout: float = 5.0) -> None:
        self.window = window
        self._lock = threading.Lock()
        self._next = 1
        try:
            self._sock = socket.create_connection((HOST, window.port), timeout=timeout)
        except OSError as exc:
            raise DebugError("NO_WINDOW", f"cannot reach the {window.ide} window; is it still open?") from exc
        self._reader = self._sock.makefile("rb")
        try:
            self._send({"hello": window.token})
            reply = self._receive(timeout)
        except DebugError:
            self.close()
            raise
        if reply.get("hello") != "ok" or reply.get("window") != window.window:
            self.close()
            raise DebugError("NO_WINDOW", "the IDE window refused the connection")

    def _send(self, message: dict) -> None:
        try:
            self._sock.sendall(json.dumps(message).encode("utf-8") + b"\n")
        except OSError as exc:
            raise DebugError("NO_WINDOW", "lost the connection to the IDE window") from exc

    def _receive(self, timeout: float) -> dict:
        self._sock.settimeout(timeout)
        try:
            line = self._reader.readline(MAX_LINE + 1)
        except socket.timeout as exc:
            raise DebugError("IDE_ERROR", "the IDE did not answer in time") from exc
        except OSError as exc:
            raise DebugError("NO_WINDOW", "lost the connection to the IDE window") from exc
        if not line.endswith(b"\n"):
            raise DebugError("NO_WINDOW", "the IDE window closed the connection")
        try:
            message = json.loads(line)
        except ValueError as exc:
            raise DebugError("IDE_ERROR", "the IDE sent an unreadable reply") from exc
        if not isinstance(message, dict):
            raise DebugError("IDE_ERROR", "the IDE sent an unexpected reply")
        return message

    def call(self, op: str, args: dict | None = None, timeout: float = 10.0) -> dict:
        with self._lock:
            request = self._next
            self._next += 1
            self._send({"id": request, "op": op, "args": args or {}})
            reply = self._receive(timeout)
        if reply.get("id") != request:
            self.close()
            raise DebugError("IDE_ERROR", "the IDE sent a reply to another request")
        if reply.get("ok"):
            result = reply.get("result")
            return result if isinstance(result, dict) else {}
        error = reply.get("error") if isinstance(reply.get("error"), dict) else {}
        raise DebugError(str(error.get("code", "IDE_ERROR")), str(error.get("message", "the IDE refused"))[:2000])

    def close(self) -> None:
        for closer in (self._reader.close, self._sock.close):
            try:
                closer()
            except OSError:
                pass
