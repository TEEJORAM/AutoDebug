"""BaseAdapter: the common protocol every IDE adapter implements.

`probe()` (T01) only determines OS-applicability. `probe_capabilities()` (T02)
goes one level deeper: given a backend description (a real adapter connection
in later tasks, a `FakeBackend` fixture until then — see
`tests/fixtures/fake_backend.py`), it reports a per-operation capability state
so `UNKNOWN`, `UNAVAILABLE`, `UNSUPPORTED` and `NOT_APPLICABLE` stay distinct
(GW-02). Nothing here contacts a real IDE, process, or network.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from typing import Protocol

from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import CapabilityState

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
        paused? (T08.) This is the primitive `facade.AutoDebugFacade`'s
        cancellable `autodebug_wait_for_stop` loop actually calls — it polls
        this on a short interval instead of making one long blocking
        `wait_for_stop` call, so a cancellation request is observed
        promptly. `wait_for_stop` above remains the single-call, non
        -cancellable operation named in `CORE_OPERATIONS`/`GW-06`; a
        concrete adapter is expected to implement both, typically with
        `wait_for_stop` looping over this same check internally.

        This was previously only implemented ad hoc on the `FakeAdapter`
        test double, with no corresponding declaration here — a real gap,
        since nothing enforced that a future real adapter would provide it
        too. Declaring it formally here closes that gap.
        """
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
