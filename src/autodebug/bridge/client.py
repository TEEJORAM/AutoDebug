"""Find and talk to a running AutoDebug Bridge (BR-01, BR-02).

Each IDE window with the extension writes a connection file into the private
`bridges` folder next to the evidence base. AutoDebug trusts a file only if the
folder is private to the user, the file is not a link, and every field is well
formed; it connects only to 127.0.0.1.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import socket
import stat
import threading
from dataclasses import dataclass
from pathlib import Path

from autodebug.bridge.protocol import LOOPBACK, MAX_MESSAGE_BYTES, PROTOCOL_VERSION, ProtocolError, decode, encode
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.evidence import is_link, is_private_dir

BRIDGES_FOLDER = "bridges"
BRIDGE_IDES = ("vscode", "cursor")
_MAX_FILE_BYTES = 64 * 1024
_TOKEN = re.compile(r"[0-9a-f]{64}")
_WINDOW_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def bridges_dir(evidence_base: Path) -> Path:
    return Path(evidence_base) / BRIDGES_FOLDER


def _unavailable(message: str) -> AutoDebugError:
    return AutoDebugError(ErrorDetail(code=ErrorCode.BACKEND_UNAVAILABLE, message=message, recoverable=True))


@dataclass(frozen=True)
class ConnectionInfo:
    """One bridge's connection file. `token` never leaves this process."""

    window_id: str
    ide: str
    port: int
    token: str
    workspace_folders: tuple[str, ...]
    extension_version: str

    def __repr__(self) -> str:  # keep the token out of logs and tracebacks
        return f"ConnectionInfo(window_id={self.window_id!r}, ide={self.ide!r}, port={self.port})"


def _parse(data: dict) -> ConnectionInfo:
    folders = data.get("workspace_folders")
    info = ConnectionInfo(
        window_id=data.get("window_id"), ide=data.get("ide"), port=data.get("port"), token=data.get("token"),
        workspace_folders=tuple(folders) if type(folders) is list else (),
        extension_version=data.get("extension_version"),
    )
    if (
        data.get("protocol") != PROTOCOL_VERSION or data.get("host") != LOOPBACK
        or type(info.window_id) is not str or not _WINDOW_ID.fullmatch(info.window_id)
        or info.ide not in BRIDGE_IDES
        or type(info.port) is not int or not 1 <= info.port <= 65535
        or type(info.token) is not str or not _TOKEN.fullmatch(info.token)
        or not info.workspace_folders or len(info.workspace_folders) > 64
        or any(type(f) is not str or not f or len(f) > 2000 for f in info.workspace_folders)
        or type(info.extension_version) is not str or len(info.extension_version) > 64
    ):
        raise ValueError("malformed connection file")
    return info


def _file_is_private(path: Path) -> bool:
    if os.name == "nt":
        return True  # Covered by the folder's protected DACL.
    info = path.stat()
    return info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077


