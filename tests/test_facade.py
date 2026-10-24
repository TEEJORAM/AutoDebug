"""T07 acceptance tests — MCP tool facade and fake end-to-end (GW-01, GW-06,
RP-04, DE-01, DE-03, DE-09). Stdlib `unittest` only, zero third-party
packages, no MCP SDK — the facade under test has none either.

These tests exercise `src/autodebug/facade.py` entirely against the fake
backend fixtures (`FakeAdapter`, `FULL_SUPPORT`). They do not, and cannot,
prove the T05 security gate is closed for a real debugger — that remains
OPEN / NOT APPROVED; `verify_approval`'s `backend_kind != "fake"` refusal
(tested in `test_approvals.py`) is unchanged by this module.
"""

import inspect
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from autodebug import facade as facade_module
from autodebug.adapters import VSCodeAdapter
from autodebug.approvals import ApprovalBroker
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.evidence import REDACTED_PLACEHOLDER
from autodebug.facade import SCOPE_ARM, SCOPE_CONTINUE, SCOPE_STEP, AutoDebugFacade, target_identity_for
from autodebug.models import (
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


def make_plan(**overrides) -> CasePlan:
    defaults = dict(
        schema_version="0.1-draft",
        case_id="CASE-2026-T07",
        source_revision="abc123",
        target=TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None),
        breakpoints=(Breakpoint(file="/repo/src/file.cpp", line=42),),
        reproduction=ReproductionPlan(mode="manual", steps=("Open a disposable design", "Invoke command X")),
        policy=CasePolicy(max_steps=2, max_inspection_seconds=300),
        digest_sha256=None,
    )
    defaults.update(overrides)
    return stage_plan(CasePlan(**defaults))


def make_broker(start_time: float = 1000.0):
    clock = {"t": start_time}
    tokens = iter(f"token-{i}" for i in range(1, 10_000))

    def now():
        return clock["t"]

    def make_token():
        return next(tokens)

    return ApprovalBroker(now=now, make_token=make_token), clock


