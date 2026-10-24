"""Windows file primitives for `EvidenceStore` (standard library `ctypes`).

The Windows counterpart of the POSIX descriptor-relative, no-follow scheme
(see openspec/changes/windows-evidence-storage/design.md):

- Every path is opened with `FILE_FLAG_OPEN_REPARSE_POINT`, so a symlink or
  junction is opened as itself and then rejected.
- A directory is pinned by holding a handle without `FILE_SHARE_DELETE`; it
  cannot be renamed or replaced while held. Its identity is the volume serial
  number plus the file index.
- A file is accepted only if `GetFinalPathNameByHandleW` places it directly in
  the pinned directory under the expected name.
- Snapshots are written to a `CREATE_NEW` temporary file and renamed in place
  by handle.
- Directories are created with a protected DACL for the current user, SYSTEM
  and Administrators.

Importing this module is safe on any platform; `AVAILABLE` says whether the
Windows APIs could be loaded.
"""

from __future__ import annotations

import ctypes
import io
import ntpath
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_READ_DATA = FILE_LIST_DIRECTORY = 0x0001
FILE_WRITE_DATA = FILE_ADD_FILE = 0x0002
FILE_APPEND_DATA = FILE_ADD_SUBDIRECTORY = 0x0004
FILE_TRAVERSE = 0x0020
FILE_READ_ATTRIBUTES = 0x0080
DELETE = 0x00010000
READ_CONTROL = 0x00020000
SYNCHRONIZE = 0x00100000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
CREATE_NEW = 1
OPEN_EXISTING = 3
OPEN_ALWAYS = 4
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_ALREADY_EXISTS = 183
FILE_DISPOSITION_INFO_CLASS = 4
FILE_RENAME_INFORMATION_CLASS = 10
SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x1
DACL_SECURITY_INFORMATION = 0x4
TOKEN_QUERY = 0x8
TOKEN_USER_CLASS = 1
TOKEN_OWNER_CLASS = 4
INHERIT_ONLY_ACE = 0x08
SDDL_REVISION_1 = 1
SID_SYSTEM = "S-1-5-18"
SID_ADMINISTRATORS = "S-1-5-32-544"

_DIRECTORY_ACCESS = FILE_LIST_DIRECTORY | FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY | FILE_TRAVERSE | \
    FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE


