"""T15 acceptance tests — Security/Quality/Release Gate (`GW-05`, `DE-06`,
`DE-08`). Stdlib `unittest` only, zero third-party packages, no MCP SDK.

This file closes three concrete gaps found during the T15 security review,
all pre-existing since earlier tasks and none specific to any one IDE
adapter:

1. `GW-05` — `SessionRegistry.lease()` (built in T03, unit-tested in
   `test_sessions.py`) was never acquired by any facade tool. Two
   concurrent `autodebug_step`/`autodebug_continue` calls on the same
   session could race through the adapter with no serialization at all.
2. `DE-08` — approval expiration discovered mid-investigation (inside
   `autodebug_step`/`autodebug_continue`) did not label the case
   `INCOMPLETE`, even though DE-08's requirement text names "approval
   expiration" as a recovery trigger alongside disconnect and
   cancellation, and `docs/traceability.md` maps DE-08 to T15.
3. `DE-06` — "Every conclusion SHALL cite stored evidence IDs" was never
   actually enforced: `autodebug_complete_case` accepted any
   caller-supplied `evidence_ids` tuple, including IDs that were never
   recorded by `EvidenceStore.record_evidence` at all. A caller (the AI
   agent) could cite a fabricated evidence ID and have it accepted into a
   `CONFIRMED`/`LIKELY` report.

Everything here runs against `FakeAdapter`/the fake backend only, per the
unchanged T05 security gate.
"""

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from autodebug.approvals import ApprovalBroker
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.evidence import EvidenceStore
from autodebug.facade import SCOPE_ARM, SCOPE_CONTINUE, SCOPE_STEP, AutoDebugFacade, target_identity_for
from autodebug.models import (
    ApprovalRecord,
    Breakpoint,
    CasePlan,
    CasePolicy,
    IntakeSource,
    ReproductionPlan,
    RootCauseConfidence,
    TargetRef,
)
from autodebug.plans import stage_plan
from autodebug.sessions import SessionRegistry
from tests.fixtures.fake_adapter import FakeAdapter
from tests.fixtures.fake_backend import FULL_SUPPORT


