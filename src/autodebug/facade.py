"""MCP tool facade (T07) — GW-01, GW-06, RP-04, DE-01, DE-03, DE-09.

Composes T01-T06 components (`Case`, `Router`, `SessionRegistry`,
`ApprovalBroker`, `EvidenceStore`) behind the documented `autodebug_*` tool
surface from `docs/mcp-contract.md`. This module exposes those tools as
plain Python callables — there is **no MCP SDK dependency anywhere in this
file**, by explicit developer instruction overriding `tasks.md`'s literal
T07 text; a real MCP transport binding is deferred until a separate
dependency-approval step is granted.

**Fake backend only.** Every `AutoDebugFacade` method here operates purely
against caller-supplied fake adapters/backends (see `tests/fixtures/`); the
real-debugger security gate from T05 remains OPEN / NOT APPROVED and
nothing in this module changes that — `approvals.verify_approval` still
unconditionally refuses any `backend_kind` other than `"fake"`.

**Trust boundary (binding, not advisory).** There is deliberately no method
here that calls `ApprovalBroker.issue_approval` — per `docs/mcp-contract.md`,
"AutoDebug must not expose an MCP tool that lets the agent self-approve a
plan." An `ApprovalRecord` must always arrive from a separate, already-
trusted local process that called `issue_approval` directly; this facade
only ever *verifies* an approval it is handed (`autodebug_arm_case`,
`autodebug_step`, `autodebug_continue`), never issues one.

Every privileged operation that actually arms a session routes exclusively
through `approvals.authorize_and_arm` — never through `Router.arm_target`
directly — per T05's binding requirement recorded in `tasks.md`. `step`/
`continue` have no `Router` operation to perform, so they call
`ApprovalBroker.verify_approval` directly (the same enforced check
`authorize_and_arm` itself calls first); no tool anywhere in this file
calls `self._router.arm_target(...)` on its own.

**This module is NOT an MCP server.** `AutoDebugFacade` is a plain Python
class with plain Python methods — there is no `stdio`/HTTP transport, no
request/response framing, no tool-registration/discovery handshake, and no
MCP SDK object anywhere in this file or its dependency graph. Binding this
facade to an actual MCP transport (per `docs/mcp-contract.md`'s "Protocol
transport" section) is explicitly out of scope for T07 and remains a
future task, contingent on the still-open dependency-approval blocker
(`docs/status.md`, blocker #1).
"""

from __future__ import annotations

import threading
import time
import logging
import math
import json
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, ParamSpec, TypeVar

from autodebug.adapters.base import BaseAdapter, CapabilityReport
from autodebug.approvals import ApprovalBroker, authorize_and_arm
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.evidence import EvidenceStore, build_investigation_report, sanitize_observation, sanitize_output, sanitize_text, validate_case_id
from autodebug.models import ApprovalRecord, CasePlan, CaseState, ExecutionConfidence, IntakeSource, RootCauseConfidence, SessionRef, StopSnapshot, TargetRef
from autodebug.operations import call_bounded
from autodebug.router import Router
from autodebug.sessions import SessionLease, SessionRegistry
from autodebug.workflow import Case

#: Approval-scope component conventions. A separate trusted process issuing
#: an `ApprovalRecord` (via `ApprovalBroker.issue_approval`, never called
#: from this module) MUST use these exact scope strings and the
#: `target_identity_for` format below — the agent has no ability to choose
#: or influence either value itself; this facade only verifies, never sets.
SCOPE_ARM = "op:arm_case"
SCOPE_STEP = "op:step"
SCOPE_CONTINUE = "op:continue"
SCOPE_WAIT = "op:wait_for_stop"
SCOPE_STACK = "op:get_stack"
SCOPE_VARIABLES = "op:get_variables"
MAX_SELECTION = 50
_LOG = logging.getLogger(__name__)
P = ParamSpec("P")
T = TypeVar("T")


def target_identity_for(target: TargetRef) -> str:
    """Canonical `target_identity` string used as the approval scope's
    `target:` component (RP-05). Must match exactly what the separate
    trusted approval-issuing process used when calling `issue_approval`."""
    discriminator = target.pid if target.pid is not None else target.debug_session_id
    return f"{target.host_id}/{target.ide}/{discriminator}"


def _ok(case_id: str | None, result: object = None) -> dict:
    return {"ok": True, "case_id": case_id, "result": result}


def _err(case_id: str | None, detail: ErrorDetail) -> dict:
    return {
        "ok": False,
        "case_id": sanitize_text(case_id) if isinstance(case_id, str) else None,
        "error": {"code": detail.code.value, "message": sanitize_text(detail.message), "recoverable": detail.recoverable},
    }


@dataclass
class _CaseContext:
    case: Case
    adapter: BaseAdapter
    target: TargetRef
    session: SessionRef | None = None
    approval: ApprovalRecord | None = None
    evidence_store: EvidenceStore | None = None
    steps_taken: int = 0
    inspection_started_at: float | None = None
    has_confirmed_stop: bool = False
    stop: StopSnapshot | None = None
    arming_started_at: float | None = None
    backend_active: threading.Event = field(default_factory=threading.Event)
    disconnect_lock: threading.Lock = field(default_factory=threading.Lock)
    disconnected: bool = False
    recorded_stops: set[str] = field(default_factory=set)
    operation_lock: threading.Lock = field(default_factory=threading.Lock)
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    cancel_event: object = None  # threading.Event, injected by the facade


