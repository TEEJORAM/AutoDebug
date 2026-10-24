"""BaseAdapter: the common protocol every IDE adapter implements.

`probe()` (T01) only determines OS-applicability. `probe_capabilities()` (T02)
goes one level deeper: given a backend description (a real adapter connection
in later tasks, a `FakeBackend` fixture until then — see
`tests/fixtures/fake_backend.py`), it reports a per-operation capability state
so `UNKNOWN`, `UNAVAILABLE`, `UNSUPPORTED` and `NOT_APPLICABLE` stay distinct
(GW-02). Nothing here contacts a real IDE, process, or network.
"""

from __future__ import annotations

import itertools
import platform
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import Breakpoint, CapabilityState, SessionRef, TargetRef

if TYPE_CHECKING:
    from autodebug.workflow import BreakpointBindingResult

#: The core debugger operations every adapter is probed against (GW-02).
#: `probe()`/`probe_capabilities()` never contact a real IDE to build this list
#: — it mirrors the adapter protocol itself (docs/architecture.md).
CORE_OPERATIONS: tuple[str, ...] = (
    "list_sessions",
    "launch_or_attach",
    "set_breakpoints",
    "wait_for_stop",
    "is_paused",
    "get_stack",
    "get_variables",
    "step",
    "continue_execution",
    "disconnect",
)


class BackendDescription(Protocol):
    """Shape a backend (fake today, real from T08) must expose to be probed."""

    installed: bool
    reachable: bool
    ide_version: str | None
    backend_version: str | None
    supported_operations: frozenset[str]


@dataclass(frozen=True)
class RemoteSessionInfo:
    """What a real adapter's injected debug client reports about one remote
    session (T08, generalized for reuse across adapters at T09). This shape
    is AutoDebug's own, adapter-agnostic abstraction — never a transcription
    of any specific IDE's real wire protocol (see each adapter module's own
    docstring for what remains unverified about its particular backend).

    `generation` is `None` whenever the client cannot report a stable
    per-attach generation/start-time marker. When `None`, the adapter
    assigns and tracks its own generation counter per `remote_session_id`
    as a fallback, so `GW-03`'s stale-session/PID-reuse checks still have
    *something* to compare — an AutoDebug-side safety net, not a claim that
    any specific backend tracks generations itself.
    """

    remote_session_id: str
    pid: int
    ide_instance_id: str
    executable: str
    state: str
    generation: int | None = None


@dataclass(frozen=True)
class ProbeResult:
    ide: str
    host_os: str
    state: CapabilityState
    reason: str
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityReport:
    """GW-02 — a per-operation capability breakdown, not just one boolean."""

    ide: str
    host_os: str
    state: CapabilityState
    ide_version: str | None
    backend_version: str | None
    reason: str
    operations: dict[str, CapabilityState] = field(default_factory=dict)