class FacadeTestBase(unittest.TestCase):
    """Shared fixture wiring: a fresh facade + a staged, approved plan ready
    to arm, per test, each against its own temp evidence directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.registry = SessionRegistry()
        self.broker, self.clock = make_broker()
        self.facade = AutoDebugFacade(
            registry=self.registry,
            broker=self.broker,
            evidence_base_dir=Path(self._tmp.name),
            now=lambda: self.clock["t"],
            sleep=lambda _seconds: None,
        )
        self.adapter = FakeAdapter()
        self.target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)

    def create_and_stage(self, case_id="CASE-2026-T07", adapter=None, target=None, plan=None):
        adapter = adapter if adapter is not None else self.adapter
        target = target if target is not None else self.target
        plan = plan if plan is not None else make_plan(case_id=case_id, target=target)
        result = self.facade.autodebug_create_case(
            case_id=case_id,
            intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="disposable repro",
            adapter=adapter,
            target=target,
        )
        self.assertTrue(result["ok"], result)
        staged = self.facade.autodebug_stage_plan(case_id=case_id, plan=plan)
        self.assertTrue(staged["ok"], staged)
        return staged["result"]["digest_sha256"]

    def issue_approval(self, case_id, digest, target, scope=(SCOPE_ARM, SCOPE_STEP, SCOPE_CONTINUE, "op:wait_for_stop", "op:get_stack", "op:get_variables"), backend_kind="fake"):
        plan_with_digest = replace(self.facade._cases[case_id].case.plan, digest_sha256=digest)
        return self.broker.issue_approval(
            plan_with_digest,
            reviewer="developer@example.com",
            backend_kind=backend_kind,
            target_identity=target_identity_for(target),
            scope=scope,
            ttl_seconds=60.0,
            human_presence_confirmed=True,
        )


class TestFakeEndToEndHappyPath(FacadeTestBase):
    """GW-06-A (launch): no prior session, adapter supports launch_or_attach."""

    def test_full_case_lifecycle_against_fake_backend(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)

        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertTrue(armed["ok"], armed)
        self.assertEqual(armed["result"]["state"], "awaiting_developer_reproduction")
        self.assertEqual(self.adapter.launch_or_attach_calls, 1)

        session_id = armed["result"]["session"]["debug_session_id"]
        self.adapter.simulate_stop(session_id)

        waited = self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        self.assertTrue(waited["ok"], waited)
        self.assertEqual(waited["result"]["state"], "paused")

        stack = self.facade.autodebug_get_stack(case_id=case_id, frame_limit=3)
        self.assertTrue(stack["ok"], stack)
        self.assertEqual(len(stack["result"]["frames"]), 3)

        variables = self.facade.autodebug_get_variables(
            case_id=case_id, frame_id="frame-0", selected_names=("local_var", "password")
        )
        self.assertTrue(variables["ok"], variables)
        self.assertEqual(variables["result"]["variables"]["local_var"], "42")
        self.assertEqual(variables["result"]["variables"]["password"], REDACTED_PLACEHOLDER)

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertTrue(stepped["ok"], stepped)
        self.assertEqual(stepped["result"]["steps_taken"], 1)

        resumed = self.facade.autodebug_continue(case_id=case_id, approval=approval)
        self.assertTrue(resumed["ok"], resumed)

        completed = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="Null local_var under condition X",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=("E0001",),
            reproduced=True,
        )
        self.assertTrue(completed["ok"], completed)
        self.assertEqual(completed["result"]["state"], "finalized")

        report_path = Path(self._tmp.name) / case_id / "report.md"
        self.assertTrue(report_path.exists())

    def test_secret_variable_never_reaches_disk_unredacted(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        session_id = armed["result"]["session"]["debug_session_id"]
        self.adapter.simulate_stop(session_id)
        self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        self.facade.autodebug_get_variables(case_id=case_id, frame_id="frame-0", selected_names=("password",))

        events_path = Path(self._tmp.name) / case_id / "events.jsonl"
        raw_bytes = events_path.read_bytes()
        self.assertNotIn(b"hunter2", raw_bytes)


class TestGW06Scenarios(FacadeTestBase):
    def test_attach_to_running_process(self):
        """GW-06-B: process already running, no existing session."""
        case_id = "CASE-2026-ATTACH"
        digest = self.create_and_stage(case_id, plan=make_plan(case_id=case_id, process_running=True))
        approval = self.issue_approval(case_id, digest, self.target)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=True,
        )
        self.assertTrue(armed["ok"], armed)
        self.assertEqual(self.adapter.launch_or_attach_calls, 1)

    def test_existing_session_is_reused_not_relaunched(self):
        """GW-06-C: a session already registered for this target wins."""
        case_id = "CASE-2026-REUSE"
        digest = self.create_and_stage(case_id, plan=make_plan(case_id=case_id, process_running=True))
        existing = self.adapter.launch_or_attach(self.target, None)
        self.registry.register(existing)
        self.assertEqual(self.adapter.launch_or_attach_calls, 1)

        approval = self.issue_approval(case_id, digest, self.target)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=True,
        )
        self.assertTrue(armed["ok"], armed)
        self.assertEqual(armed["result"]["session"]["debug_session_id"], existing.debug_session_id)
        # Reused, not relaunched — still exactly the one call from above.
        self.assertEqual(self.adapter.launch_or_attach_calls, 1)

    def test_decline_when_adapter_does_not_support_launch_or_attach(self):
        """GW-06-D: capability report marks launch_or_attach unsupported."""
        case_id = "CASE-2026-DECLINE"
        unsupported_adapter = FakeAdapter(can_launch_or_attach=False)
        digest = self.create_and_stage(case_id, adapter=unsupported_adapter)
        approval = self.issue_approval(case_id, digest, self.target)

        from autodebug.adapters.base import CORE_OPERATIONS
        from tests.fixtures.fake_backend import FakeBackend

        no_launch_support = FakeBackend(
            supported_operations=frozenset(CORE_OPERATIONS) - {"launch_or_attach"}
        )
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=unsupported_adapter.probe_capabilities(no_launch_support),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertFalse(armed["ok"])
        self.assertEqual(armed["error"]["code"], "CAPABILITY_UNSUPPORTED")
        self.assertEqual(unsupported_adapter.launch_or_attach_calls, 0)


class TestUnauthorizedAndSecurityBoundaries(FacadeTestBase):
    def test_arm_case_without_any_approval_is_rejected(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        forged = self.broker.issue_approval(
            replace(make_plan(case_id=case_id, target=self.target), digest_sha256=digest),
            reviewer="developer@example.com",
            backend_kind="fake",
            target_identity=target_identity_for(self.target),
            scope=(SCOPE_ARM,),
            ttl_seconds=60.0,
            human_presence_confirmed=True,
        )
        self.broker.revoke(forged.token)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=forged,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertFalse(armed["ok"])
        self.assertEqual(armed["error"]["code"], "CANCELLED")
        self.assertEqual(self.adapter.launch_or_attach_calls, 0)

    def test_arm_case_with_wrong_scope_is_rejected(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target, scope=(SCOPE_STEP,))  # missing SCOPE_ARM
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertFalse(armed["ok"])
        self.assertEqual(armed["error"]["code"], "PERMISSION_DENIED")
        self.assertEqual(self.adapter.launch_or_attach_calls, 0)

    def test_step_without_approval_scope_is_rejected(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target, scope=(SCOPE_ARM, "op:wait_for_stop"))  # no SCOPE_STEP
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        self.adapter.simulate_stop(session_id)
        self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"])
        self.assertEqual(stepped["error"]["code"], "PERMISSION_DENIED")

    def test_facade_never_issues_its_own_approvals(self):
        """Structural guard: the facade module must never call
        `issue_approval` — approval issuance must come from a separate
        trusted process, never from agent-reachable tool code."""
        source = inspect.getsource(facade_module)
        self.assertNotIn(".issue_approval(", source)

    def test_facade_never_calls_bare_router_arm_target(self):
        """Structural guard: every privileged arm path must go through
        `authorize_and_arm`, never `Router.arm_target` directly."""
        source = inspect.getsource(facade_module.AutoDebugFacade.autodebug_arm_case)
        self.assertNotIn("self._router.arm_target(", source)
        self.assertNotIn("router.arm_target(", source)
        full_source = inspect.getsource(facade_module)
        self.assertIn("authorize_and_arm(", full_source)

    def test_real_adapter_backend_kind_still_refused_through_the_facade(self):
        """Defense in depth: even if a caller wired a real adapter into a
        case context, the facade's arm path still goes through
        `authorize_and_arm`, which still refuses any backend_kind != fake."""
        case_id = "CASE-2026-REAL"
        real_adapter = VSCodeAdapter()
        real_target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)
        digest = self.create_and_stage(case_id, adapter=real_adapter, target=real_target)
        approval = self.issue_approval(case_id, digest, real_target, backend_kind="fake")
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=real_adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertFalse(armed["ok"])
        # The approval's scope was issued for "backend:fake", but
        # `authorize_and_arm` derives the real check from `adapter.ide_id`
        # ("vscode") — the scope-match layer (RP-05-C) catches the mismatch
        # before the unconditional real-backend refusal is even reached.
        self.assertEqual(armed["error"]["code"], "TARGET_MISMATCH")
        self.assertEqual(self.registry.all_sessions(), ())

    def test_expired_approval_is_rejected_at_arm_time(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)
        self.clock["t"] += 61.0  # ttl_seconds was 60.0 in issue_approval
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertFalse(armed["ok"])
        self.assertEqual(armed["error"]["code"], "APPROVAL_EXPIRED")
        self.assertEqual(self.adapter.launch_or_attach_calls, 0)


class TestStaleSessionIdentity(FacadeTestBase):
    """GW-03-B, re-applied at the facade layer: every operation on a live
    session — not just `autodebug_wait_for_stop` — must re-verify PID,
    generation, and IDE instance identity before touching the adapter."""

    def _arm_and_pause(self, case_id="CASE-2026-T07"):
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        self.adapter.simulate_stop(session_id)
        waited = self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        self.assertTrue(waited["ok"], waited)
        return approval

    def test_exited_session_blocks_get_stack_get_variables_step_and_continue(self):
        # DE-08 (T14): the *first* detected disconnect labels the case
        # INCOMPLETE and finalizes partial evidence — "stop additional
        # privileged actions ... label the case incomplete." Once that has
        # happened, `autodebug_step`/`autodebug_continue` correctly fail
        # with NOT_PAUSED (the case is no longer in a privileged-operable
        # state at all), not a second SESSION_STALE — a stronger guarantee
        # than before, not a weaker one. `get_stack`/`get_variables` check
        # session identity before case state, so they still report
        # SESSION_STALE directly even after the case becomes INCOMPLETE.
        case_id = "CASE-2026-T07"
        approval = self._arm_and_pause(case_id)
        ctx = self.facade._cases[case_id]
        self.registry.unregister(ctx.session)  # simulates the process/session exiting

        stack = self.facade.autodebug_get_stack(case_id=case_id, frame_limit=1)
        self.assertFalse(stack["ok"])
        self.assertEqual(stack["error"]["code"], "SESSION_STALE")
        self.assertEqual(ctx.case.state.value, "incomplete", "DE-08: first disconnect must label the case incomplete")

        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
        self.assertFalse(variables["ok"])
        self.assertEqual(variables["error"]["code"], "SESSION_STALE")

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"])
        self.assertEqual(stepped["error"]["code"], "NOT_PAUSED")

        resumed = self.facade.autodebug_continue(case_id=case_id, approval=approval)
        self.assertFalse(resumed["ok"])
        self.assertEqual(resumed["error"]["code"], "NOT_PAUSED")

        case_json = json.loads((Path(self._tmp.name) / case_id / "case.json").read_text())
        self.assertEqual(case_json["state"], "incomplete")

    def test_reassigned_session_identity_blocks_step(self):
        """A PID reused by a different process (or a bumped generation)
        after the session was armed must fail closed, not silently operate
        on the wrong process."""
        case_id = "CASE-2026-T07"
        approval = self._arm_and_pause(case_id)
        ctx = self.facade._cases[case_id]
        reassigned = replace(ctx.session, session_generation=ctx.session.session_generation + 1)
        self.registry.register(reassigned)  # same key, different identity fields

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"])
        self.assertEqual(stepped["error"]["code"], "TARGET_MISMATCH")
        # T14 security review: TARGET_MISMATCH is a reused/reassigned
        # identity, a security concern distinct from DE-08's disconnect
        # trigger -- it must never mark the case INCOMPLETE.
        self.assertEqual(ctx.case.state.value, "paused")


class TestBreakpointBindingFailureRollback(FacadeTestBase):
    """RP-06 / `BREAKPOINT_UNBOUND`: a failed bind must not leave a live,
    registered, still-authorized session with no owning case able to use
    or clean it up."""

    def test_failed_binding_disconnects_unregisters_and_revokes(self):
        case_id = "CASE-2026-T07"
        adapter = FakeAdapter(can_bind_breakpoints=False)
        digest = self.create_and_stage(case_id, adapter=adapter)
        approval = self.issue_approval(case_id, digest, self.target)

        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertFalse(armed["ok"])
        self.assertEqual(armed["error"]["code"], "BREAKPOINT_UNBOUND")

        # The session must not be left live/registered...
        self.assertEqual(self.registry.all_sessions(), ())
        self.assertEqual(adapter.disconnect_calls, 1)

        # ...the case must be moved to a terminal state, not left stuck...
        ctx = self.facade._cases[case_id]
        self.assertEqual(ctx.case.state.value, "failed")
        self.assertIsNone(ctx.session)

        # ...and the approval must no longer be usable.
        with self.assertRaises(AutoDebugError) as broker_ctx:
            self.broker.verify_approval(
                approval,
                plan=make_plan(case_id=case_id, target=self.target),
                backend_kind="fake",
                target_identity=target_identity_for(self.target),
                required_scope=SCOPE_ARM,
            )
        self.assertEqual(broker_ctx.exception.detail.code, ErrorCode.CANCELLED)

    def test_failed_binding_does_not_affect_other_cases(self):
        case_id_a = "CASE-2026-FAIL"
        case_id_b = "CASE-2026-OK"
        failing_adapter = FakeAdapter(can_bind_breakpoints=False)
        target_a = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)
        target_b = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=4242)

        digest_a = self.create_and_stage(case_id_a, adapter=failing_adapter, target=target_a)
        approval_a = self.issue_approval(case_id_a, digest_a, target_a)
        self.facade.autodebug_arm_case(
            case_id=case_id_a,
            approval=approval_a,
            capability_report=failing_adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )

        digest_b = self.create_and_stage(case_id_b, adapter=self.adapter, target=target_b)
        approval_b = self.issue_approval(case_id_b, digest_b, target_b)
        armed_b = self.facade.autodebug_arm_case(
            case_id=case_id_b,
            approval=approval_b,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertTrue(armed_b["ok"], armed_b)
        self.assertEqual(len(self.registry.all_sessions()), 1)


class TestCancellationAndBudgets(FacadeTestBase):
    def test_timeout_when_never_paused(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertTrue(armed["ok"], armed)

        ticks = iter([0.0, 0.1, 0.2, 0.3])

        def fake_now():
            return next(ticks, 999.0)

        self.facade._now = fake_now
        result = self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=0.25)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "TIMEOUT")

    def test_cancellation_mid_wait_returns_cancelled_promptly(self):
        case_id = "CASE-2026-T07"
        registry = SessionRegistry()
        broker, _clock = make_broker()
        import time as real_time

        facade = AutoDebugFacade(
            registry=registry,
            broker=broker,
            evidence_base_dir=Path(self._tmp.name),
            now=real_time.monotonic,
            sleep=real_time.sleep,
            poll_interval=0.01,
        )
        adapter = FakeAdapter()
        target = self.target
        plan = make_plan(case_id=case_id, target=target)
        facade.autodebug_create_case(
            case_id=case_id,
            intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="cancellation test",
            adapter=adapter,
            target=target,
        )
        staged = facade.autodebug_stage_plan(case_id=case_id, plan=plan)
        digest = staged["result"]["digest_sha256"]
        plan_with_digest = replace(plan, digest_sha256=digest)
        approval = broker.issue_approval(
            plan_with_digest,
            reviewer="developer@example.com",
            backend_kind="fake",
            target_identity=target_identity_for(target),
            scope=(SCOPE_ARM, "op:wait_for_stop"),
            ttl_seconds=60.0,
            human_presence_confirmed=True,
        )
        armed = facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertTrue(armed["ok"], armed)

        outcome = {}

        def run_wait():
            outcome["result"] = facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=10.0)

        thread = threading.Thread(target=run_wait)
        thread.start()
        real_time.sleep(0.05)
        cancelled = facade.autodebug_cancel_case(case_id=case_id)
        self.assertTrue(cancelled["ok"], cancelled)
        self.assertEqual(cancelled["result"]["state"], "cancelled")
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive(), "wait_for_stop did not return promptly after cancellation")
        self.assertFalse(outcome["result"]["ok"])
        self.assertEqual(outcome["result"]["error"]["code"], "CANCELLED")

    def test_cancel_case_is_idempotent(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)
        self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        first = self.facade.autodebug_cancel_case(case_id=case_id)
        second = self.facade.autodebug_cancel_case(case_id=case_id)
        self.assertTrue(first["ok"], first)
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["result"]["state"], "cancelled")

    def test_cancel_case_revokes_approval_so_it_cannot_step_afterward(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        session_id = armed["result"]["session"]["debug_session_id"]
        self.adapter.simulate_stop(session_id)
        self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        self.facade.autodebug_cancel_case(case_id=case_id)

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"])
        # The case itself is terminal (`cancelled`) by the time `step` runs,
        # so the state-precondition check fires first (NOT_PAUSED) — the
        # broker-level revocation is verified directly below.
        self.assertEqual(stepped["error"]["code"], "NOT_PAUSED")

        with self.assertRaises(AutoDebugError) as broker_ctx:
            self.broker.verify_approval(
                approval,
                plan=make_plan(case_id=case_id, target=self.target),
                backend_kind="fake",
                target_identity=target_identity_for(self.target),
                required_scope=SCOPE_STEP,
            )
        self.assertEqual(broker_ctx.exception.detail.code, ErrorCode.CANCELLED)

    def test_step_budget_enforced_de03(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)  # policy.max_steps == 2
        approval = self.issue_approval(case_id, digest, self.target)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        session_id = armed["result"]["session"]["debug_session_id"]
        self.adapter.simulate_stop(session_id)
        self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)

        self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        third = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(third["ok"])
        self.assertEqual(third["error"]["code"], "POLICY_LIMIT")

    def test_revised_plan_invalidates_a_stale_approval_at_arm_time(self):
        """RP-05: a plan change after an approval was issued, but before
        arming, must invalidate that approval — proven through the facade's
        own `autodebug_arm_case`, not just at the lower `approvals.py`
        layer directly."""
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)

        ctx = self.facade._cases[case_id]
        ctx.case.mark_approved(digest)
        revised_plan = make_plan(
            case_id=case_id,
            target=self.target,
            reproduction=ReproductionPlan(mode="manual", steps=("A different repro step",)),
        )
        ctx.case.revise_plan(revised_plan)

        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertFalse(armed["ok"])
        self.assertEqual(armed["error"]["code"], "PLAN_CHANGED")
        self.assertEqual(self.adapter.launch_or_attach_calls, 0)


class TestReadOnlyTools(FacadeTestBase):
    def test_health(self):
        result = self.facade.autodebug_health()
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["security_gate"], "OPEN / NOT APPROVED — real debugger control is disabled")

    def test_probe_adapters(self):
        result = self.facade.autodebug_probe_adapters(adapters=[(self.adapter, FULL_SUPPORT, None)])
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["adapters"][0]["ide"], "fake")
        self.assertEqual(result["result"]["adapters"][0]["state"], "available")

    def test_list_sessions_reflects_registry(self):
        session = self.adapter.launch_or_attach(self.target, None)
        self.registry.register(session)
        result = self.facade.autodebug_list_sessions()
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["result"]["sessions"]), 1)

    def test_get_plan_before_staging_fails_closed(self):
        self.facade.autodebug_create_case(
            case_id="CASE-2026-NOPLAN",
            intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="no plan yet",
            adapter=self.adapter,
            target=self.target,
        )
        result = self.facade.autodebug_get_plan(case_id="CASE-2026-NOPLAN")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "NOT_APPROVED")

    def test_unknown_case_id_fails_closed(self):
        result = self.facade.autodebug_case_status(case_id="CASE-DOES-NOT-EXIST")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")


class TestCompleteCaseConfidenceBar(FacadeTestBase):
    def test_confirmed_without_causal_validation_is_rejected(self):
        case_id = "CASE-2026-T07"
        digest = self.create_and_stage(case_id)
        approval = self.issue_approval(case_id, digest, self.target)
        armed = self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )
        session_id = armed["result"]["session"]["debug_session_id"]
        self.adapter.simulate_stop(session_id)
        self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        self.facade.autodebug_get_stack(case_id=case_id, frame_limit=1)
        # T15 (DE-06 gap closure): `autodebug_complete_case` now cross-checks
        # every cited evidence ID against what was actually recorded, so
        # "E0001" must be genuinely produced here (via `get_variables`) for
        # this test to still exercise its real subject -- the
        # causal-validation bar -- rather than failing earlier on a
        # never-recorded evidence ID for an unrelated reason.
        self.facade.autodebug_get_variables(case_id=case_id, frame_id="frame-0", selected_names=("local_var",))

        result = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="Null local_var",
            confidence=RootCauseConfidence.CONFIRMED,
            evidence_ids=("E0001",),
            reproduced=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
        # T15 security review: assert on the message too, so a future
        # regression in the evidence-ID check (DE-06) that masked this
        # test's real subject (the causal-validation bar) would be caught
        # here rather than passing for the wrong reason.
        self.assertIn("CONFIRMED", result["error"]["message"])
        self.assertIn("causal_validation", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