class BlockingStepAdapter(FakeAdapter):
    """A `FakeAdapter` whose `step()` blocks until released, used only to
    make a real race window observable deterministically in a test. No
    production code anywhere calls this; it exists solely to prove
    `autodebug_step` actually serializes per-session, not merely that
    `SessionRegistry.lease()` works in isolation (already covered by
    `test_sessions.py`)."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def step(self, session, kind):
        self.entered.set()
        self.release.wait(timeout=5.0)
        return super().step(session, kind)


class RaisingOnceStepAdapter(FakeAdapter):
    """Raises `AutoDebugError` from `step()` exactly once, then behaves
    normally -- used to prove the session lease is released even when the
    wrapped adapter call fails, not only on the happy path."""

    def __init__(self, error_code: ErrorCode = ErrorCode.BACKEND_UNAVAILABLE) -> None:
        super().__init__()
        self._raised = False
        self._error_code = error_code

    def step(self, session, kind):
        if not self._raised:
            self._raised = True
            raise AutoDebugError(
                ErrorDetail(code=self._error_code, message="simulated mid-step failure")
            )
        return super().step(session, kind)


class RaisingUnexpectedStepAdapter(FakeAdapter):
    """Raises an uncaught exception once, then succeeds, to prove the
    context-manager lease is released even when the facade propagates it."""

    def __init__(self) -> None:
        super().__init__()
        self._raised = False

    def step(self, session, kind):
        if not self._raised:
            self._raised = True
            raise RuntimeError("simulated unexpected adapter exception")
        return super().step(session, kind)


class DelayedSecondLeaseRegistry(SessionRegistry):
    """Pause the second caller immediately before lease acquisition so a
    first caller can consume the last approved step. This makes the
    check/acquire race deterministic without timing sleeps."""

    def __init__(self) -> None:
        super().__init__()
        self.second_lease_requested = threading.Event()
        self.allow_second_lease = threading.Event()
        self._lease_calls = 0
        self.delay_enabled = False
        self._lease_calls_lock = threading.Lock()

    def lease(self, session):
        with self._lease_calls_lock:
            self._lease_calls += 1
            lease_call = self._lease_calls
        if self.delay_enabled and lease_call == 2:
            self.second_lease_requested.set()
            if not self.allow_second_lease.wait(timeout=5.0):
                raise TimeoutError("test did not release the second lease attempt")
        return super().lease(session)


def make_broker(start_time: float = 3000.0):
    clock = {"t": start_time}
    tokens = iter(f"t15-token-{i}" for i in range(1, 10_000))
    return ApprovalBroker(now=lambda: clock["t"], make_token=lambda: next(tokens)), clock


class T15Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base_dir = Path(self._tmp.name)
        self.registry = SessionRegistry()
        self.broker, self.clock = make_broker()
        self.facade = AutoDebugFacade(
            registry=self.registry,
            broker=self.broker,
            evidence_base_dir=self.base_dir,
            now=lambda: self.clock["t"],
            sleep=lambda _s: None,
        )
        self.target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)

    def make_plan(self, case_id, target=None, max_steps=10):
        return stage_plan(
            CasePlan(
                schema_version="0.1-draft",
                case_id=case_id,
                source_revision="r1",
                target=target if target is not None else self.target,
                breakpoints=(Breakpoint(file="/x.py", line=1),),
                reproduction=ReproductionPlan(mode="manual", steps=("step",)),
                policy=CasePolicy(max_steps=max_steps, max_inspection_seconds=60),
                digest_sha256=None,
            )
        )

    def create_stage_approve_arm_pause(
        self,
        case_id,
        adapter,
        ttl_seconds=60.0,
        scope=(SCOPE_ARM, SCOPE_STEP, SCOPE_CONTINUE, "op:wait_for_stop", "op:get_stack", "op:get_variables"),
        target=None,
        max_steps=10,
    ):
        target = target if target is not None else self.target
        plan = self.make_plan(case_id, target=target, max_steps=max_steps)
        created = self.facade.autodebug_create_case(
            case_id=case_id,
            intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="T15 regression",
            adapter=adapter,
            target=target,
        )
        self.assertTrue(created["ok"], created)
        staged = self.facade.autodebug_stage_plan(case_id=case_id, plan=plan)
        self.assertTrue(staged["ok"], staged)
        digest = staged["result"]["digest_sha256"]
        plan_with_digest = replace(plan, digest_sha256=digest)
        approval = self.broker.issue_approval(
            plan_with_digest,
            reviewer="developer@example.com",
            backend_kind="fake",
            target_identity=target_identity_for(target),
            scope=scope,
            ttl_seconds=ttl_seconds,
            human_presence_confirmed=True,
        )
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        adapter.simulate_stop(session_id)
        waited = self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        self.assertTrue(waited["ok"], waited)
        return approval


class TestGW05SessionLeaseSerialization(T15Base):
    """GW-05: at most one mutating operation on a given session proceeds at
    a time; a second concurrent attempt is rejected, not queued or raced."""

    def test_concurrent_step_calls_on_the_same_session_are_serialized(self):
        case_id = "T15-GW05-STEP"
        adapter = BlockingStepAdapter()
        approval = self.create_stage_approve_arm_pause(case_id, adapter)

        results = {}

        def first_step():
            results["first"] = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")

        thread = threading.Thread(target=first_step)
        thread.start()
        self.assertTrue(adapter.entered.wait(timeout=5.0), "first step never entered the adapter")

        # A second step attempted while the first is still in-flight on the
        # same session must fail closed with POLICY_LIMIT, not block
        # silently and not race the adapter.
        second = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(second["ok"], second)
        self.assertEqual(second["error"]["code"], "POLICY_LIMIT")

        adapter.release.set()
        thread.join(timeout=5.0)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results["first"]["ok"], results["first"])
        self.assertEqual(results["first"]["result"]["steps_taken"], 1)

        # Once released, the session is free again -- the lease is not
        # permanently stuck after the first operation completes.
        third = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertTrue(third["ok"], third)
        self.assertEqual(third["result"]["steps_taken"], 2)

    def test_a_session_busy_with_step_also_rejects_a_concurrent_continue(self):
        """The lease is keyed per-session, not per-operation-type -- a
        session mid-`step` must also reject a concurrent `continue`."""
        case_id = "T15-GW05-CROSS-OP"
        adapter = BlockingStepAdapter()
        approval = self.create_stage_approve_arm_pause(case_id, adapter)

        thread = threading.Thread(
            target=lambda: self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        )
        thread.start()
        self.assertTrue(adapter.entered.wait(timeout=5.0))

        continued = self.facade.autodebug_continue(case_id=case_id, approval=approval)
        self.assertFalse(continued["ok"], continued)
        self.assertEqual(continued["error"]["code"], "POLICY_LIMIT")

        adapter.release.set()
        thread.join(timeout=5.0)

    def test_lease_is_released_even_when_the_adapter_raises(self):
        """The lease is acquired via a `with` block (`SessionLease.__exit__`
        always runs, success or exception) -- a failing adapter call must
        not leave the session permanently locked out of further
        operations."""
        case_id = "T15-GW05-RAISES"
        adapter = RaisingOnceStepAdapter()
        approval = self.create_stage_approve_arm_pause(case_id, adapter)

        failed = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(failed["ok"], failed)
        self.assertEqual(failed["error"]["code"], "BACKEND_UNAVAILABLE")
        self.assertEqual(self.facade._cases[case_id].steps_taken, 0)
        self.assertEqual(self.facade._cases[case_id].case.state.value, "incomplete")
        session = self.facade._cases[case_id].session
        with self.registry.lease(session):
            self.assertIn(session, self.registry.all_sessions())
        refused = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(refused["ok"], refused)

    def test_lease_is_released_when_adapter_reports_timeout_or_cancellation(self):
        for error_code in (ErrorCode.TIMEOUT, ErrorCode.CANCELLED):
            with self.subTest(error_code=error_code.value):
                case_id = f"T15-GW05-{error_code.value}"
                adapter = RaisingOnceStepAdapter(error_code=error_code)
                target = TargetRef(host_id=f"local-synthetic-{error_code.value}", ide="fake", debug_session_id=None, pid=None)
                approval = self.create_stage_approve_arm_pause(case_id, adapter, target=target)

                failed = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
                self.assertFalse(failed["ok"], failed)
                self.assertEqual(failed["error"]["code"], error_code.value)

                recovered = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
                self.assertFalse(recovered["ok"], recovered)
                self.assertEqual(self.facade._cases[case_id].case.state.value, "incomplete")
                with self.registry.lease(self.facade._cases[case_id].session):
                    self.assertEqual(self.facade._cases[case_id].steps_taken, 0)

    def test_lease_is_released_when_an_unexpected_exception_propagates(self):
        case_id = "T15-GW05-UNEXPECTED-EXCEPTION"
        adapter = RaisingUnexpectedStepAdapter()
        approval = self.create_stage_approve_arm_pause(case_id, adapter)

        failed = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(failed["ok"], failed)
        self.assertEqual(failed["error"]["code"], "BACKEND_UNAVAILABLE")
        self.assertNotIn("simulated unexpected adapter exception", failed["error"]["message"])

        recovered = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(recovered["ok"], recovered)
        self.assertEqual(self.facade._cases[case_id].case.state.value, "incomplete")
        with self.registry.lease(self.facade._cases[case_id].session):
            self.assertEqual(self.facade._cases[case_id].steps_taken, 0)

    def test_concurrent_steps_on_different_sessions_do_not_block_each_other(self):
        """The lease is keyed per-session (`host_id`, `ide`,
        `debug_session_id`) -- a session busy with `step` must never block
        an unrelated session's own `step`, proving no cross-session
        interference."""
        busy_case_id = "T15-GW05-CROSS-SESSION-BUSY"
        busy_adapter = BlockingStepAdapter()
        busy_approval = self.create_stage_approve_arm_pause(busy_case_id, busy_adapter)

        thread = threading.Thread(
            target=lambda: self.facade.autodebug_step(case_id=busy_case_id, approval=busy_approval, kind="step_over")
        )
        thread.start()
        self.assertTrue(busy_adapter.entered.wait(timeout=5.0), "busy session's step never entered the adapter")

        other_case_id = "T15-GW05-CROSS-SESSION-OTHER"
        other_adapter = FakeAdapter()
        # A distinct host_id guarantees a distinct SessionRegistry key even
        # though each FakeAdapter instance independently numbers its own
        # sessions starting at 1 -- without this, both "different" sessions
        # would collide on the same (host_id, ide, debug_session_id) key and
        # this test would not actually exercise cross-session independence.
        other_target = TargetRef(host_id="local-mac-2", ide="fake", debug_session_id=None, pid=None)
        other_approval = self.create_stage_approve_arm_pause(other_case_id, other_adapter, target=other_target)

        # The other session's own step must succeed immediately -- it must
        # not wait for the busy session's lease to be released.
        other_result = self.facade.autodebug_step(case_id=other_case_id, approval=other_approval, kind="step_over")
        self.assertTrue(other_result["ok"], other_result)
        self.assertEqual(other_result["result"]["steps_taken"], 1)

        busy_adapter.release.set()
        thread.join(timeout=5.0)
        self.assertFalse(thread.is_alive())

    def test_step_budget_is_checked_after_acquiring_the_session_lease(self):
        case_id = "T15-GW05-BUDGET-RACE"
        adapter = BlockingStepAdapter()
        registry = DelayedSecondLeaseRegistry()
        self.registry = registry
        self.facade = AutoDebugFacade(
            registry=registry,
            broker=self.broker,
            evidence_base_dir=self.base_dir,
            now=lambda: self.clock["t"],
            sleep=lambda _s: None,
        )
        approval = self.create_stage_approve_arm_pause(case_id, adapter, max_steps=1)
        registry._lease_calls = 0
        registry.delay_enabled = True
        results = {}

        first = threading.Thread(
            target=lambda: results.setdefault(
                "first", self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
            )
        )
        first.start()
        self.assertTrue(adapter.entered.wait(timeout=5.0), "first step never entered the adapter")

        second = threading.Thread(
            target=lambda: results.setdefault(
                "second", self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
            )
        )
        second.start()
        self.assertTrue(registry.second_lease_requested.wait(timeout=5.0))

        adapter.release.set()
        first.join(timeout=5.0)
        self.assertFalse(first.is_alive())
        registry.allow_second_lease.set()
        second.join(timeout=5.0)

        self.assertFalse(second.is_alive())
        self.assertTrue(results["first"]["ok"], results["first"])
        self.assertFalse(results["second"]["ok"], results["second"])
        self.assertEqual(results["second"]["error"]["code"], "POLICY_LIMIT")
        self.assertEqual(self.facade._cases[case_id].steps_taken, 1)


class TestDE08ApprovalExpirationDuringInvestigation(T15Base):
    """DE-08: approval expiration discovered mid-investigation is a
    recovery trigger, not a bare refusal -- the case must be labeled
    INCOMPLETE and partial evidence preserved, mirroring the existing
    SESSION_STALE handling."""

    def test_expired_approval_during_step_marks_case_incomplete_and_preserves_evidence(self):
        case_id = "T15-DE08-EXPIRED-STEP"
        adapter = FakeAdapter()
        approval = self.create_stage_approve_arm_pause(case_id, adapter, ttl_seconds=10.0)

        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)
        evidence_before = self.facade._cases[case_id].evidence_store.read_events()
        self.assertTrue(evidence_before)

        self.clock["t"] += 11.0  # past the 10s ttl_seconds

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"], stepped)
        self.assertEqual(stepped["error"]["code"], "APPROVAL_EXPIRED")

        ctx = self.facade._cases[case_id]
        self.assertEqual(ctx.case.state.value, "incomplete")

        case_json = (self.base_dir / case_id / "case.json").read_text()
        self.assertIn('"incomplete"', case_json)

        evidence_after = self.facade._cases[case_id].evidence_store.read_events()
        self.assertEqual(evidence_before, evidence_after, "DE-08: partial evidence must be preserved on expiration")

    def test_expired_approval_during_continue_marks_case_incomplete(self):
        case_id = "T15-DE08-EXPIRED-CONTINUE"
        adapter = FakeAdapter()
        approval = self.create_stage_approve_arm_pause(case_id, adapter, ttl_seconds=10.0)
        self.clock["t"] += 11.0

        resumed = self.facade.autodebug_continue(case_id=case_id, approval=approval)
        self.assertFalse(resumed["ok"], resumed)
        self.assertEqual(resumed["error"]["code"], "APPROVAL_EXPIRED")
        self.assertEqual(self.facade._cases[case_id].case.state.value, "incomplete")

    def test_approval_expiration_at_arm_time_is_unaffected_no_case_or_evidence_exists_yet(self):
        """The new `_verify_approval` incomplete-labeling helper is used
        only by `autodebug_step`/`autodebug_continue` -- `autodebug_arm_case`
        still calls `authorize_and_arm` directly and is unchanged: there is
        no session or evidence yet at arm time, so "incomplete" would be
        meaningless."""
        case_id = "T15-DE08-EXPIRED-AT-ARM"
        adapter = FakeAdapter()
        plan = self.make_plan(case_id)
        self.facade.autodebug_create_case(
            case_id=case_id,
            intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="d",
            adapter=adapter,
            target=self.target,
        )
        staged = self.facade.autodebug_stage_plan(case_id=case_id, plan=plan)
        digest = staged["result"]["digest_sha256"]
        plan_with_digest = replace(plan, digest_sha256=digest)
        approval = self.broker.issue_approval(
            plan_with_digest,
            reviewer="dev@example.com",
            backend_kind="fake",
            target_identity=target_identity_for(self.target),
            scope=(SCOPE_ARM, SCOPE_STEP, SCOPE_CONTINUE),
            ttl_seconds=10.0,
            human_presence_confirmed=True,
        )
        self.clock["t"] += 11.0
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertFalse(armed["ok"], armed)
        self.assertEqual(armed["error"]["code"], "APPROVAL_EXPIRED")
        self.assertEqual(adapter.launch_or_attach_calls, 0)
        ctx = self.facade._cases[case_id]
        self.assertEqual(ctx.case.state.value, "awaiting_approval", "pre-arm expiration must not fabricate an INCOMPLETE case")

    def test_a_scope_denied_step_does_not_mark_the_case_incomplete(self):
        """Only APPROVAL_EXPIRED triggers the DE-08 recovery path --
        PERMISSION_DENIED (a trust/authorization failure, not a recovery
        condition) must never mark a valid case incomplete."""
        case_id = "T15-DE08-SCOPE-DENIED-NOT-INCOMPLETE"
        adapter = FakeAdapter()
        approval = self.create_stage_approve_arm_pause(case_id, adapter, scope=(SCOPE_ARM, "op:wait_for_stop", "op:get_variables"))

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"], stepped)
        self.assertEqual(stepped["error"]["code"], "PERMISSION_DENIED")
        self.assertEqual(self.facade._cases[case_id].case.state.value, "paused")

    def test_a_forged_approval_does_not_mark_the_case_incomplete(self):
        """`NOT_APPROVED` (a forged/never-issued token -- an attack, not an
        interruption) must never mark a valid case incomplete, exactly like
        `PERMISSION_DENIED` above. `_verify_approval`'s recovery path is
        keyed to the exact `APPROVAL_EXPIRED` code, not "any verify_approval
        failure"."""
        case_id = "T15-DE08-FORGED-NOT-INCOMPLETE"
        adapter = FakeAdapter()
        self.create_stage_approve_arm_pause(case_id, adapter)

        forged = ApprovalRecord(
            case_id=case_id,
            plan_digest="forged-digest",
            reviewer="attacker@example.com",
            expiration="999999999999",
            scope=(SCOPE_ARM, SCOPE_STEP, SCOPE_CONTINUE),
            token="never-issued-by-this-broker",
        )
        stepped = self.facade.autodebug_step(case_id=case_id, approval=forged, kind="step_over")
        self.assertFalse(stepped["ok"], stepped)
        self.assertEqual(stepped["error"]["code"], "NOT_APPROVED")
        self.assertEqual(self.facade._cases[case_id].case.state.value, "paused")

    def test_expiration_handling_is_idempotent_across_repeated_calls(self):
        """A second privileged call against an already-`INCOMPLETE` case
        (caused by the first expiration) must not crash, re-raise a
        confusing second `APPROVAL_EXPIRED`, or corrupt/duplicate evidence
        -- it fails closed with `NOT_PAUSED` from the ordinary case-state
        gate, which runs before `_verify_approval` is ever reached again."""
        case_id = "T15-DE08-EXPIRED-IDEMPOTENT"
        adapter = FakeAdapter()
        approval = self.create_stage_approve_arm_pause(case_id, adapter, ttl_seconds=10.0)
        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)
        evidence_before = self.facade._cases[case_id].evidence_store.read_events()

        self.clock["t"] += 11.0

        first = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(first["ok"], first)
        self.assertEqual(first["error"]["code"], "APPROVAL_EXPIRED")
        case_json_after_first = (self.base_dir / case_id / "case.json").read_text()

        second = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(second["ok"], second)
        self.assertEqual(second["error"]["code"], "NOT_PAUSED")

        third = self.facade.autodebug_continue(case_id=case_id, approval=approval)
        self.assertFalse(third["ok"], third)
        self.assertEqual(third["error"]["code"], "NOT_PAUSED")

        case_json_after_repeats = (self.base_dir / case_id / "case.json").read_text()
        self.assertEqual(case_json_after_first, case_json_after_repeats)
        evidence_after = self.facade._cases[case_id].evidence_store.read_events()
        self.assertEqual(evidence_before, evidence_after)
        self.assertEqual(self.facade._cases[case_id].steps_taken, 0)