class BaseAdapter:
    ide_id: str = ""
    supported_os: tuple[str, ...] = ()
    proof_task_id: str = ""

    def get_stop(self, session):
        raise AutoDebugError(ErrorDetail(
            code=ErrorCode.CAPABILITY_UNSUPPORTED,
            message="verified process-start and stop identity are unavailable for this adapter",
        ))

    def probe(self, host_os: str | None = None) -> ProbeResult:
        host_os = host_os or platform.system()
        if host_os not in self.supported_os:
            return ProbeResult(
                ide=self.ide_id,
                host_os=host_os,
                state=CapabilityState.NOT_APPLICABLE,
                reason=f"{self.ide_id} is not a target on {host_os}",
            )
        return ProbeResult(
            ide=self.ide_id,
            host_os=host_os,
            state=CapabilityState.UNKNOWN,
            reason=f"capability discovery not yet implemented (see tasks.md {self.proof_task_id})",
        )

    def probe_capabilities(
        self,
        backend: BackendDescription | None = None,
        host_os: str | None = None,
    ) -> CapabilityReport:
        """GW-02 — report IDE/backend version, reachability and per-operation
        support. `backend` stands in for a real IDE connection; until T08–T12
        only a `FakeBackend` fixture is ever passed here (see tests/fixtures).
        """
        host_os = host_os or platform.system()

        if host_os not in self.supported_os:
            # IDE-02-A: never attempt to probe a backend on the wrong OS.
            return CapabilityReport(
                ide=self.ide_id,
                host_os=host_os,
                state=CapabilityState.NOT_APPLICABLE,
                ide_version=None,
                backend_version=None,
                reason=f"{self.ide_id} is not a target on {host_os}",
            )

        if backend is None:
            # Not yet probed — distinct from "probed and absent" (UNAVAILABLE).
            return CapabilityReport(
                ide=self.ide_id,
                host_os=host_os,
                state=CapabilityState.UNKNOWN,
                ide_version=None,
                backend_version=None,
                reason=f"capability discovery not yet run for {self.ide_id}",
            )

        if not backend.installed or not backend.reachable:
            # GW-02-A: UNAVAILABLE with a reason, never an invented tool list.
            return CapabilityReport(
                ide=self.ide_id,
                host_os=host_os,
                state=CapabilityState.UNAVAILABLE,
                ide_version=backend.ide_version,
                backend_version=backend.backend_version,
                reason=(
                    f"{self.ide_id} backend is not installed"
                    if not backend.installed
                    else f"{self.ide_id} backend is installed but unreachable"
                ),
                operations={op: CapabilityState.UNAVAILABLE for op in CORE_OPERATIONS},
            )

        # GW-02-B: reachable backend — report each operation individually;
        # a missing operation is UNSUPPORTED, never faked as AVAILABLE.
        operations = {
            op: (
                CapabilityState.AVAILABLE
                if op in backend.supported_operations
                else CapabilityState.UNSUPPORTED
            )
            for op in CORE_OPERATIONS
        }
        overall = (
            CapabilityState.AVAILABLE
            if all(state is CapabilityState.AVAILABLE for state in operations.values())
            else CapabilityState.UNSUPPORTED
        )
        return CapabilityReport(
            ide=self.ide_id,
            host_os=host_os,
            state=overall,
            ide_version=backend.ide_version,
            backend_version=backend.backend_version,
            reason=(
                "all core operations supported"
                if overall is CapabilityState.AVAILABLE
                else "backend reachable but missing one or more core operations"
            ),
            operations=operations,
        )

    def require_capability(self, report: CapabilityReport, operation: str) -> None:
        """GW-02-B — raise `CAPABILITY_UNSUPPORTED` if `operation` isn't
        `AVAILABLE` in `report`; never silently proceed with a faked result."""
        if report.operations.get(operation) is not CapabilityState.AVAILABLE:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.CAPABILITY_UNSUPPORTED,
                    message=f"{self.ide_id}.{operation} is not supported by the connected backend",
                )
            )

    def _not_implemented(self, operation: str):
        raise NotImplementedError(
            f"{self.ide_id}.{operation}() is not implemented — native debugger "
            f"proof is deferred to tasks.md {self.proof_task_id}"
        )

    def list_sessions(self):
        self._not_implemented("list_sessions")

    def launch_or_attach(self, target, reviewed_configuration):
        self._not_implemented("launch_or_attach")

    def set_breakpoints(self, session, resolved_locations):
        self._not_implemented("set_breakpoints")

    def wait_for_stop(self, session, timeout):
        self._not_implemented("wait_for_stop")

    def is_paused(self, debug_session_id):
        """Non-blocking, single-check poll: is this session currently
        paused? `wait_for_stop` is the single-call, bounded variant named in
        `CORE_OPERATIONS`/`GW-06`; concrete adapters typically implement it
        as a loop over this check. The facade itself polls `get_stop`, which
        additionally carries a verified stop identity."""
        self._not_implemented("is_paused")

    def get_stack(self, session, frame_limit):
        self._not_implemented("get_stack")

    def get_variables(self, session, frame_id, selected_names):
        self._not_implemented("get_variables")

    def step(self, session, kind):
        self._not_implemented("step")

    def continue_execution(self, session):
        self._not_implemented("continue_execution")

    def disconnect(self, session):
        self._not_implemented("disconnect")


