"""T04 acceptance tests — the case state machine (RP-01, RP-06, RP-08).
Stdlib `unittest` only, zero third-party packages."""

import unittest

from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.models import Breakpoint, CasePlan, CasePolicy, CaseState, IntakeSource, ReproductionPlan, TargetRef
from autodebug.workflow import BreakpointBindingResult, Case


def make_plan(**overrides) -> CasePlan:
    defaults = dict(
        schema_version="0.1-draft",
        case_id="CASE-2026-001",
        source_revision="abc123",
        target=TargetRef(host_id="local-mac", ide="clion", debug_session_id=None, pid=None),
        breakpoints=(Breakpoint(file="/repo/src/file.cpp", line=42),),
        reproduction=ReproductionPlan(mode="manual", steps=("Open a disposable design", "Invoke command X")),
        policy=CasePolicy(max_steps=20, max_inspection_seconds=300),
        digest_sha256=None,
    )
    defaults.update(overrides)
    return CasePlan(**defaults)


def staged_and_approved_case() -> Case:
    case = Case(case_id="CASE-2026-001")
    case.stage_plan(make_plan())
    case.mark_approved(case.plan.digest_sha256)
    return case


class TestIntake(unittest.TestCase):
    """RP-01: a case accepts developer text or a Jira summary; no credential
    field exists anywhere to store Jira access tokens."""

    def test_jira_unavailable_developer_text_still_drafts_a_case(self):
        case = Case(case_id="CASE-2026-001")
        case.record_intake(IntakeSource.DEVELOPER_TEXT, "Opening a sketch sometimes enters an invalid state")
        self.assertEqual(case.intake_source, IntakeSource.DEVELOPER_TEXT)

    def test_jira_source_recorded_without_any_credential_field(self):
        case = Case(case_id="CASE-2026-001")
        case.record_intake(IntakeSource.JIRA, "FUS-1234: undo after combine crashes")
        self.assertEqual(case.intake_source, IntakeSource.JIRA)
        self.assertFalse(hasattr(case, "jira_token"))
        self.assertFalse(hasattr(case, "jira_credentials"))

    def test_empty_description_is_rejected(self):
        case = Case(case_id="CASE-2026-001")
        with self.assertRaises(ValueError):
            case.record_intake(IntakeSource.DEVELOPER_TEXT, "")


class TestRP08StateDistinction(unittest.TestCase):
    """RP-08: generated / approved / execution-requested are three distinct,
    independently observable states — never conflated or skipped."""

    def test_generated_approved_and_execution_requested_are_distinct(self):
        case = Case(case_id="CASE-2026-001")

        case.stage_plan(make_plan())
        generated_state = case.state  # "script generated"
        self.assertEqual(generated_state, CaseState.AWAITING_APPROVAL)

        case.mark_approved(case.plan.digest_sha256)
        approved_state = case.state  # "approved"
        self.assertEqual(approved_state, CaseState.APPROVED)
        self.assertNotEqual(approved_state, generated_state)

        case.begin_arming()
        case.confirm_session()
        case.bind_breakpoints((BreakpointBindingResult(file="/repo/src/file.cpp", line=42, bound=True),))
        case.begin_reproduction()
        execution_requested_state = case.state  # "execution requested"
        self.assertEqual(execution_requested_state, CaseState.AWAITING_DEVELOPER_REPRODUCTION)
        self.assertNotEqual(execution_requested_state, approved_state)
        self.assertNotEqual(execution_requested_state, generated_state)

    def test_cannot_jump_straight_from_generated_to_execution_requested(self):
        case = Case(case_id="CASE-2026-001")
        case.stage_plan(make_plan())
        with self.assertRaises(AutoDebugError) as ctx:
            case.begin_reproduction()
        self.assertEqual(ctx.exception.detail.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(case.state, CaseState.AWAITING_APPROVAL)  # unchanged


class TestRP06BreakpointBindingGate(unittest.TestCase):
    def test_all_bound_advances_to_breakpoints_bound(self):
        case = staged_and_approved_case()
        case.begin_arming()
        case.confirm_session()
        case.bind_breakpoints((BreakpointBindingResult(file="/repo/src/file.cpp", line=42, bound=True),))
        self.assertEqual(case.state, CaseState.BREAKPOINTS_BOUND)

    def test_unbound_breakpoint_fails_closed_and_never_claims_ready(self):
        # RP-06-A: symbols missing -> BREAKPOINT_UNBOUND, reproduction not ready.
        case = staged_and_approved_case()
        case.begin_arming()
        case.confirm_session()
        with self.assertRaises(AutoDebugError) as ctx:
            case.bind_breakpoints(
                (BreakpointBindingResult(file="/repo/src/file.cpp", line=42, bound=False, reason="missing symbols"),)
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.BREAKPOINT_UNBOUND)
        self.assertEqual(case.state, CaseState.SESSION_VERIFIED)  # did not advance

        with self.assertRaises(AutoDebugError):
            case.begin_reproduction()  # still cannot report ready-to-reproduce

    def test_partial_binding_failure_also_fails_closed(self):
        case = staged_and_approved_case()
        case.begin_arming()
        case.confirm_session()
        with self.assertRaises(AutoDebugError) as ctx:
            case.bind_breakpoints(
                (
                    BreakpointBindingResult(file="a.cpp", line=1, bound=True),
                    BreakpointBindingResult(file="b.cpp", line=2, bound=False, reason="unresolved"),
                )
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.BREAKPOINT_UNBOUND)
        self.assertEqual(case.state, CaseState.SESSION_VERIFIED)


class TestPlanChangeInvalidatesApproval(unittest.TestCase):
    """RP-05's mechanism (not its trust layer): a modified plan invalidates
    a stale approval and returns the case to AWAITING_APPROVAL."""

    def test_revising_an_approved_plan_returns_to_awaiting_approval(self):
        case = staged_and_approved_case()
        old_digest = case.approved_digest

        case.revise_plan(make_plan(source_revision="def456"))

        self.assertEqual(case.state, CaseState.AWAITING_APPROVAL)
        self.assertIsNone(case.approved_digest)
        self.assertNotEqual(case.plan.digest_sha256, old_digest)

    def test_stale_approval_digest_is_rejected_after_revision(self):
        case = staged_and_approved_case()
        old_digest = case.approved_digest
        case.revise_plan(make_plan(source_revision="def456"))

        with self.assertRaises(AutoDebugError) as ctx:
            case.mark_approved(old_digest)
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PLAN_CHANGED)

    def test_fresh_digest_is_accepted_after_revision(self):
        case = staged_and_approved_case()
        case.revise_plan(make_plan(source_revision="def456"))
        case.mark_approved(case.plan.digest_sha256)  # must not raise
        self.assertEqual(case.state, CaseState.APPROVED)

    def test_check_plan_unchanged_passes_when_nothing_changed(self):
        case = staged_and_approved_case()
        case.check_plan_unchanged()  # must not raise

    def test_begin_arming_without_approval_is_rejected(self):
        case = Case(case_id="CASE-2026-001")
        case.stage_plan(make_plan())  # AWAITING_APPROVAL, not yet APPROVED
        with self.assertRaises(AutoDebugError) as ctx:
            case.begin_arming()
        self.assertEqual(ctx.exception.detail.code, ErrorCode.NOT_APPROVED)


