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
UNAVAILABLE, not an automatic download or code copy" — rather than the bare
`NotImplementedError` the other four still-stub adapters raise. That
distinction is intentional: this adapter is no longer a stub declaring "not
implemented," it is a real implementation reporting "backend not reachable,"
which is the correct typed outcome once an adapter actually exists.

**Real-backend authorization remains fully gated.** Nothing in this file
touches `approvals.py`. `ApprovalBroker.verify_approval` still
unconditionally refuses any `backend_kind != "fake"`
(`approvals.FAKE_BACKEND_KIND`), so arming a case against this adapter
through the facade's `authorize_and_arm` path still fails with
`TARGET_MISMATCH`/`PERMISSION_DENIED` regardless of this implementation —
see `tests/test_vscode_adapter.py`'s
`TestAuthorizationGateStillBlocksVSCode` for a regression proving this.
"""

from __future__ import annotations

import itertools
import time
from typing import Protocol

from autodebug.adapters.base import BaseAdapter, RemoteSessionInfo
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import Breakpoint, SessionRef, TargetRef
from autodebug.workflow import BreakpointBindingResult

__all__ = ["DebugMCPClient", "RemoteSessionInfo", "VSCodeAdapter"]


class DebugMCPClient(Protocol):
    """The minimal operations `VSCodeAdapter` needs from a connected
    DebugMCP session. This is AutoDebug's own abstraction — method names
    and shapes here are *not* DebugMCP's actual remote tool/schema names,
    which remain unverified (`docs/vscode-debugmcp-mapping.md`). A real
    implementation of this `Protocol`, built once the extension is
    installed and Autodesk-approved, owns that real translation; this
    adapter only depends on the shape declared here.
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


class VSCodeAdapter(BaseAdapter):
    ide_id = "vscode"
    supported_os = ("Windows", "Darwin", "Linux")
    proof_task_id = "T08"

    def __init__(self, client: DebugMCPClient | None = None, *, host_id: str = "local-mac") -> None:
        """`client` is `None` by default (no DebugMCP connection) — every
        operation then fails closed with `BACKEND_UNAVAILABLE`, exactly
        like `cls()` with no arguments must still work for
        `test_adapters.py`'s enumeration tests. `host_id` defaults to the
        single-local-machine convention this project already uses
        throughout (`docs/architecture.md`) — AutoDebug is loopback-only,
        per `CLAUDE.md`, so one adapter instance only ever represents one
        local host.
        """
        self._client = client
        self._host_id = host_id
        self._sessions: dict[str, SessionRef] = {}
        self._generations: dict[str, int] = {}
        self._generation_counter = itertools.count(1)

    def _require_client(self) -> DebugMCPClient:
        if self._client is None:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.BACKEND_UNAVAILABLE,
                    message="no DebugMCP client is attached; the extension is not connected (IDE-03-A)",
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
        that wants one blocking call with a bounded timeout.
        """
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
        """Returns raw, unredacted values — exactly like `FakeAdapter`.
        Redaction (`DE-07`) happens exactly once, in
        `evidence.sanitize_observation`, called from
        `facade.autodebug_get_variables`. Duplicating it here would be a
        second, divergent redaction point, not defense in depth."""
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