class TestDE06EvidenceIdIntegrity(T15Base):
    """DE-06: "Every conclusion SHALL cite stored evidence IDs" is now
    structurally enforced -- a caller cannot complete a case citing an
    evidence ID that was never actually recorded by
    `EvidenceStore.record_evidence`, whether fabricated outright or copied
    from a different case."""

    def test_a_fabricated_evidence_id_is_rejected(self):
        case_id = "T15-DE06-FABRICATED"
        adapter = FakeAdapter()
        self.create_stage_approve_arm_pause(case_id, adapter)
        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)

        result = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="local_var was unexpectedly null",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=("E9999",),  # never recorded for this case
            reproduced=True,
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
        self.assertIn("E9999", result["error"]["message"])
        # The case is not left finalized or otherwise corrupted by the
        # rejected attempt -- it remains inspecting, completable once a
        # real evidence ID is cited.
        self.assertEqual(self.facade._cases[case_id].case.state.value, "inspecting")

    def test_confirmed_report_with_fabricated_evidence_is_rejected_even_with_causal_validation(self):
        case_id = "T15-DE06-CONFIRMED-FABRICATED"
        adapter = FakeAdapter()
        self.create_stage_approve_arm_pause(case_id, adapter)
        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)

        result = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="the missing check caused the failure",
            confidence=RootCauseConfidence.CONFIRMED,
            evidence_ids=("E9999",),
            reproduced=True,
            causal_validation="a controlled rerun passed with the fix",
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
        self.assertIn("E9999", result["error"]["message"])
        self.assertEqual(self.facade._cases[case_id].case.state.value, "inspecting")

    def test_a_real_evidence_id_from_a_different_case_is_rejected(self):
        """An evidence ID that genuinely exists -- just not for *this*
        case -- must be refused exactly like an outright fabrication; each
        case's `EvidenceStore` is scoped to its own `case_id` directory.
        `evidence_id` values are per-case sequential counters (both cases'
        first record is "E0001"), so the other case is given a *second*
        observation ("E0002") that this case never records, to construct an
        ID that is genuinely real somewhere, but not for this case."""
        other_case_id = "T15-DE06-OTHER-CASE"
        adapter_other = FakeAdapter()
        self.create_stage_approve_arm_pause(other_case_id, adapter_other)
        other_variables = self.facade.autodebug_get_variables(
            case_id=other_case_id, frame_id="f0", selected_names=("local_var", "password")
        )
        self.assertTrue(other_variables["ok"], other_variables)
        other_case_events = self.facade._cases[other_case_id].evidence_store.read_events()
        self.assertEqual(len(other_case_events), 3)
        self.assertEqual(other_case_events[0].event_type, "stop_observed")
        real_id_only_in_other_case = other_case_events[2].evidence_id

        case_id = "T15-DE06-CROSS-CASE"
        adapter = FakeAdapter()
        target = TargetRef(host_id="local-synthetic-other-case", ide="fake", debug_session_id=None, pid=None)
        self.create_stage_approve_arm_pause(case_id, adapter, target=target)
        # This case records only one observation, so it only ever has
        # "E0001" -- "E0002" is real, but only in the other case above.
        this_case_variables = self.facade.autodebug_get_variables(
            case_id=case_id, frame_id="f0", selected_names=("local_var",)
        )
        self.assertTrue(this_case_variables["ok"], this_case_variables)
        self.assertEqual(len(self.facade._cases[case_id].evidence_store.read_events()), 2)

        result = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="local_var was unexpectedly null",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=(real_id_only_in_other_case,),
            reproduced=True,
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")

    def test_evidence_record_with_another_case_id_is_rejected(self):
        case_id = "T15-DE06-FOREIGN-RECORD"
        adapter = FakeAdapter()
        self.create_stage_approve_arm_pause(case_id, adapter)
        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)

        events_path = self.base_dir / case_id / "events.jsonl"
        record = json.loads(events_path.read_text().splitlines()[0])
        record["case_id"] = "T15-DE06-OTHER-CASE"
        events_path.write_text(json.dumps(record) + "\n")

        result = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="local_var was unexpectedly null",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=("E0001",),
            reproduced=True,
        )
        self.assertFalse(result["ok"], result)
        self.assertIn("E0001", result["error"]["message"])

    def test_malformed_evidence_id_input_is_rejected(self):
        case_id = "T15-DE06-MALFORMED"
        adapter = FakeAdapter()
        self.create_stage_approve_arm_pause(case_id, adapter)
        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)

        result = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="local_var was unexpectedly null",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=("E0001", []),
            reproduced=True,
        )
        self.assertFalse(result["ok"], result)
        self.assertIn("tuple of strings", result["error"]["message"])

    def test_a_genuinely_recorded_evidence_id_is_accepted(self):
        """Positive control: the new check does not reject legitimate
        citations -- only unrecorded ones."""
        case_id = "T15-DE06-GENUINE"
        adapter = FakeAdapter()
        self.create_stage_approve_arm_pause(case_id, adapter)
        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)
        real_id = self.facade._cases[case_id].evidence_store.read_events()[0].evidence_id

        result = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="local_var was unexpectedly null",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=(real_id,),
            reproduced=True,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["state"], "finalized")

    def test_case_id_cannot_escape_the_evidence_base_directory(self):
        case_id = "../another-case"
        result = self.facade.autodebug_create_case(
            case_id=case_id,
            intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="T15 path-boundary regression",
            adapter=FakeAdapter(),
            target=self.target,
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn(case_id, self.facade._cases)
        with self.assertRaisesRegex(ValueError, "single path component"):
            EvidenceStore(self.base_dir, case_id)

    def test_case_directory_symlink_cannot_alias_another_case(self):
        existing = EvidenceStore(self.base_dir, "T15-DE06-EXISTING")
        alias = self.base_dir / "T15-DE06-ALIAS"
        alias.symlink_to(existing.case_dir, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "already exists"):
            EvidenceStore(self.base_dir, "T15-DE06-ALIAS")
