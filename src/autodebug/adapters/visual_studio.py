"""Visual Studio adapter (T12) — GW-06, IDE-02, IDE-03, IDE-04.

**Tested and implemented independently from VS Code, Cursor, CLion, and
Xcode — a Visual Studio integration (an Autodesk-approved internal bridge,
or an independently authored public-API extension) is never assumed to
share any other IDE's MCP tool inventory, capability set, or even
transport mechanism** (`docs/ide-integrations.md` section D: *"Evaluate any
existing internal Autodesk bridge separately with its maintainers'
permission and organizational approvals. For a public/external version,
use a new independently written Visual Studio SDK/EnvDTE adapter; never
package or disclose Autodesk internal code without authorization."*).
`VisualStudioAdapter` reuses the exact same `BaseAdapter` contract the
other four adapters implement, but depends on its own, separately-named
`VisualStudioDebugClient` injected abstraction — not any of the other
four — so nothing here implies Visual Studio shares a remote protocol,
tool inventory, or capability set with any other adapter. `RemoteSessionInfo`
(the generic remote-session shape) is shared from `adapters.base`, since it
is AutoDebug's own adapter-agnostic abstraction, not a borrowed concept.

**Environment finding (read-only, `platform.system()` only, no process
spawned, no network contact, this session):** this development machine
reports `platform.system() == "Darwin"` (macOS), **not Windows**. Visual
Studio (the full IDE, as distinct from VS Code) is Windows-only
(`supported_os = ("Windows",)`, unchanged from T01). **This is a more
fundamental limitation than any of T08–T11's findings: those were all "the
right OS, but a specific tool/IDE/bridge is absent on it"; this is "the
wrong OS entirely — there is no Windows host in this environment to probe
an internal bridge or public-API extension on at all."** This exactly
matches `IDE-05-A`'s own acceptance scenario: *"GIVEN only a Mac test host
is available WHEN compatibility documentation is updated THEN Windows and
Linux test cases remain NOT_TESTED or BLOCKED instead of green
checkmarks."* Per that explicit guidance, this is recorded as `BLOCKED`
(cannot test — no Windows host available), not `UNSUPPORTED` (which would
imply a real probe ran and the backend lacked a capability) — see
`docs/compatibility-ledger.md` and `tasks.md` T12 for the full writeup.
**This reflects the absence of a Windows test host in this specific
environment — it is not a claim that Visual Studio, an internal Autodesk
bridge, or a public-API extension cannot support native debugging.**

With no client attached (the default), every operation fails closed with
`BACKEND_UNAVAILABLE` (`IDE-03-A`), identical to the other four real
adapters' convention — this is a real implementation reporting "backend
not reachable," not a stub declaring "not implemented." `probe()`/
`probe_capabilities()` (inherited unchanged from `BaseAdapter`, T01/T02)
already correctly report `NOT_APPLICABLE` for this adapter on any
non-Windows host, including this one — that existing `IDE-02-A` behavior
is unchanged and re-confirmed, not modified, by this task.

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

__all__ = ["VisualStudioAdapter", "VisualStudioDebugClient", "RemoteSessionInfo"]


class VisualStudioDebugClient(RemoteDebugClient, Protocol):
    """Operations `VisualStudioAdapter` needs from a Visual Studio native-
    debugger bridge/extension. Deliberately separate from the other
    adapters' clients; no bridge has been verified."""


class VisualStudioAdapter(ClientBackedAdapter):
    ide_id = "visual_studio"
    supported_os = ("Windows",)
    proof_task_id = "T12"
    missing_client_message = "no Visual Studio debug client is attached; no bridge/extension is connected"