class _Api:
    """Lazily bound Windows functions with explicit signatures."""

    def __init__(self) -> None:
        from ctypes import wintypes as w

        self.w = w
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        nt = ctypes.WinDLL("ntdll")
        vp = ctypes.c_void_p

        def bind(dll, name, restype, *argtypes):
            function = getattr(dll, name)
            function.restype, function.argtypes = restype, list(argtypes)
            setattr(self, name, function)

        bind(k32, "CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD, vp, w.DWORD, w.DWORD, w.HANDLE)
        bind(k32, "CloseHandle", w.BOOL, w.HANDLE)
        bind(k32, "GetFileInformationByHandle", w.BOOL, w.HANDLE, ctypes.POINTER(_FileInfo))
        bind(k32, "GetFinalPathNameByHandleW", w.DWORD, w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD)
        bind(k32, "ReadFile", w.BOOL, w.HANDLE, vp, w.DWORD, ctypes.POINTER(w.DWORD), vp)
        bind(k32, "WriteFile", w.BOOL, w.HANDLE, ctypes.c_char_p, w.DWORD, ctypes.POINTER(w.DWORD), vp)
        bind(k32, "SetFileInformationByHandle", w.BOOL, w.HANDLE, ctypes.c_int, vp, w.DWORD)
        bind(k32, "CreateDirectoryW", w.BOOL, w.LPCWSTR, vp)
        bind(k32, "GetCurrentProcess", w.HANDLE)
        bind(k32, "LocalFree", vp, vp)
        bind(adv, "OpenProcessToken", w.BOOL, w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE))
        bind(adv, "GetTokenInformation", w.BOOL, w.HANDLE, ctypes.c_int, vp, w.DWORD, ctypes.POINTER(w.DWORD))
        bind(adv, "ConvertSidToStringSidW", w.BOOL, vp, ctypes.POINTER(w.LPWSTR))
        bind(adv, "ConvertStringSidToSidW", w.BOOL, w.LPCWSTR, ctypes.POINTER(vp))
        bind(adv, "ConvertStringSecurityDescriptorToSecurityDescriptorW", w.BOOL,
             w.LPCWSTR, w.DWORD, ctypes.POINTER(vp), ctypes.POINTER(w.ULONG))
        bind(adv, "GetSecurityInfo", w.DWORD, w.HANDLE, ctypes.c_int, w.DWORD,
             ctypes.POINTER(vp), ctypes.POINTER(vp), ctypes.POINTER(vp), ctypes.POINTER(vp), ctypes.POINTER(vp))
        bind(adv, "GetAce", w.BOOL, vp, w.DWORD, ctypes.POINTER(vp))
        bind(adv, "EqualSid", w.BOOL, vp, vp)
        bind(nt, "NtSetInformationFile", ctypes.c_long, w.HANDLE, ctypes.POINTER(_IoStatusBlock), vp, w.ULONG, ctypes.c_int)
        bind(nt, "RtlNtStatusToDosError", w.ULONG, ctypes.c_long)
        self.invalid_handle = ctypes.c_void_p(-1).value


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _FileInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32), ("created", _FileTime), ("accessed", _FileTime), ("written", _FileTime),
        ("volume_serial", ctypes.c_uint32), ("size_high", ctypes.c_uint32), ("size_low", ctypes.c_uint32),
        ("links", ctypes.c_uint32), ("index_high", ctypes.c_uint32), ("index_low", ctypes.c_uint32),
    ]


class _IoStatusBlock(ctypes.Structure):
    _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_void_p)]


class _Acl(ctypes.Structure):
    _fields_ = [("revision", ctypes.c_ubyte), ("sbz1", ctypes.c_ubyte), ("size", ctypes.c_ushort),
                ("count", ctypes.c_ushort), ("sbz2", ctypes.c_ushort)]


class _AceHeader(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("size", ctypes.c_ushort)]


try:
    _API: _Api | None = _Api() if os.name == "nt" else None
except (AttributeError, OSError):
    _API = None
AVAILABLE = _API is not None


def _api() -> _Api:
    if _API is None:
        raise OSError("Windows file APIs are unavailable")
    return _API


def _error() -> OSError:
    return ctypes.WinError(ctypes.get_last_error())


# -- handles -----------------------------------------------------------------


def _create(path: str, access: int, disposition: int, *, directory: bool = False, share: int = FILE_SHARE_READ) -> int:
    api = _api()
    flags = FILE_FLAG_OPEN_REPARSE_POINT | (FILE_FLAG_BACKUP_SEMANTICS if directory else FILE_ATTRIBUTE_NORMAL)
    handle = api.CreateFileW(path, access, share, None, disposition, flags, None)
    if handle is None or handle == api.invalid_handle:
        raise _error()
    return handle


def _close(handle: int) -> None:
    _api().CloseHandle(handle)


def _info(handle: int) -> _FileInfo:
    info = _FileInfo()
    if not _api().GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise _error()
    return info


def _identity(info: _FileInfo) -> tuple[int, int]:
    return info.volume_serial, (info.index_high << 32) | info.index_low


def _final_path(handle: int) -> str:
    api = _api()
    size = 512
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = api.GetFinalPathNameByHandleW(handle, buffer, size, 0)
        if length == 0:
            raise _error()
        if length < size:
            return buffer.value
        size = length + 1


def _same_path(left: str, right: str) -> bool:
    return ntpath.normcase(left) == ntpath.normcase(right)


