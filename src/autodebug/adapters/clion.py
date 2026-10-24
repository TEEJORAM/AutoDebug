"""CLion adapter (T10) — GW-06, IDE-04.

**Tested and implemented independently from VS Code and Cursor — JetBrains'
built-in MCP server and its advertised debugger tools are never assumed to
match DebugMCP's or any generic IDE-extension's capability set**
(`docs/ide-integrations.md` section C: *"Use JetBrains' supported built-in
MCP server and its advertised debugger tools. Do not hardcode `xdebug_*`
names until runtime discovery confirms them... do not assume a generic DAP
socket exposes CLion's active session."*). `CLionAdapter` reuses the exact
same `BaseAdapter` contract `VSCodeAdapter` (T08) and `CursorAdapter` (T09)
implement, but depends on its own, separately-named `CLionDebugClient`
injected abstraction — not `vscode.DebugMCPClient`, not
`cursor.CursorDebugClient` — so nothing here implies CLion shares a remote
protocol, tool inventory, or capability set with either. `RemoteSessionInfo`
(the generic remote-session shape) is shared from `adapters.base`, since it
is AutoDebug's own adapter-agnostic abstraction, not a borrowed concept
from any other adapter.

**Environment finding (read-only, no process spawned, no network contact,
this session):** a comprehensive local search (`/Applications`,
`~/Applications`, JetBrains Toolbox's apps directory, and a Spotlight
`mdfind` query for `CLion.app`) found **no installed CLion application
anywhere on this machine**, despite three residual JetBrains configuration
directories under `~/Library/Application Support/JetBrains/`
(`CLion2024.2`, `CLion2024.3`, `CLion2025.1`) left over from a prior
install. `bundled_plugins.txt` and the installed-plugins directory inside
the most recent config folder (`CLion2025.1`) contain no MCP-related plugin
— only theme/VCS/Copilot plugins. **CLion itself is not currently
installed, so there is no JetBrains MCP server or debugger tool to
enumerate at all** — a more fundamental absence than T08's VS Code finding
(a specific, named extension missing) or T09's Cursor finding (the IDE
installed, zero MCP servers registered): here the IDE application itself
is absent. Per `tasks.md` T10's own acceptance criterion ("`UNSUPPORTED` if
missing"), this is recorded as `UNSUPPORTED`, not `BLOCKED` — see
`docs/compatibility-ledger.md` and `tasks.md` T10 for the full writeup.

With no client attached (the default), every operation fails closed with
`BACKEND_UNAVAILABLE` (`IDE-03-A`), identical to `VSCodeAdapter`'s and
`CursorAdapter`'s convention — this is a real implementation reporting
"backend not reachable," not a stub declaring "not implemented."

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

__all__ = ["CLionAdapter", "CLionDebugClient", "RemoteSessionInfo"]


class CLionDebugClient(RemoteDebugClient, Protocol):
    """Operations `CLionAdapter` needs from a JetBrains CLion MCP debugger
    connection. Deliberately separate from the other adapters' clients;
    JetBrains' real tool names are unverified."""


class CLionAdapter(ClientBackedAdapter):
    ide_id = "clion"
    supported_os = ("Windows", "Darwin", "Linux")
    proof_task_id = "T10"
    missing_client_message = "no CLion MCP debug client is attached; no JetBrains MCP server is connected"
