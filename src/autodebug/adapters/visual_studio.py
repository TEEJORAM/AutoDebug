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
this implementation — see `tests/test_visual_studio_adapter.py`'s
`TestAuthorizationGateStillBlocksVisualStudio`.
"""

from __future__ import annotations

import itertools
import time
from typing import Protocol

from autodebug.adapters.base import BaseAdapter, RemoteSessionInfo
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import Breakpoint, SessionRef, TargetRef
from autodebug.workflow import BreakpointBindingResult

__all__ = ["VisualStudioAdapter", "VisualStudioDebugClient", "RemoteSessionInfo"]


class VisualStudioDebugClient(Protocol):
    """The minimal operations `VisualStudioAdapter` needs from a connected
    Visual Studio debugger session (via an Autodesk-approved internal
    bridge, or an independently authored public-API/EnvDTE extension).
    This is AutoDebug's own abstraction, deliberately separate from every
    other adapter's client type — Visual Studio's real remote tool/schema
    names are unverified in this environment, since no Windows host exists
    here to probe either integration path against. A real implementation
    of this `Protocol`, built once a specific bridge/extension is chosen,
    its advertised debugger capabilities are runtime-discovered, and
    Autodesk-approved, owns that real translation; this adapter only
    depends on the shape declared here.
    """

    def list_sessions(self) -> tuple[RemoteSessionInfo, ...]: ...

    def start_or_attach(self, target: TargetRef, reviewed_configuration: object) -> RemoteSessionInfo: ...

    def set_breakpoints(
        self, remote_session_id: str, breakpoints: tuple[Breakpoint, ...]
    ) -> tuple[BreakpointBindingResult, ...]: ...

    def is_paused(self, remote_session_id: str) -> bool: ...

    def get_stack(self, remote_session_id: str, frame_limit: int) -> tuple[dict, ...]: ...

    def get_variables(self, remote_session_id: str, frame_id: str, selected_names: tuple[str, ...]) -> dict: ...

    def step(self, remote_session_id: str, kind: str) -> None: ...

    def continue_execution(self, remote_session_id: str) -> None: ...

    def disconnect(self, remote_session_id: str) -> None: ...


class VisualStudioAdapter(BaseAdapter):
    ide_id = "visual_studio"
    supported_os = ("Windows",)
    proof_task_id = "T12"

    def __init__(self, client: VisualStudioDebugClient | None = None, *, host_id: str = "local-mac") -> None:
        """`client` is `None` by default (no Visual Studio bridge/extension
        connection) — every operation then fails closed with
        `BACKEND_UNAVAILABLE`, exactly like `cls()` with no arguments must
        still work for `test_adapters.py`'s enumeration tests."""
        self._client = client
        self._host_id = host_id
        self._sessions: dict[str, SessionRef] = {}
        self._generations: dict[str, int] = {}
        self._generation_counter = itertools.count(1)

    def _require_client(self) -> VisualStudioDebugClient:
        if self._client is None:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.BACKEND_UNAVAILABLE,
                    message="no Visual Studio debug client is attached; no bridge/extension is connected (IDE-03-A)",
                )
            )
        return self._client

    def _generation_for(self, remote_session_id: str, reported: int | None) -> int:
        if reported is not None:
            return reported
        if remote_session_id not in self._generations:
            self._generations[remote_session_id] = next(self._generation_counter)
        return self._generations[remote_session_id]

    def _to_session_ref(self, info: RemoteSessionInfo) -> SessionRef:
        session = SessionRef(
            host_id=self._host_id,
            ide=self.ide_id,
            ide_instance_id=info.ide_instance_id,
            debug_session_id=info.remote_session_id,
            session_generation=self._generation_for(info.remote_session_id, info.generation),
            pid=info.pid,
            executable=info.executable,
            state=info.state,
            capabilities=(),
        )
        self._sessions[session.debug_session_id] = session
        return session

    def list_sessions(self) -> tuple[SessionRef, ...]:
        client = self._require_client()
        return tuple(self._to_session_ref(info) for info in client.list_sessions())

    def launch_or_attach(self, target: TargetRef, reviewed_configuration: object) -> SessionRef:
        client = self._require_client()
        info = client.start_or_attach(target, reviewed_configuration)
        return self._to_session_ref(info)

    def set_breakpoints(
        self, session: SessionRef, resolved_locations: tuple[Breakpoint, ...]
    ) -> tuple[BreakpointBindingResult, ...]:
        client = self._require_client()
        return client.set_breakpoints(session.debug_session_id, resolved_locations)

    def is_paused(self, debug_session_id: str) -> bool:
        client = self._require_client()
        return client.is_paused(debug_session_id)

    def wait_for_stop(self, session: SessionRef, timeout: float) -> None:
        """The single-call, non-cancellable operation named in
        `CORE_OPERATIONS`/`GW-06`. `facade.AutoDebugFacade` does not call
        this directly — it polls `is_paused` itself in a short, cancellable
        loop (`DE-09`) — but this remains available for any other caller
        that wants one blocking call with a bounded timeout."""
        client = self._require_client()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if client.is_paused(session.debug_session_id):
                return
            time.sleep(0.05)
        raise AutoDebugError(
            ErrorDetail(code=ErrorCode.TIMEOUT, message="timed out waiting for a real pause event (DE-01)")
        )

    def get_stack(self, session: SessionRef, frame_limit: int) -> tuple[dict, ...]:
        client = self._require_client()
        return client.get_stack(session.debug_session_id, frame_limit)

    def get_variables(self, session: SessionRef, frame_id: str, selected_names: tuple[str, ...]) -> dict:
        """Returns raw, unredacted values — exactly like `FakeAdapter`/
        `VSCodeAdapter`/`CursorAdapter`/`CLionAdapter`/`XcodeAdapter`.
        Redaction (`DE-07`) happens exactly once, in
        `evidence.sanitize_observation`, called from
        `facade.autodebug_get_variables`."""
        client = self._require_client()
        return client.get_variables(session.debug_session_id, frame_id, selected_names)

    def step(self, session: SessionRef, kind: str) -> None:
        client = self._require_client()
        client.step(session.debug_session_id, kind)

    def continue_execution(self, session: SessionRef) -> None:
        client = self._require_client()
        client.continue_execution(session.debug_session_id)

    def disconnect(self, session: SessionRef) -> None:
        client = self._require_client()
        client.disconnect(session.debug_session_id)
        self._sessions.pop(session.debug_session_id, None)
