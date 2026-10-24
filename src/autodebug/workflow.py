"""Case state machine (T04) — RP-01, RP-06, RP-08 workflow gating.

`Case` tracks one investigation's lifecycle end to end. Every transition is
checked against an explicit legal-transition graph (design.md's "Case
workflow states"); an attempted transition outside that graph fails closed
rather than silently happening. Operating on an already-`CANCELLED` or
`TIMED_OUT` case reuses those states' own error codes (`CANCELLED`,
`TIMEOUT`) since they're a precise semantic match; every other illegal
transition — including `FAILED`/`INCOMPLETE`/`FINALIZED` terminal states,
which have no corresponding existing code — falls back to `INTERNAL_ERROR`.
Nothing here verifies
*who* approved a plan or whether that approval is trustworthy — that is
T05's approvals.py. This module only enforces that the steps happen in the
right order, that a changed plan invalidates a stale approval (RP-05's
mechanism, not its trust decision), and that breakpoints are confirmed bound
before reproduction is ever requested (RP-06).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from autodebug import plans
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import CasePlan, CaseState, IntakeSource

_TERMINAL_RECOVERY = frozenset(
    {CaseState.CANCELLED, CaseState.FAILED, CaseState.TIMED_OUT, CaseState.INCOMPLETE}
)

#: Legal transitions, per design.md's "Case workflow states". Every
#: non-terminal state can additionally fall through to any terminal/recovery
#: state (cancel/fail/time out/incomplete) — merged in below.
_LEGAL_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.NEW: frozenset({CaseState.PLAN_STAGED}),
    CaseState.PLAN_STAGED: frozenset({CaseState.AWAITING_APPROVAL}),
    CaseState.AWAITING_APPROVAL: frozenset({CaseState.APPROVED}),
    CaseState.APPROVED: frozenset({CaseState.STARTING_OR_ATTACHING, CaseState.AWAITING_APPROVAL}),
    CaseState.STARTING_OR_ATTACHING: frozenset({CaseState.SESSION_VERIFIED, CaseState.AWAITING_APPROVAL}),
    CaseState.SESSION_VERIFIED: frozenset({CaseState.BREAKPOINTS_BOUND, CaseState.AWAITING_APPROVAL}),
    CaseState.BREAKPOINTS_BOUND: frozenset({CaseState.AWAITING_DEVELOPER_REPRODUCTION, CaseState.AWAITING_APPROVAL}),
    CaseState.AWAITING_DEVELOPER_REPRODUCTION: frozenset({CaseState.PAUSED, CaseState.FINALIZED}),
    CaseState.PAUSED: frozenset({CaseState.INSPECTING, CaseState.AWAITING_DEVELOPER_REPRODUCTION}),
    CaseState.INSPECTING: frozenset({CaseState.PAUSED, CaseState.FINALIZED, CaseState.AWAITING_DEVELOPER_REPRODUCTION}),
    CaseState.FINALIZED: frozenset(),
    CaseState.CANCELLED: frozenset(),
    CaseState.FAILED: frozenset(),
    CaseState.TIMED_OUT: frozenset(),
    CaseState.INCOMPLETE: frozenset(),
}
for _state, _targets in list(_LEGAL_TRANSITIONS.items()):
    if _state not in _TERMINAL_RECOVERY and _state is not CaseState.FINALIZED:
        _LEGAL_TRANSITIONS[_state] = _targets | _TERMINAL_RECOVERY

#: Two of the five terminal states already have a semantically precise
#: existing error code for "you tried to operate on a case that's already
#: there" — reuse them instead of the generic INTERNAL_ERROR. FAILED,
#: INCOMPLETE and FINALIZED have no corresponding code among the 16 defined
#: in errors.py, so they fall through to INTERNAL_ERROR below rather than
#: force a misleading fit.
_TERMINAL_STATE_ERROR_CODES: dict[CaseState, ErrorCode] = {
    CaseState.CANCELLED: ErrorCode.CANCELLED,
    CaseState.TIMED_OUT: ErrorCode.TIMEOUT,
}


@dataclass
class BreakpointBindingResult:
    """The real, adapter-reported outcome of attempting to bind one
    breakpoint (RP-06). A *requested* breakpoint is never treated as bound
    until something like this says so."""

    file: str
    line: int
    bound: bool
    reason: str = ""


@dataclass
class Case:
    case_id: str
    state: CaseState = CaseState.NEW
    plan: CasePlan | None = None
    approved_digest: str | None = None
    bound_breakpoints: tuple[BreakpointBindingResult, ...] = ()
    intake_source: IntakeSource | None = None
    intake_description: str = ""

    def _transition(self, new_state: CaseState) -> None:
        allowed = _LEGAL_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            if self.state in _TERMINAL_STATE_ERROR_CODES:
                raise AutoDebugError(
                    ErrorDetail(
                        code=_TERMINAL_STATE_ERROR_CODES[self.state],
                        message=f"case is already {self.state.value}; cannot transition to {new_state.value}",
                    )
                )
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=f"illegal state transition {self.state.value} -> {new_state.value}",
                )
            )
        self.state = new_state

    def record_intake(self, source: IntakeSource, description: str) -> None:
        """RP-01: accept a bug report from Jira (via an already-authorized
        external connector) or developer-supplied text. AutoDebug never stores
        Jira credentials — no such field exists anywhere in this module or
        `autodebug.models`."""
        if not description:
            raise ValueError("intake description must not be empty")
        self.intake_source = source
        self.intake_description = description

    def stage_plan(self, plan: CasePlan) -> None:
        """RP-03: validate and record the plan. This is the 'script
        generated' moment of RP-08's generated/approved/execution-requested
        distinction — distinct from `mark_approved` and `begin_reproduction`
        below."""
        if plan.case_id != self.case_id:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="plan belongs to another case"))
        validated = plans.stage_plan(plan)  # raises ValueError if malformed
        self._transition(CaseState.PLAN_STAGED)
        self.plan = validated
        self._transition(CaseState.AWAITING_APPROVAL)

    def revise_plan(self, new_plan: CasePlan) -> None:
        """A material plan change after approval invalidates it (RP-05) and
        returns the case to `AWAITING_APPROVAL` for re-review — this is the
        mechanism RP-05 depends on, not the trust decision over who may
        re-approve it."""
        if new_plan.case_id != self.case_id:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="plan belongs to another case"))
        validated = plans.stage_plan(new_plan)
        self._transition(CaseState.AWAITING_APPROVAL)
        self.plan = validated
        self.approved_digest = None

    def mark_approved(self, approved_digest: str) -> None:
        """RP-08's 'approved' moment. This only checks the approved digest
        still matches the currently staged plan — it does not verify *who*
        approved it or that the approval is trustworthy; that verification
        is T05's approvals.py, which calls this once it has done so."""
        if self.plan is None:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="no plan staged"))
        if approved_digest != self.plan.digest_sha256:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.PLAN_CHANGED,
                    message="approved digest does not match the currently staged plan",
                )
            )
        self.approved_digest = approved_digest
        self._transition(CaseState.APPROVED)

    def check_plan_unchanged(self) -> None:
        """Re-check before any privileged operation (see docs/mcp-contract.md
        "Re-check approval + session identity on every privileged call").
        A plan whose digest no longer matches its approval fails closed."""
        if self.plan is None or self.approved_digest is None:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="case is not approved"))
        if plans.compute_plan_digest(self.plan) != self.approved_digest:
            raise AutoDebugError(
                ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="the plan has changed since it was approved")
            )

    def begin_arming(self) -> None:
        self.check_plan_unchanged()
        self._transition(CaseState.STARTING_OR_ATTACHING)

    def confirm_session(self) -> None:
        self._transition(CaseState.SESSION_VERIFIED)

    def bind_breakpoints(self, results: tuple[BreakpointBindingResult, ...]) -> None:
        """RP-06: only transition to `BREAKPOINTS_BOUND` if every requested
        breakpoint actually bound; otherwise fail closed with
        `BREAKPOINT_UNBOUND` and never claim ready-to-reproduce."""
        if self.plan is None:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="no plan staged"))
        requested = Counter((bp.file, bp.line) for bp in self.plan.breakpoints)
        returned = Counter((result.file, result.line) for result in results)
        if requested != returned:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.BREAKPOINT_UNBOUND, message="binding response does not cover exactly the reviewed breakpoints"))
        self.bound_breakpoints = results
        unbound = [r for r in results if not r.bound]
        if unbound:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.BREAKPOINT_UNBOUND,
                    message=(
                        f"{len(unbound)} breakpoint(s) failed to bind: "
                        + ", ".join(f"{r.file}:{r.line} ({r.reason})" for r in unbound)
                    ),
                )
            )
        self._transition(CaseState.BREAKPOINTS_BOUND)

    def begin_reproduction(self) -> None:
        """RP-08's 'execution requested' moment — only reachable once
        breakpoints are confirmed bound."""
        self._transition(CaseState.AWAITING_DEVELOPER_REPRODUCTION)

    def pause(self) -> None:
        self._transition(CaseState.PAUSED)

    def inspect(self) -> None:
        self._transition(CaseState.INSPECTING)

    def resume(self) -> None:
        self._transition(CaseState.AWAITING_DEVELOPER_REPRODUCTION)

    def finalize(self) -> None:
        self._transition(CaseState.FINALIZED)

    def cancel(self) -> None:
        self._transition(CaseState.CANCELLED)

    def fail(self) -> None:
        self._transition(CaseState.FAILED)

    def time_out(self) -> None:
        self._transition(CaseState.TIMED_OUT)

    def mark_incomplete(self) -> None:
        self._transition(CaseState.INCOMPLETE)
