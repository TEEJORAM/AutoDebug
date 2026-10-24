"""VS Code adapter (T08) — GW-04, GW-06, IDE-03, IDE-04.

Bridges to a separately installed, Autodesk-approved Microsoft DebugMCP
extension. **`VSCodeAdapter` never speaks DebugMCP's wire protocol
directly** — it depends on an injected `DebugMCPClient` (any object
implementing that `Protocol`), and translates between AutoDebug's typed
models (`TargetRef`, `Breakpoint`, `SessionRef`, `BreakpointBindingResult`)
and whatever that client returns. This split exists because DebugMCP's
*exact* remote tool/schema names are still unverified — see
`docs/vscode-debugmcp-mapping.md`, which marks every one
`UNKNOWN — CONFIRM AT RUNTIME` — and `CLAUDE.md` forbids fabricating IDE
APIs. `DebugMCPClient` is AutoDebug's own abstraction (constructor-injected,
per `CLAUDE.md`'s dependency-injection convention), not a transcription of
DebugMCP's actual protocol; a real client implementing it, built against
the real extension once installed and Autodesk-approved, is a separate,
future, dependency-approval-gated piece of work. Nothing here installs
DebugMCP, any MCP SDK, or contacts a real debugger.

With no client attached (the default), every operation fails closed with
`BACKEND_UNAVAILABLE` — matching `IDE-03-A`'s "bridge is absent ->
UNAVAILABLE, not an automatic download or code copy" — rather than a bare
`NotImplementedError`.

**Real-backend authorization remains fully gated.** Nothing in this file
touches `approvals.py`. `ApprovalBroker.verify_approval` still
unconditionally refuses any `backend_kind != "fake"`
(`approvals.FAKE_BACKEND_KIND`), so arming a case against this adapter
through the facade's `authorize_and_arm` path still fails with
`TARGET_MISMATCH`/`PERMISSION_DENIED` regardless of this implementation —
see `tests/test_ide_adapters.py` for a regression proving this.
"""

from __future__ import annotations

from typing import Protocol

from autodebug.adapters.base import ClientBackedAdapter, RemoteDebugClient, RemoteSessionInfo

__all__ = ["VSCodeAdapter", "DebugMCPClient", "RemoteSessionInfo"]


class DebugMCPClient(RemoteDebugClient, Protocol):
    """Operations `VSCodeAdapter` needs from a connected DebugMCP session.
    Method names here are not DebugMCP's real remote tool/schema names,
    which remain unverified (`docs/vscode-debugmcp-mapping.md`)."""


class VSCodeAdapter(ClientBackedAdapter):
    ide_id = "vscode"
    supported_os = ("Windows", "Darwin", "Linux")
    proof_task_id = "T08"
    missing_client_message = "no DebugMCP client is attached; the extension is not connected"