def _open_directory(path: str) -> int:
    """Open and pin a real directory (no link, no junction)."""
    handle = _create(path, _DIRECTORY_ACCESS, OPEN_EXISTING, directory=True, share=FILE_SHARE_READ | FILE_SHARE_WRITE)
    try:
        attributes = _info(handle).attributes
        if attributes & FILE_ATTRIBUTE_REPARSE_POINT or not attributes & FILE_ATTRIBUTE_DIRECTORY:
            raise ValueError("evidence directory must be a real directory, not a link or junction")
    except BaseException:
        _close(handle)
        raise
    return handle


def _check_child(handle: int, directory_path: str, name: str, *, directory: bool) -> _FileInfo:
    """Require `handle` to be `name` directly inside `directory_path`."""
    info = _info(handle)
    if info.attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("evidence path is a link or junction")
    if bool(info.attributes & FILE_ATTRIBUTE_DIRECTORY) != directory:
        raise ValueError("evidence path has the wrong type")
    if not directory and info.links != 1:
        raise ValueError("evidence artifact must be a regular file with a single link")
    final = _final_path(handle)
    if not (_same_path(ntpath.dirname(final), directory_path) and _same_path(ntpath.basename(final), name)):
        raise ValueError("evidence path resolved outside its case directory")
    return info


def _delete_by_handle(handle: int) -> None:
    flag = ctypes.c_ubyte(1)
    _api().SetFileInformationByHandle(handle, FILE_DISPOSITION_INFO_CLASS, ctypes.byref(flag), ctypes.sizeof(flag))


def _rename_in_place(handle: int, name: str) -> None:
    """Rename the open file within its own directory, replacing `name`."""
    api = _api()
    encoded = name.encode("utf-16-le")

    class _RenameInformation(ctypes.Structure):
        _fields_ = [("replace_if_exists", ctypes.c_ulong), ("root_directory", ctypes.c_void_p),
                    ("name_length", ctypes.c_ulong), ("name", ctypes.c_wchar * len(name))]

    info = _RenameInformation(1, None, len(encoded), name)
    status_block = _IoStatusBlock()
    status = api.NtSetInformationFile(handle, ctypes.byref(status_block), ctypes.byref(info),
                                      ctypes.sizeof(info), FILE_RENAME_INFORMATION_CLASS)
    if status < 0:
        raise ctypes.WinError(api.RtlNtStatusToDosError(status))


class _HandleIO(io.RawIOBase):
    """Unbuffered binary I/O over a Windows handle the caller still owns."""

    def __init__(self, handle: int, *, writable: bool) -> None:
        super().__init__()
        self._handle, self._writable = handle, writable

    def readable(self) -> bool:
        return not self._writable

    def writable(self) -> bool:
        return self._writable

    def readinto(self, buffer) -> int:
        view = memoryview(buffer).cast("B")
        if not len(view):
            return 0
        target = (ctypes.c_char * len(view)).from_buffer(view)
        count = _api().w.DWORD()
        if not _api().ReadFile(self._handle, ctypes.addressof(target), len(view), ctypes.byref(count), None):
            raise _error()
        return count.value

    def write(self, data) -> int:
        payload = bytes(data)
        count = _api().w.DWORD()
        if not _api().WriteFile(self._handle, payload, len(payload), ctypes.byref(count), None):
            raise _error()
        return count.value


# -- security ----------------------------------------------------------------


