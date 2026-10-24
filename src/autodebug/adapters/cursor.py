"""Cursor adapter (T09) — GW-06, IDE-03, IDE-04.

**Tested and implemented independently from VS Code — Cursor's extension
host is not assumed to expose the same debugger access DebugMCP gives VS
Code** (`docs/ide-integrations.md` section B: *"Cursor's API for
registering MCP servers is not a guarantee of live-debugger access... do
not assume VS Code compatibility"*). `CursorAdapter` reuses the exact same
`BaseAdapter` contract `VSCodeAdapter` (T08) implements, but depends on its
own, separately-named `CursorDebugClient` injected abstraction — not
`vscode.DebugMCPClient` — so nothing here implies Cursor and VS Code share
a remote protocol, a tool inventory, or a capability set. `RemoteSessionInfo`
(the generic remote-session shape) is shared from `adapters.base`, since it
is AutoDebug's own adapter-agnostic abstraction, not a borrowed VS Code
concept.

**Environment finding (read-only, no process spawned, no network contact,
this session):** `~/.cursor/mcp.json` on this machine reports
`{"mcpServers": {}}` — zero MCP servers are currently registered with
Cursor, and `~/.cursor/extensions` contains no native-debugger-exposing
MCP bridge (only `ms-python.debugpy`, a generic DAP debugger extension
unrelated to Cursor's own native session, same as found for VS Code in
T08). This is stronger, more direct evidence than T08 had: not just "no
known extension installed" but "Cursor itself reports zero registered MCP
servers." Real Cursor-native-debugger validation is therefore not possible
in this environment — see `docs/compatibility-ledger.md` and `tasks.md`
T09 for the full writeup.

With no client attached (the default), every operation fails closed with
`BACKEND_UNAVAILABLE` (`IDE-03-A`), identical to `VSCodeAdapter`'s
convention — this is a real implementation reporting "backend not
reachable," not a stub declaring "not implemented."

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

__all__ = ["CursorAdapter", "CursorDebugClient", "RemoteSessionInfo"]


class CursorDebugClient(RemoteDebugClient, Protocol):
    """Operations `CursorAdapter` needs from a Cursor native-debugger bridge.
    Deliberately separate from `vscode.DebugMCPClient`: no Cursor debugger
    protocol has been verified."""


class CursorAdapter(ClientBackedAdapter):
    ide_id = "cursor"
    supported_os = ("Windows", "Darwin", "Linux")
    proof_task_id = "T09"
    missing_client_message = "no Cursor native-debugger client is attached; no MCP bridge is connected"