class RemoteDebugClient(Protocol):
    """The minimal operations a client-backed adapter needs from a connected
    IDE debugger bridge. This is AutoDebug's own abstraction, never a
    transcription of any IDE's real wire protocol. Each adapter module
    declares its own distinctly named sub-protocol, so a client written for
    one IDE is never implied to fit another (IDE-03)."""

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


class ClientBackedAdapter(BaseAdapter):
    """Shared implementation for adapters that delegate every operation to
    a constructor-injected `RemoteDebugClient` (T08-T12).

    With no client attached (the default, so `cls()` always works), every
    operation fails closed with `BACKEND_UNAVAILABLE` (IDE-03-A). Values
    are returned raw: DE-07 redaction happens exactly once, at the facade
    boundary. Nothing here spawns a process, touches `approvals.py`, or
    contacts a real debugger; `verify_approval` still refuses every
    `backend_kind != "fake"`.
    """

    #: Shown when no client is attached; each subclass names its bridge.
    missing_client_message: str = "no debug client is attached"

    def __init__(self, client: RemoteDebugClient | None = None, *, host_id: str = "local-mac") -> None:
        self._client = client
        self._host_id = host_id
        self._generations: dict[str, int] = {}
        self._generation_counter = itertools.count(1)

    def _require_client(self) -> RemoteDebugClient:
        if self._client is None:
            raise AutoDebugError(
                ErrorDetail(code=ErrorCode.BACKEND_UNAVAILABLE, message=f"{self.missing_client_message} (IDE-03-A)")
            )
        return self._client

    def _generation_for(self, remote_session_id: str, reported: int | None) -> int:
        """Use the client's generation when reported; otherwise track a
        local per-session counter so GW-03 identity checks still have
        something to compare."""
        if reported is not None:
            return reported
        if remote_session_id not in self._generations:
            self._generations[remote_session_id] = next(self._generation_counter)
        return self._generations[remote_session_id]

    def _to_session_ref(self, info: RemoteSessionInfo) -> SessionRef:
        return SessionRef(
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

    def list_sessions(self) -> tuple[SessionRef, ...]:
        return tuple(self._to_session_ref(info) for info in self._require_client().list_sessions())

    def launch_or_attach(self, target: TargetRef, reviewed_configuration: object) -> SessionRef:
        return self._to_session_ref(self._require_client().start_or_attach(target, reviewed_configuration))

    def set_breakpoints(
        self, session: SessionRef, resolved_locations: tuple[Breakpoint, ...]
    ) -> tuple[BreakpointBindingResult, ...]:
        return self._require_client().set_breakpoints(session.debug_session_id, resolved_locations)

    def is_paused(self, debug_session_id: str) -> bool:
        return self._require_client().is_paused(debug_session_id)

    def wait_for_stop(self, session: SessionRef, timeout: float) -> None:
        """Single bounded blocking wait; the facade polls instead (DE-09)."""
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
        return self._require_client().get_stack(session.debug_session_id, frame_limit)

    def get_variables(self, session: SessionRef, frame_id: str, selected_names: tuple[str, ...]) -> dict:
        return self._require_client().get_variables(session.debug_session_id, frame_id, selected_names)

    def step(self, session: SessionRef, kind: str) -> None:
        self._require_client().step(session.debug_session_id, kind)

    def continue_execution(self, session: SessionRef) -> None:
        self._require_client().continue_execution(session.debug_session_id)

    def disconnect(self, session: SessionRef) -> None:
        self._require_client().disconnect(session.debug_session_id)
