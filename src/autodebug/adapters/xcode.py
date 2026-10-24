"""Xcode adapter (T11) — GW-06, IDE-02, IDE-04.

**Tested and implemented independently from VS Code, Cursor, and CLion —
Apple's `xcrun mcpbridge` facility is never assumed to match any other
IDE's MCP tool inventory or capability set** (`docs/ide-integrations.md`
section E: *"Do not claim all Xcode versions expose the debugger tools;
enumerate advertised MCP tools and probe a disposable example project.
LLDB outside Xcode is not the same thing as controlling Xcode's active
native debug session."*). `XcodeAdapter` reuses the exact same `BaseAdapter`
contract `VSCodeAdapter` (T08), `CursorAdapter` (T09), and `CLionAdapter`
(T10) implement, but depends on its own, separately-named `XcodeDebugClient`
injected abstraction — not any of the other three — so nothing here implies
Xcode shares a remote protocol, tool inventory, or capability set with any
other adapter. `RemoteSessionInfo` (the generic remote-session shape) is
shared from `adapters.base`, since it is AutoDebug's own adapter-agnostic
abstraction, not a borrowed concept from any other adapter.

**Environment finding (read-only, no process spawned beyond `xcode-select`/
`xcodebuild -version`/`xcrun -f`, no network contact, this session):**
Xcode **is installed** on this machine — `xcode-select -p` resolves to
`/Applications/Xcode.app/Contents/Developer`, and `xcodebuild -version`
reports `Xcode 26.0.1 (Build 17A400)`. However, `xcrun mcpbridge` **is not
found** — `xcrun -f mcpbridge` fails with "unable to find utility
'mcpbridge', not a developer tool or in PATH," and a recursive filesystem
search of the entire `/Applications/Xcode.app` bundle for `mcpbridge`
returns zero matches. **The Xcode application is present; the specific
`mcpbridge` MCP facility this adapter depends on is not** — closer to T08's
VS Code finding (IDE installed, specific named tool/extension absent) than
T10's CLion finding (the IDE application itself absent). Per `IDE-04-A`
("the installed Xcode MCP bridge exposes no native debugger control ->
PARTIAL or UNSUPPORTED, with a tool-inventory evidence note, not PASS"),
and since the tool is not merely limited but entirely absent, this is
recorded as `UNSUPPORTED`, not `PASS` or `PARTIAL` — see
`docs/compatibility-ledger.md` and `tasks.md` T11 for the full writeup.
**This reflects this Xcode installation/version on this machine only — it
is not a claim that Xcode/`xcrun mcpbridge` can never expose native
debugger control in any version.**

With no client attached (the default), every operation fails closed with
`BACKEND_UNAVAILABLE` (`IDE-03-A`), identical to the other three real
adapters' convention — this is a real implementation reporting "backend
not reachable," not a stub declaring "not implemented."

**Real-backend authorization remains fully gated.** Nothing in this file
touches `approvals.py`. `ApprovalBroker.verify_approval` still
unconditionally refuses any `backend_kind != "fake"`
(`approvals.FAKE_BACKEND_KIND`), so arming a case against this adapter
through the facade's `authorize_and_arm` path still fails regardless of
this implementation — see `tests/test_ide_adapters.py`.
"""

from __future__ import annotations

from typing import Protocol

from autodebug.adapters.base import ClientBackedAdapter, RemoteDebugClient, RemoteSessionInfo

__all__ = ["XcodeAdapter", "XcodeDebugClient", "RemoteSessionInfo"]


class XcodeDebugClient(RemoteDebugClient, Protocol):
    """Operations `XcodeAdapter` needs from an `xcrun mcpbridge` debugger
    session. Deliberately separate from the other adapters' clients;
    `mcpbridge` was not found on the development machine, so its real tools
    are unverified."""


class XcodeAdapter(ClientBackedAdapter):
    ide_id = "xcode"
    supported_os = ("Darwin",)
    proof_task_id = "T11"
    missing_client_message = "no Xcode mcpbridge client is attached; mcpbridge is not connected"