class TestIllegalTransitionsFailClosed(unittest.TestCase):
    def test_cannot_finalize_a_brand_new_case(self):
        case = Case(case_id="CASE-2026-001")
        with self.assertRaises(AutoDebugError) as ctx:
            case.finalize()
        self.assertEqual(ctx.exception.detail.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(case.state, CaseState.NEW)

    def test_cannot_bind_breakpoints_before_a_session_exists(self):
        case = staged_and_approved_case()
        with self.assertRaises(AutoDebugError):
            case.bind_breakpoints((BreakpointBindingResult(file="a.cpp", line=1, bound=True),))
        self.assertEqual(case.state, CaseState.APPROVED)

    def test_any_state_can_be_cancelled(self):
        for case in (staged_and_approved_case(), Case(case_id="CASE-2026-002")):
            with self.subTest(state=case.state):
                case.cancel()
                self.assertEqual(case.state, CaseState.CANCELLED)

    def test_cancelled_case_is_terminal(self):
        case = Case(case_id="CASE-2026-001")
        case.cancel()
        with self.assertRaises(AutoDebugError) as ctx:
            case.stage_plan(make_plan())
        # A cancelled case reports CANCELLED, not the generic INTERNAL_ERROR —
        # a precise existing code exists for "this case is already closed."
        self.assertEqual(ctx.exception.detail.code, ErrorCode.CANCELLED)

    def test_timed_out_case_reports_timeout_not_a_generic_error(self):
        case = Case(case_id="CASE-2026-001")
        case.stage_plan(make_plan())
        case.time_out()
        with self.assertRaises(AutoDebugError) as ctx:
            case.finalize()  # any further transition attempt, not just approval
        self.assertEqual(ctx.exception.detail.code, ErrorCode.TIMEOUT)

    def test_failed_case_has_no_precise_code_so_falls_back_to_internal_error(self):
        # FAILED/INCOMPLETE/FINALIZED have no corresponding existing error
        # code, so they correctly fall back to INTERNAL_ERROR rather than a
        # misleading fit — this is the remaining, explicitly-flagged gap.
        case = Case(case_id="CASE-2026-001")
        case.fail()
        with self.assertRaises(AutoDebugError) as ctx:
            case.stage_plan(make_plan())
        self.assertEqual(ctx.exception.detail.code, ErrorCode.INTERNAL_ERROR)


if __name__ == "__main__":
    unittest.main()