def discover(folder: Path) -> tuple[ConnectionInfo, ...]:
    """Every valid connection file in `folder`. A folder that exists but is
    not private to this user is refused outright (BR-01-A)."""
    folder = Path(folder)
    if not folder.exists():
        return ()
    if is_link(folder) or not folder.is_dir() or not is_private_dir(folder):
        raise AutoDebugError(ErrorDetail(
            code=ErrorCode.PERMISSION_DENIED,
            message=f"bridge folder {folder} is not private to this user; refusing its connection files",
        ))
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            if is_link(path) or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES or not _file_is_private(path):
                continue
            found.append(_parse(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, AttributeError):
            continue  # Half-written, stale or foreign file: ignore it.
    return tuple(found)


def normalize_folder(path: str) -> str:
    """Compare workspace folders the way the OS does: Windows-style paths
    case-insensitively with one separator style; POSIX paths exactly."""
    path = path.rstrip("/\\") or path
    if re.match(r"[A-Za-z]:", path) or path.startswith("\\\\") or "\\" in path:
        return path.replace("/", "\\").lower()
    return path


def select(infos: tuple[ConnectionInfo, ...], workspace_folder: str, ide: str) -> ConnectionInfo:
    """BR-02 — exactly one bridge must have this workspace open in this IDE."""
    wanted = normalize_folder(workspace_folder)
    matches = [i for i in infos if i.ide == ide and wanted in {normalize_folder(f) for f in i.workspace_folders}]
    if not matches:
        other = sorted({i.ide for i in infos if i.ide != ide and wanted in {normalize_folder(f) for f in i.workspace_folders}})
        if other:
            raise _unavailable(f"{workspace_folder} is open in {other[0]}, not {ide}; create the case with target ide '{other[0]}'")
        raise _unavailable(
            f"no AutoDebug Bridge is running for {workspace_folder} in {ide}; open that folder with the "
            "AutoDebug Bridge extension installed (autodebug bridge install)"
        )
    if len(matches) > 1:
        raise AutoDebugError(ErrorDetail(
            code=ErrorCode.SESSION_AMBIGUOUS,
            message=f"{len(matches)} {ide} windows have {workspace_folder} open; close all but one",
        ))
    return matches[0]


class BridgeConnection:
    """One authenticated connection to one bridge. Requests are serialized."""

    def __init__(self, info: ConnectionInfo, *, connect_timeout: float = 5.0) -> None:
        self.info = info
        self._lock = threading.Lock()
        self._next_id = 1
        try:
            self._sock = socket.create_connection((LOOPBACK, info.port), timeout=connect_timeout)
        except OSError as exc:
            raise _unavailable(f"cannot reach the AutoDebug Bridge in {info.ide} window {info.window_id}") from exc
        self._reader = self._sock.makefile("rb")
        try:
            self._send({"hello": info.token, "protocol": PROTOCOL_VERSION})
            reply = self._receive()
        except AutoDebugError:
            self.close()
            raise
        if reply.get("hello") != "ok" or not hmac.compare_digest(str(reply.get("window_id")), info.window_id):
            self.close()
            raise _unavailable("the AutoDebug Bridge did not accept the connection")

    def _send(self, message: dict) -> None:
        try:
            self._sock.sendall(encode(message))
        except (OSError, ProtocolError) as exc:
            raise _unavailable("lost the connection to the AutoDebug Bridge") from exc

    def _receive(self) -> dict:
        try:
            return decode(self._reader.readline(MAX_MESSAGE_BYTES + 1))
        except socket.timeout as exc:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.TIMEOUT, message="the AutoDebug Bridge did not answer in time")) from exc
        except (OSError, ProtocolError) as exc:
            raise _unavailable("lost the connection to the AutoDebug Bridge") from exc

    def request(self, op: str, args: dict | None = None, *, timeout: float = 5.0) -> dict:
        """Send one operation and return its `result`, or raise the bridge's
        error as an `AutoDebugError`."""
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._sock.settimeout(timeout)
            self._send({"id": request_id, "op": op, "args": args or {}})
            reply = self._receive()
        if reply.get("id") != request_id or type(reply.get("ok")) is not bool:
            self.close()
            raise _unavailable("the AutoDebug Bridge sent an unexpected reply")
        if reply["ok"]:
            result = reply.get("result")
            return result if type(result) is dict else {}
        error = reply.get("error") if type(reply.get("error")) is dict else {}
        try:
            code = ErrorCode(error.get("code"))
        except ValueError:
            code = ErrorCode.BACKEND_UNAVAILABLE
        message = error.get("message") if type(error.get("message")) is str else "bridge operation failed"
        raise AutoDebugError(ErrorDetail(code=code, message=message[:2000], recoverable=code is not ErrorCode.INTERNAL_ERROR))

    def close(self) -> None:
        for closer in (self._reader.close, self._sock.close):
            try:
                closer()
            except OSError:
                pass