class _Sids:
    """Current user, token default owner, SYSTEM and Administrators SIDs."""

    def __init__(self) -> None:
        api = _api()
        token = api.w.HANDLE()
        if not api.OpenProcessToken(api.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
            raise _error()
        try:
            self._user_buffer = self._token_info(token, TOKEN_USER_CLASS)
            self._owner_buffer = self._token_info(token, TOKEN_OWNER_CLASS)
        finally:
            _close(token)
        self.user = ctypes.c_void_p.from_buffer(self._user_buffer).value
        self.token_owner = ctypes.c_void_p.from_buffer(self._owner_buffer).value
        self.system = self._well_known(SID_SYSTEM)
        self.administrators = self._well_known(SID_ADMINISTRATORS)
        text = api.w.LPWSTR()
        if not api.ConvertSidToStringSidW(self.user, ctypes.byref(text)):
            raise _error()
        try:
            self.user_string = text.value
        finally:
            api.LocalFree(ctypes.cast(text, ctypes.c_void_p))

    @staticmethod
    def _token_info(token, info_class: int) -> ctypes.Array:
        api = _api()
        needed = api.w.DWORD()
        api.GetTokenInformation(token, info_class, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        if not api.GetTokenInformation(token, info_class, buffer, needed, ctypes.byref(needed)):
            raise _error()
        return buffer

    @staticmethod
    def _well_known(text: str) -> int:
        sid = ctypes.c_void_p()
        if not _api().ConvertStringSidToSidW(text, ctypes.byref(sid)):
            raise _error()
        return sid.value  # intentionally kept for the process lifetime


_SIDS: _Sids | None = None


def _sids() -> _Sids:
    global _SIDS
    if _SIDS is None:
        _SIDS = _Sids()
    return _SIDS


def _is_private_handle(handle: int) -> bool:
    """Owner is this user (or the token's default owner) and every effective
    allow-ACE grants only the user, SYSTEM or Administrators."""
    api, sids = _api(), _sids()
    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    status = api.GetSecurityInfo(handle, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                                 ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if status:
        raise ctypes.WinError(status)
    try:
        if not any(api.EqualSid(owner, sid) for sid in (sids.user, sids.token_owner)):
            return False
        if not dacl.value:  # a NULL DACL grants everyone full access
            return False
        trusted = (sids.user, sids.token_owner, sids.system, sids.administrators)
        for index in range(_Acl.from_address(dacl.value).count):
            ace = ctypes.c_void_p()
            if not api.GetAce(dacl, index, ctypes.byref(ace)):
                raise _error()
            header = _AceHeader.from_address(ace.value)
            if header.flags & INHERIT_ONLY_ACE:
                continue
            if header.type in (0, 9):  # ACCESS_ALLOWED(_CALLBACK): SID follows header and mask
                if not any(api.EqualSid(ace.value + 8, sid) for sid in trusted):
                    return False
            elif header.type in (4, 5, 11):  # compound/object allow ACEs: not expected, refuse
                return False
        return True
    finally:
        api.LocalFree(descriptor)


def _create_directory(path: str) -> None:
    """Create one directory with a protected, owner-only DACL."""
    api, sids = _api(), _sids()
    user = sids.user_string
    sddl = f"O:{user}D:P(A;OICI;FA;;;{user})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    descriptor = ctypes.c_void_p()
    if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, SDDL_REVISION_1, ctypes.byref(descriptor), None):
        raise _error()
    try:
        class _SecurityAttributes(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("descriptor", ctypes.c_void_p), ("inherit", ctypes.c_int)]

        attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, 0)
        if not api.CreateDirectoryW(path, ctypes.byref(attributes)):
            raise _error()
    finally:
        api.LocalFree(descriptor)


# -- public operations ---------------------------------------------------------


def create_private_directory(path: str, *, exist_ok: bool = False) -> None:
    """Create `path` (its parent must exist) with an owner-only DACL. With
    `exist_ok`, an existing real directory is accepted as it is."""
    try:
        _create_directory(path)
    except FileExistsError:
        if not exist_ok:
            raise
        _close(_open_directory(path))


def is_private_directory(path: str) -> bool:
    """Whether the real directory at `path` is private to this user."""
    handle = _open_directory(path)
    try:
        return _is_private_handle(handle)
    finally:
        _close(handle)


def create_case_directory(base: str, case_id: str) -> tuple[int, int]:
    """Exclusively create `base\\case_id` inside the private, pinned base and
    return the new directory's identity."""
    base_handle = _open_directory(base)
    try:
        if not _is_private_handle(base_handle):
            raise PermissionError("evidence base must be owned by the current user and private")
        base_path = _final_path(base_handle)
        case_path = ntpath.join(base_path, case_id)
        try:
            _create_directory(case_path)
        except FileExistsError as exc:
            raise ValueError("case directory already exists; use a fresh case_id") from exc
        case_handle = _open_directory(case_path)
        try:
            return _identity(_check_child(case_handle, base_path, case_id, directory=True))
        finally:
            _close(case_handle)
    finally:
        _close(base_handle)


@contextmanager
def open_artifact(case_dir: str, name: str, mode: str, identity: tuple[int, int]) -> Iterator[TextIO]:
    """Open `name` inside the pinned case directory as UTF-8 text.

    `r` reads, `a` appends (creating if needed), `w` writes a new snapshot that
    atomically replaces any previous one. Links, junctions, hardlinks, a
    replaced case directory and any path resolving elsewhere are refused.
    """
    try:
        directory = _open_directory(case_dir)
    except FileNotFoundError as exc:
        raise ValueError("evidence case directory disappeared") from exc
    try:
        if _identity(_info(directory)) != identity:
            raise ValueError("evidence case directory identity changed")
        directory_path = _final_path(directory)
        target = ntpath.join(directory_path, name)
        if mode == "r":
            yield from _read(target, directory_path, name)
        elif mode == "a":
            yield from _append(target, directory_path, name)
        elif mode == "w":
            yield from _write(directory_path, name)
        else:
            raise ValueError(f"unsupported evidence file mode {mode!r}")
    finally:
        _close(directory)


def _read(target: str, directory_path: str, name: str) -> Iterator[TextIO]:
    handle = _create(target, GENERIC_READ | FILE_READ_ATTRIBUTES, OPEN_EXISTING)
    try:
        _check_child(handle, directory_path, name, directory=False)
        with io.TextIOWrapper(io.BufferedReader(_HandleIO(handle, writable=False)), encoding="utf-8") as stream:
            yield stream
    finally:
        _close(handle)


def _append(target: str, directory_path: str, name: str) -> Iterator[TextIO]:
    access = FILE_APPEND_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE | DELETE
    handle = _create(target, access, OPEN_ALWAYS)
    created = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
    try:
        try:
            _check_child(handle, directory_path, name, directory=False)
        except BaseException:
            if created:
                _delete_by_handle(handle)
            raise
        stream = io.TextIOWrapper(io.BufferedWriter(_HandleIO(handle, writable=True)), encoding="utf-8", newline="\n")
        try:
            yield stream
        finally:
            stream.flush()
            stream.detach()
    finally:
        _close(handle)


def _write(directory_path: str, name: str) -> Iterator[TextIO]:
    target = ntpath.join(directory_path, name)
    try:
        existing = _create(target, FILE_READ_ATTRIBUTES, OPEN_EXISTING, share=FILE_SHARE_READ | FILE_SHARE_WRITE)
    except FileNotFoundError:
        pass
    else:
        try:
            _check_child(existing, directory_path, name, directory=False)
        finally:
            _close(existing)
    temporary = f".{name}.{uuid.uuid4().hex}.tmp"
    handle = _create(ntpath.join(directory_path, temporary),
                     GENERIC_WRITE | DELETE | FILE_READ_ATTRIBUTES | SYNCHRONIZE, CREATE_NEW, share=0)
    keep = False
    try:
        _check_child(handle, directory_path, temporary, directory=False)
        stream = io.TextIOWrapper(io.BufferedWriter(_HandleIO(handle, writable=True)), encoding="utf-8", newline="\n")
        try:
            yield stream
            stream.flush()
        finally:
            stream.detach()
        _rename_in_place(handle, name)
        keep = True
    finally:
        if not keep:
            _delete_by_handle(handle)
        _close(handle)