class AutoDebugFacade:
    """Owns one process's in-memory case contexts and exposes the
    documented `autodebug_*` tools. `now`/`sleep` are injected (same
    determinism convention as `ApprovalBroker`) so `autodebug_wait_for_stop`
    stays testable without a real wall-clock dependency; production callers
    pass `time.monotonic`/`time.sleep`.
    """

    def __init__(
        self,
        *,
        registry: SessionRegistry,
        broker: ApprovalBroker,
        evidence_base_dir: Path,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        event_factory: Callable[[], object] = threading.Event,
        poll_interval: float = 0.01,
    ) -> None:
        self._registry = registry
        self._router = Router(registry)
        self._broker = broker
        self._evidence_base_dir = Path(evidence_base_dir)
        self._now = now
        self._sleep = sleep
        self._event_factory = event_factory
        self._poll_interval = poll_interval
        self._cases: dict[str, _CaseContext] = {}
        self._cases_lock = threading.Lock()

    # -- internal helpers -------------------------------------------------

    def _lookup(self, case_id: str) -> _CaseContext:
        try:
            return self._cases[case_id]
        except KeyError:
            raise AutoDebugError(
                ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message=f"unknown case_id {case_id!r}", recoverable=False)
            ) from None

    def _ensure_inspecting(self, ctx: _CaseContext) -> None:
        stop = self._get_stop(ctx)
        if stop is None:
            if ctx.case.state in (CaseState.PAUSED, CaseState.INSPECTING):
                ctx.case.resume()
            ctx.stop = None
            raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_PAUSED, message="native session is running"))
        if ctx.stop is None or stop != ctx.stop:
            if ctx.case.state in (CaseState.PAUSED, CaseState.INSPECTING):
                ctx.case.resume()
            ctx.stop = None
            raise AutoDebugError(ErrorDetail(code=ErrorCode.SESSION_STALE, message="debugger stop changed; wait for a fresh verified stop"))
        if ctx.case.state == CaseState.PAUSED:
            ctx.case.inspect()
        elif ctx.case.state != CaseState.INSPECTING:
            raise AutoDebugError(
                ErrorDetail(code=ErrorCode.NOT_PAUSED, message="case is not currently paused or inspecting")
            )

    def _call(self, ctx: _CaseContext, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        if not getattr(ctx.adapter, "supports_bounded_operations", False):
            raise AutoDebugError(ErrorDetail(code=ErrorCode.CAPABILITY_UNSUPPORTED, message="adapter has no reviewed bounded-operation contract"))
        started = ctx.inspection_started_at if ctx.inspection_started_at is not None else ctx.arming_started_at
        remaining = ctx.case.plan.policy.max_inspection_seconds - (self._now() - started) if started is not None else ctx.case.plan.policy.max_operation_seconds
        if remaining <= 0:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="case deadline exhausted before dispatch"))

        def execute() -> T:
            ctx.backend_active.set()
            try:
                if ctx.cancel_event.is_set():
                    raise AutoDebugError(ErrorDetail(code=ErrorCode.CANCELLED, message="cancelled before backend dispatch"))
                return function(*args, **kwargs)
            except AutoDebugError:
                raise
            except Exception:
                _LOG.error("Backend raised an unexpected exception; investigation refused")
                raise AutoDebugError(ErrorDetail(code=ErrorCode.BACKEND_UNAVAILABLE, message="backend operation failed")) from None
            finally:
                ctx.backend_active.clear()

        def cleanup(value: T) -> None:
            session = value if isinstance(value, SessionRef) else cleanup_session
            disconnect_session(session)

        def disconnect_session(session: SessionRef | None) -> None:
            if session is not None and not ctx.disconnected:
                ctx.adapter.disconnect(session)
                self._registry.unregister(session)
                ctx.disconnected = True

        cleanup_session = ctx.session
        return call_bounded(
            execute, timeout=min(remaining, ctx.case.plan.policy.max_operation_seconds),
            cancellation=ctx.cancel_event, on_abandon=lambda: self._registry.quarantine(ctx.target),
            on_late_result=cleanup,
            on_late_error=lambda: disconnect_session(cleanup_session),
        )

    def _get_stop(self, ctx: _CaseContext) -> StopSnapshot | None:
        snapshot = self._call(ctx, ctx.adapter.get_stop, ctx.session)
        if snapshot is None:
            return None
        if (
            not isinstance(snapshot, StopSnapshot) or snapshot.session != ctx.session
            or not snapshot.session.process_start_id
            or not isinstance(snapshot.stop_id, str) or not snapshot.stop_id
            or sanitize_text(snapshot.stop_id) != snapshot.stop_id
            or not isinstance(snapshot.frame_generation, int) or isinstance(snapshot.frame_generation, bool)
            or snapshot.frame_generation < 1 or not isinstance(snapshot.reason, str) or not snapshot.reason.strip()
        ):
            raise AutoDebugError(ErrorDetail(code=ErrorCode.SESSION_STALE, message="invalid or stale debugger stop identity"))
        if snapshot.reason == "breakpoint" and (snapshot.breakpoint_file, snapshot.breakpoint_line) not in {
            (bp.file, bp.line) for bp in ctx.case.plan.breakpoints
        }:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.TARGET_MISMATCH, message="stop is not at a reviewed bound breakpoint"))
        return snapshot

    def _record(self, ctx: _CaseContext, event_type: str, name: str, value: str, *, frame: str = "") -> None:
        stop = ctx.stop
        ctx.evidence_store.record_evidence(
            event_type=event_type, session_id=ctx.session.debug_session_id,
            source_revision=ctx.case.plan.source_revision, frame=frame,
            observation_name=name, observation_value=value, expected="", confidence="observation-only",
            execution_confidence=(ExecutionConfidence.DEVELOPER_REPORTED if ctx.case.plan.reproduction.mode == "api_script"
                                  else ExecutionConfidence.NOT_APPLICABLE),
            stop_id=stop.stop_id if stop else None,
            frame_generation=stop.frame_generation if stop else None,
            process_start_id=ctx.session.process_start_id, plan_digest=ctx.case.approved_digest,
        )

    def _disconnect(self, ctx: _CaseContext) -> None:
        with ctx.disconnect_lock:
            if ctx.session is None or ctx.disconnected or ctx.backend_active.is_set():
                return
            session = ctx.session
            try:
                call_bounded(
                    lambda: ctx.adapter.disconnect(session), timeout=ctx.case.plan.policy.max_operation_seconds,
                    cancellation=threading.Event(), on_abandon=lambda: self._registry.quarantine(ctx.target),
                )
            except Exception:
                self._registry.quarantine(ctx.target)
                _LOG.error("Backend disconnect failed; target quarantined")
                raise AutoDebugError(ErrorDetail(code=ErrorCode.BACKEND_UNAVAILABLE, message="backend disconnect failed")) from None
            ctx.disconnected = True
            self._registry.unregister(session)

    def _verify_session(self, ctx: _CaseContext) -> None:
        """GW-03-B, re-applied at the facade layer: re-check PID,
        generation, and IDE instance identity immediately before *any*
        operation that reads from or mutates a live session — not just
        `autodebug_wait_for_stop`. A session that exited, or whose identity
        was reassigned (PID reuse, a new generation, a different IDE
        window) since it was armed, fails closed here (`SESSION_STALE` /
        `TARGET_MISMATCH`) before the adapter is ever called again.

        `SESSION_STALE` specifically — the session has disappeared, the
        fake-world equivalent of `DE-08`'s "IDE exits mid-investigation" —
        additionally labels the case honestly `INCOMPLETE` and retains
        whatever partial evidence already exists, per `DE-08`: "stop
        additional privileged actions, preserve sanitized partial evidence
        and label the case incomplete." `TARGET_MISMATCH` (a reused PID or
        reassigned identity — a security concern, not a disconnect) does
        not trigger this; it is simply refused.
        """
        if ctx.session is None:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="case has no armed session yet"))
        try:
            self._registry.verify_identity(
                ctx.session,
                expected_pid=ctx.session.pid,
                expected_generation=ctx.session.session_generation,
                expected_ide_instance_id=ctx.session.ide_instance_id,
            )
        except AutoDebugError as exc:
            if exc.detail.code is ErrorCode.SESSION_STALE:
                self._mark_incomplete(ctx)
            raise

    def _mark_incomplete(self, ctx: _CaseContext) -> None:
        """DE-08: retain partial evidence once without changing terminal cases."""
        with ctx.state_lock:
            if ctx.case.state not in (
                CaseState.FINALIZED, CaseState.CANCELLED, CaseState.FAILED,
                CaseState.TIMED_OUT, CaseState.INCOMPLETE,
            ):
                ctx.case.mark_incomplete()
                if ctx.session is not None:
                    self._registry.release_owner(ctx.session, ctx)
                if ctx.evidence_store is not None:
                    ctx.evidence_store.finalize(case_state=ctx.case.state.value, report=None)

    def _check_binding(self, ctx: _CaseContext) -> None:
        if ctx.case.plan is None:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="no plan staged"))
        if ctx.case.plan.case_id != ctx.case.case_id:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="plan belongs to another case"))
        if ctx.case.plan.target != ctx.target:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.TARGET_MISMATCH, message="target differs from plan"))

    def _check_active(self, ctx: _CaseContext, approval: ApprovalRecord | None, scope: str) -> None:
        if ctx.cancel_event.is_set() or ctx.case.state == CaseState.CANCELLED:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.CANCELLED, message="case was cancelled"))
        self._verify_session(ctx)
        self._check_binding(ctx)
        if approval is None:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="case has no approval"))
        ctx.case.check_plan_unchanged()
        self._verify_approval(ctx, approval, scope)
        if ctx.case.state in (CaseState.FINALIZED, CaseState.FAILED, CaseState.INCOMPLETE, CaseState.TIMED_OUT):
            raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="case is no longer active"))
        self._registry.verify_owner(ctx.session, ctx)
        if (
            ctx.inspection_started_at is not None
            and self._now() - ctx.inspection_started_at >= ctx.case.plan.policy.max_inspection_seconds
        ):
            self._mark_incomplete(ctx)
            raise AutoDebugError(ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="inspection time budget exhausted"))

    def _storage_error(self, case_id: str) -> dict:
        _LOG.error("Evidence persistence failed; operation refused")
        return _err(case_id, ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message="evidence persistence failed"))

    def _operation_error(self, case_id: str, error: AutoDebugError) -> dict:
        ctx = self._cases.get(case_id)
        if ctx is not None and error.detail.code in (ErrorCode.BACKEND_UNAVAILABLE, ErrorCode.TIMEOUT, ErrorCode.CANCELLED):
            try:
                self._mark_incomplete(ctx)
            except (OSError, ValueError):
                return self._storage_error(ctx.case.case_id)
        return _err(case_id, error.detail)

    def _check_armed_target(self, ctx: _CaseContext) -> None:
        session = ctx.session
        target = ctx.target
        if (
            not session.process_start_id or sanitize_text(session.process_start_id) != session.process_start_id
            or session.host_id != target.host_id or session.ide != target.ide
            or (target.pid is not None and session.pid != target.pid)
            or (target.debug_session_id is not None and session.debug_session_id != target.debug_session_id)
            or (target.ide_instance_id is not None and session.ide_instance_id != target.ide_instance_id)
            or (target.process_start_id is not None and session.process_start_id != target.process_start_id)
        ):
            raise AutoDebugError(ErrorDetail(code=ErrorCode.TARGET_MISMATCH, message="returned session differs from approved target"))

    def _check_arming(self, ctx: _CaseContext, approval: ApprovalRecord, started: float) -> None:
        if ctx.cancel_event.is_set():
            raise AutoDebugError(ErrorDetail(code=ErrorCode.CANCELLED, message="case was cancelled during arming"))
        self._check_binding(ctx)
        self._check_armed_target(ctx)
        self._verify_session(ctx)
        self._broker.verify_approval(
            approval, plan=ctx.case.plan, backend_kind=ctx.adapter.ide_id,
            target_identity=target_identity_for(ctx.target), required_scope=SCOPE_ARM,
        )
        if self._now() - started >= ctx.case.plan.policy.max_inspection_seconds:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="arming time budget exhausted"))

    def _verify_approval(self, ctx: _CaseContext, approval: ApprovalRecord, required_scope: str) -> None:
        """`DE-08` (T15 gap closure): approval expiration discovered
        mid-investigation (`autodebug_step`/`autodebug_continue`) is a
        recovery trigger exactly like a session disconnect — DE-08 names
        "debugger disconnect, user cancellation, or **approval
        expiration**" as the three triggers. `APPROVAL_EXPIRED` here
        mirrors `_verify_session`'s `SESSION_STALE` handling: it labels the
        case `INCOMPLETE` and preserves partial evidence. Every other
        `verify_approval` refusal (`PERMISSION_DENIED`, `PLAN_CHANGED`,
        `CANCELLED`, `NOT_APPROVED`) is a distinct authorization/trust
        failure, not a recovery condition, and is simply refused — it must
        never mark a valid case incomplete. This helper is not used by
        `autodebug_arm_case`'s `authorize_and_arm` call: at arm time there
        is no session or evidence yet, so "incomplete" would be
        meaningless; an expired approval there is just refused, unchanged.
        """
        try:
            self._broker.verify_approval(
                approval,
                plan=ctx.case.plan,
                backend_kind=ctx.adapter.ide_id,
                target_identity=target_identity_for(ctx.target),
                required_scope=required_scope,
            )
        except AutoDebugError as exc:
            if exc.detail.code is ErrorCode.APPROVAL_EXPIRED:
                self._mark_incomplete(ctx)
            raise

    def _rollback_failed_arming(self, ctx: _CaseContext, session: SessionRef, *, newly_created: bool = True) -> None:
        """Best-effort cleanup when arming succeeds (a session is live and
        authorized) but a later step in the same `autodebug_arm_case` call
        — breakpoint binding, most likely (`RP-06`/`BREAKPOINT_UNBOUND`) —
        fails. Without this, the case was previously left stuck at
        `SESSION_VERIFIED` holding a live, registered, still-authorized
        session and a still-valid approval with no tool able to move it
        forward or clean it up — a resource leak and a lingering armed
        session with no supervising case. This does not retry binding (no
        retry tool exists) and does not invent a new `Case` state; it uses
        only existing primitives: disconnect + unregister the session,
        revoke the approval (DE-09's revocation mechanism, reused here),
        and move the case to the existing terminal `FAILED` state."""
        ctx.session = session
        if newly_created:
            try:
                self._disconnect(ctx)
            except Exception:
                _LOG.error("Adapter disconnect failed during arming rollback")
            self._registry.unregister(session)
        self._registry.release_owner(session, ctx)
        self._broker.revoke_for_case(ctx.case.case_id)
        ctx.session = None
        if ctx.case.state not in (CaseState.FAILED, CaseState.CANCELLED, CaseState.INCOMPLETE, CaseState.TIMED_OUT):
            ctx.case.fail()
        if ctx.evidence_store is not None:
            try:
                ctx.evidence_store.finalize(case_state=ctx.case.state.value, report=None)
            except (OSError, ValueError):
                _LOG.error("Evidence persistence failed during arming rollback")

    # -- read-only tools ----------------------------------------------------

    def autodebug_health(self) -> dict:
        return _ok(
            None,
            {
                "status": "ok",
                "backend_mode": "fake-only",
                "security_gate": "OPEN / NOT APPROVED — real debugger control is disabled",
            },
        )

    def autodebug_probe_adapters(self, *, adapters) -> dict:
        """`adapters` is an iterable of `(adapter, backend, host_os)`
        triples the caller already holds. This facade owns no adapter
        instances of its own and performs no IDE discovery — real adapter
        wiring is T08-T12."""
        reports = []
        for adapter, backend, host_os in adapters:
            report: CapabilityReport = adapter.probe_capabilities(backend, host_os)
            reports.append(
                {
                    "ide": report.ide,
                    "host_os": report.host_os,
                    "state": report.state.value,
                    "ide_version": report.ide_version,
                    "backend_version": report.backend_version,
                    "reason": report.reason,
                    "operations": {op: state.value for op, state in report.operations.items()},
                }
            )
        return _ok(None, sanitize_output({"adapters": reports}))

    def autodebug_list_sessions(self) -> dict:
        return _ok(None, sanitize_output({"sessions": [asdict(s) for s in self._registry.all_sessions()]}))

    # -- case lifecycle -------------------------------------------------

    def autodebug_create_case(
        self, *, case_id: str, intake_source: IntakeSource, intake_description: str, adapter: BaseAdapter, target: TargetRef
    ) -> dict:
        try:
            validate_case_id(case_id)
        except ValueError as exc:
            return _err(case_id, ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message=str(exc), recoverable=True))
        with self._cases_lock:
            if case_id in self._cases:
                return _err(
                    case_id, ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message=f"case {case_id!r} already exists")
                )
            case = Case(case_id=case_id)
            try:
                case.record_intake(intake_source, intake_description)
            except ValueError as exc:
                return _err(case_id, ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message=str(exc), recoverable=True))
            self._cases[case_id] = _CaseContext(
                case=case, adapter=adapter, target=target, cancel_event=self._event_factory()
            )
        return _ok(case_id, {"state": case.state.value})

    def autodebug_stage_plan(self, *, case_id: str, plan: CasePlan) -> dict:
        try:
            ctx = self._lookup(case_id)
            if plan.target != ctx.target:
                raise AutoDebugError(ErrorDetail(code=ErrorCode.TARGET_MISMATCH, message="target differs from case"))
            ctx.case.stage_plan(plan)
        except AutoDebugError as exc:
            return _err(case_id, exc.detail)
        except ValueError as exc:
            return _err(case_id, ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message=str(exc), recoverable=True))
        return _ok(case_id, {"state": ctx.case.state.value, "digest_sha256": ctx.case.plan.digest_sha256})

    def autodebug_get_plan(self, *, case_id: str) -> dict:
        try:
            ctx = self._lookup(case_id)
        except AutoDebugError as exc:
            return _err(case_id, exc.detail)
        if ctx.case.plan is None:
            return _err(case_id, ErrorDetail(code=ErrorCode.NOT_APPROVED, message="no plan staged yet", recoverable=True))
        return _ok(case_id, {"plan": asdict(ctx.case.plan), "state": ctx.case.state.value})

    def autodebug_arm_case(
        self,
        *,
        case_id: str,
        approval: ApprovalRecord,
        capability_report: CapabilityReport,
        reviewed_configuration: object,
        process_running: bool,
    ) -> dict:
        try:
            ctx = self._lookup(case_id)
            with SessionLease(ctx.operation_lock), self._registry.arming_lease(ctx.target):
                self._check_binding(ctx)
                if ctx.case.state != CaseState.AWAITING_APPROVAL:
                    raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="case is not awaiting approval"))
                self._broker.verify_approval(
                    approval, plan=ctx.case.plan, backend_kind=ctx.adapter.ide_id,
                    target_identity=target_identity_for(ctx.target), required_scope=SCOPE_ARM,
                )
                existing = self._registry.resolve(ctx.target)
                with self._registry.lease(existing) if existing is not None else nullcontext():
                    if existing is not None:
                        self._registry.claim(existing, ctx)
                    started = self._now()
                    ctx.arming_started_at = started
                    try:
                        try:
                            ctx.evidence_store = EvidenceStore(self._evidence_base_dir, case_id, max_events=ctx.case.plan.policy.max_evidence_records)
                        except (OSError, ValueError):
                            self._broker.revoke_for_case(case_id)
                            ctx.case.fail()
                            return self._storage_error(case_id)
                        session = authorize_and_arm(
                            self._broker, approval, plan=ctx.case.plan,
                            target_identity=target_identity_for(ctx.target),
                            required_scope=SCOPE_ARM, router=self._router, adapter=ctx.adapter,
                            capability_report=capability_report, target=ctx.target,
                            reviewed_configuration=reviewed_configuration, process_running=process_running,
                            launch=lambda target, configuration: self._call(ctx, ctx.adapter.launch_or_attach, target, configuration),
                        )
                        ctx.session = session
                        with self._registry.lease(session) if existing is None else nullcontext():
                            self._registry.claim(session, ctx)
                            self._check_arming(ctx, approval, started)
                            ctx.case.mark_approved(approval.plan_digest)
                            ctx.case.begin_arming()
                            ctx.case.confirm_session()
                            binding_results = self._call(ctx, ctx.adapter.set_breakpoints, session, ctx.case.plan.breakpoints)
                            self._check_arming(ctx, approval, started)
                            ctx.case.bind_breakpoints(binding_results)
                            ctx.case.begin_reproduction()
                        ctx.approval = approval
                        ctx.inspection_started_at = self._now()
                    except Exception:
                        if ctx.session is not None:
                            self._rollback_failed_arming(ctx, ctx.session, newly_created=existing is None)
                        else:
                            self._broker.revoke_for_case(case_id)
                            if ctx.case.state not in (CaseState.FAILED, CaseState.CANCELLED):
                                ctx.case.fail()
                        raise
                    finally:
                        if existing is not None and ctx.approval is None:
                            self._registry.release_owner(existing, ctx)
        except AutoDebugError as exc:
            return _err(case_id, exc.detail)
        return _ok(case_id, sanitize_output({"state": ctx.case.state.value, "session": asdict(session)}))

    def autodebug_case_status(self, *, case_id: str) -> dict:
        try:
            ctx = self._lookup(case_id)
        except AutoDebugError as exc:
            return _err(case_id, exc.detail)
        return _ok(
            case_id,
            sanitize_output({
                "state": ctx.case.state.value,
                "bound_breakpoints": [asdict(r) for r in ctx.case.bound_breakpoints],
                "session": asdict(ctx.session) if ctx.session else None,
            }),
        )

    def autodebug_wait_for_stop(self, *, case_id: str, timeout_seconds: float) -> dict:
        try:
            ctx = self._lookup(case_id)
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (float, int))
                or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0
            ):
                raise AutoDebugError(ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="wait timeout must be positive and finite"))
            start = self._now()
            while True:
                # DE-09: checked first, every iteration, so a cancellation
                # requested from another thread is observed within one
                # `poll_interval` tick rather than only after a timeout.
                if ctx.cancel_event.is_set():
                    raise AutoDebugError(
                        ErrorDetail(code=ErrorCode.CANCELLED, message="case was cancelled while waiting for a pause")
                    )
                with SessionLease(ctx.operation_lock), self._registry.lease(ctx.session) if ctx.session is not None else nullcontext():
                    self._check_active(ctx, ctx.approval, SCOPE_WAIT)
                    stop = self._get_stop(ctx)
                    self._check_active(ctx, ctx.approval, SCOPE_WAIT)
                    if stop is not None:
                        if ctx.case.state not in (CaseState.PAUSED, CaseState.INSPECTING):
                            ctx.case.pause()
                        ctx.has_confirmed_stop = True
                        ctx.stop = stop
                        with ctx.state_lock:
                            self._check_active(ctx, ctx.approval, SCOPE_WAIT)
                            if stop.stop_id not in ctx.recorded_stops:
                                self._record(ctx, "stop_observed", "stop_reason", stop.reason)
                                ctx.recorded_stops.add(stop.stop_id)
                        break
                if self._now() - start >= timeout_seconds:
                    self._mark_incomplete(ctx)
                    raise AutoDebugError(
                        ErrorDetail(code=ErrorCode.TIMEOUT, message="timed out waiting for a real pause event (DE-01)")
                    )
                self._sleep(self._poll_interval)
        except AutoDebugError as exc:
            return self._operation_error(case_id, exc)
        except (OSError, ValueError):
            return self._storage_error(case_id)
        return _ok(case_id, {"state": ctx.case.state.value})

    def autodebug_get_stack(self, *, case_id: str, frame_limit: int) -> dict:
        try:
            ctx = self._lookup(case_id)
            if isinstance(frame_limit, bool) or not isinstance(frame_limit, int) or not 1 <= frame_limit <= MAX_SELECTION:
                raise AutoDebugError(ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="frame_limit must be between 1 and 50"))
            with SessionLease(ctx.operation_lock), self._registry.lease(ctx.session) if ctx.session is not None else nullcontext():
                self._check_active(ctx, ctx.approval, SCOPE_STACK)
                ctx.evidence_store.require_capacity(1)
                self._ensure_inspecting(ctx)
                self._check_active(ctx, ctx.approval, SCOPE_STACK)
                frames = self._call(ctx, ctx.adapter.get_stack, ctx.session, frame_limit)
                self._check_active(ctx, ctx.approval, SCOPE_STACK)
                self._ensure_inspecting(ctx)
                frames = self._call(ctx, sanitize_output, frames[:frame_limit])
                self._check_active(ctx, ctx.approval, SCOPE_STACK)
                self._ensure_inspecting(ctx)
                with ctx.state_lock:
                    self._check_active(ctx, ctx.approval, SCOPE_STACK)
                    self._record(ctx, "stack_observed", "stack", json.dumps(frames, sort_keys=True))
        except AutoDebugError as exc:
            return self._operation_error(case_id, exc)
        except (OSError, ValueError):
            return self._storage_error(case_id)
        return _ok(case_id, {"frames": frames})

    def autodebug_get_variables(self, *, case_id: str, frame_id: str, selected_names: tuple[str, ...]) -> dict:
        try:
            ctx = self._lookup(case_id)
            if (
                not isinstance(selected_names, tuple) or not 1 <= len(selected_names) <= MAX_SELECTION
                or any(not isinstance(name, str) or not name or len(name) > 500 for name in selected_names)
                or not isinstance(frame_id, str) or not frame_id or len(frame_id) > 500
            ):
                raise AutoDebugError(ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="bounded frame and named variable selection required"))
            # RP-08/mcp-contract.md: "AutoDebug SHALL default to
            # developer_reported for api_script cases absent real
            # instrumentation" — no real instrumentation exists anywhere in
            # this project (no adapter confirms a script actually ran), so
            # an api_script-mode case's observations are always, at best,
            # developer-reported; a manual-mode case has no script to have
            # run at all, so NOT_APPLICABLE (the model default) is correct.
            with SessionLease(ctx.operation_lock), self._registry.lease(ctx.session) if ctx.session is not None else nullcontext():
                self._check_active(ctx, ctx.approval, SCOPE_VARIABLES)
                ctx.evidence_store.require_capacity(len(set(selected_names)))
                self._ensure_inspecting(ctx)
                self._check_active(ctx, ctx.approval, SCOPE_VARIABLES)
                execution_confidence = (
                    ExecutionConfidence.DEVELOPER_REPORTED
                    if ctx.case.plan.reproduction.mode == "api_script"
                    else ExecutionConfidence.NOT_APPLICABLE
                )
                raw = self._call(ctx, ctx.adapter.get_variables, ctx.session, frame_id, selected_names)
                self._check_active(ctx, ctx.approval, SCOPE_VARIABLES)
                self._ensure_inspecting(ctx)
                self._check_active(ctx, ctx.approval, SCOPE_VARIABLES)
                sanitized: dict[str, str] = {}
                observations: list[tuple[str, str]] = []
                for name in dict.fromkeys(selected_names):
                    if name not in raw:
                        continue
                    value = raw[name]
                    bounded_value = self._call(ctx, sanitize_output, value)
                    text_value = json.dumps(bounded_value, sort_keys=True) if isinstance(bounded_value, (dict, list)) else str(bounded_value)
                    sanitized_value, _note = sanitize_observation(name, text_value)
                    safe_name = sanitize_text(name)
                    if safe_name in sanitized:
                        raise AutoDebugError(ErrorDetail(code=ErrorCode.SENSITIVE_OUTPUT_BLOCKED, message="redacted variable names collide"))
                    sanitized[safe_name] = sanitized_value
                    observations.append((name, sanitized_value))
                    self._check_active(ctx, ctx.approval, SCOPE_VARIABLES)
                self._ensure_inspecting(ctx)
                with ctx.state_lock:
                    for name, sanitized_value in observations:
                        self._check_active(ctx, ctx.approval, SCOPE_VARIABLES)
                        self._record(ctx, "variable_observed", name, sanitized_value, frame=f"frame:{frame_id}")
                self._check_active(ctx, ctx.approval, SCOPE_VARIABLES)
        except AutoDebugError as exc:
            return self._operation_error(case_id, exc)
        except (OSError, ValueError):
            return self._storage_error(case_id)
        return _ok(case_id, {
            "variables": sanitize_output(sanitized),
            "unavailable_names": [sanitize_text(name) for name in selected_names if name not in raw],
        })

    def autodebug_step(self, *, case_id: str, approval: ApprovalRecord, kind: str) -> dict:
        try:
            ctx = self._lookup(case_id)
            if kind not in ("step_over", "step_in", "step_out"):
                raise AutoDebugError(ErrorDetail(code=ErrorCode.CAPABILITY_UNSUPPORTED, message="unsupported step kind"))
            if ctx.case.state not in (CaseState.PAUSED, CaseState.INSPECTING):
                raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_PAUSED, message="case must be paused to step"))
            max_steps = ctx.case.plan.policy.max_steps
            # GW-05 (T15 gap closure): `SessionRegistry.lease` was built in
            # T03 and unit-tested there, but no facade tool ever acquired it
            # — two concurrent `step`/`continue` calls on the same session
            # could race through the adapter with no serialization at all.
            # A second concurrent attempt now fails closed with
            # `POLICY_LIMIT` rather than racing or queuing silently.
            with self._registry.lease(ctx.session), SessionLease(ctx.operation_lock):
                self._check_active(ctx, approval, SCOPE_STEP)
                self._ensure_inspecting(ctx)
                self._check_active(ctx, approval, SCOPE_STEP)
                if ctx.steps_taken >= max_steps:
                    raise AutoDebugError(
                        ErrorDetail(
                            code=ErrorCode.POLICY_LIMIT,
                            message=f"case reached its {max_steps}-step budget (DE-03)",
                        )
                    )
                self._call(ctx, ctx.adapter.step, ctx.session, kind)
                ctx.steps_taken += 1
                self._check_active(ctx, approval, SCOPE_STEP)
                stop = self._get_stop(ctx)
                self._check_active(ctx, approval, SCOPE_STEP)
                ctx.stop = stop
                if stop is None:
                    ctx.case.resume()
                self._check_active(ctx, approval, SCOPE_STEP)
        except AutoDebugError as exc:
            return self._operation_error(case_id, exc)
        except (OSError, ValueError):
            return self._storage_error(case_id)
        return _ok(case_id, {"steps_taken": ctx.steps_taken})

    def autodebug_continue(self, *, case_id: str, approval: ApprovalRecord) -> dict:
        try:
            ctx = self._lookup(case_id)
            if ctx.case.state not in (CaseState.PAUSED, CaseState.INSPECTING):
                raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_PAUSED, message="case must be paused to continue"))
            with self._registry.lease(ctx.session), SessionLease(ctx.operation_lock):
                self._check_active(ctx, approval, SCOPE_CONTINUE)
                self._ensure_inspecting(ctx)
                self._check_active(ctx, approval, SCOPE_CONTINUE)
                self._call(ctx, ctx.adapter.continue_execution, ctx.session)
                self._check_active(ctx, approval, SCOPE_CONTINUE)
                ctx.case.resume()
                ctx.stop = None
        except AutoDebugError as exc:
            return self._operation_error(case_id, exc)
        except (OSError, ValueError):
            return self._storage_error(case_id)
        return _ok(case_id, {"state": ctx.case.state.value})

    def autodebug_complete_case(
        self,
        *,
        case_id: str,
        root_cause_statement: str,
        confidence: RootCauseConfidence,
        evidence_ids: tuple[str, ...],
        reproduced: bool,
        uncertainties: tuple[str, ...] = (),
        next_steps: tuple[str, ...] = (),
        causal_validation: str | None = None,
    ) -> dict:
        try:
            ctx = self._lookup(case_id)
            with SessionLease(ctx.operation_lock), ctx.state_lock:
                incomplete_states = (CaseState.CANCELLED, CaseState.FAILED, CaseState.TIMED_OUT, CaseState.INCOMPLETE)
                if ctx.case.state not in (CaseState.PAUSED, CaseState.INSPECTING, CaseState.AWAITING_DEVELOPER_REPRODUCTION, *incomplete_states):
                    raise AutoDebugError(
                        ErrorDetail(code=ErrorCode.NOT_PAUSED, message="case must be inspecting or awaiting reproduction")
                    )
                if reproduced and not ctx.has_confirmed_stop:
                    raise AutoDebugError(
                        ErrorDetail(code=ErrorCode.NOT_PAUSED, message="reproduction requires a confirmed debugger stop")
                    )
                if ctx.evidence_store is None:
                    raise AutoDebugError(
                        ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message="case has no evidence store")
                    )
                if not isinstance(evidence_ids, tuple) or any(not isinstance(eid, str) for eid in evidence_ids):
                    raise AutoDebugError(
                        ErrorDetail(
                            code=ErrorCode.INTERNAL_ERROR,
                            message="evidence_ids must be a tuple of strings (DE-06)",
                            recoverable=True,
                        )
                    )
                recorded_ids = {
                    record.evidence_id
                    for record in ctx.evidence_store.read_events()
                    if record.case_id == ctx.case.case_id
                }
                unknown_ids = [eid for eid in evidence_ids if eid not in recorded_ids]
                if unknown_ids:
                    raise AutoDebugError(
                        ErrorDetail(
                            code=ErrorCode.INTERNAL_ERROR,
                            message=f"evidence_ids {unknown_ids} were never recorded for case {case_id!r} (DE-06)",
                            recoverable=True,
                        )
                    )
                report = build_investigation_report(
                    case_id=case_id,
                    root_cause_statement=root_cause_statement,
                    confidence=confidence,
                    evidence_ids=evidence_ids,
                    reproduced=reproduced,
                    uncertainties=uncertainties,
                    next_steps=next_steps,
                    causal_validation=causal_validation,
                    execution_confidence=(ExecutionConfidence.DEVELOPER_REPORTED if ctx.case.plan.reproduction.mode == "api_script"
                                          else ExecutionConfidence.NOT_APPLICABLE),
                )
                if ctx.backend_active.is_set():
                    raise AutoDebugError(ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="backend call is still retiring"))
                self._disconnect(ctx)
                final_state = ctx.case.state if ctx.case.state in incomplete_states else CaseState.FINALIZED
                ctx.evidence_store.finalize(case_state=final_state.value, report=report)
                if final_state is CaseState.FINALIZED:
                    if ctx.case.state is CaseState.PAUSED:
                        ctx.case.inspect()
                    ctx.case.finalize()
                if ctx.session is not None:
                    self._registry.release_owner(ctx.session, ctx)
                self._broker.revoke_for_case(case_id)
        except AutoDebugError as exc:
            return _err(case_id, exc.detail)
        except ValueError as exc:
            return _err(case_id, ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message=str(exc), recoverable=True))
        except OSError:
            return self._storage_error(case_id)
        return _ok(case_id, {
            "state": ctx.case.state.value,
            "summary": f"Case completed with {report.confidence.value} confidence; reproduced={report.reproduced}.",
            "artifacts": {name: f"{case_id}/{name}" for name in ("case.json", "events.jsonl", "report.md")},
        })

    def autodebug_cancel_case(self, *, case_id: str) -> dict:
        """DE-09, tool-facade scope: idempotent, interrupts a pending
        `autodebug_wait_for_stop` promptly, revokes the case's approval, and
        retains partial evidence. Detaches AutoDebug's adapter connection,
        without terminating the target application or IDE."""
        try:
            ctx = self._lookup(case_id)
        except AutoDebugError as exc:
            return _err(case_id, exc.detail)
        with ctx.state_lock:
            if ctx.case.state != CaseState.CANCELLED:
                try:
                    ctx.case.cancel()
                except AutoDebugError as exc:
                    return _err(case_id, exc.detail)
            ctx.cancel_event.set()
            if ctx.backend_active.is_set():
                self._registry.quarantine(ctx.target)
            self._broker.revoke_for_case(case_id)
        if ctx.evidence_store is not None:
            try:
                self._disconnect(ctx)
                ctx.evidence_store.finalize(case_state=ctx.case.state.value, report=None)
            except AutoDebugError as exc:
                return self._operation_error(case_id, exc)
            except (OSError, ValueError):
                return self._storage_error(case_id)
        with ctx.state_lock:
            if ctx.session is not None:
                self._registry.release_owner(ctx.session, ctx)
        return _ok(case_id, {"state": ctx.case.state.value})
