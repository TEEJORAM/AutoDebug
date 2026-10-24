"""Synthetic regressions for the comprehensive technical closure."""

import hashlib
import json
import unittest
import threading
import time
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from autodebug.facade import target_identity_for
from autodebug.models import ReproductionPlan, RootCauseConfidence
from autodebug.evidence import EvidenceStore
from autodebug.errors import AutoDebugError
from autodebug.operations import call_bounded
from autodebug.approvals import ApprovalBroker
from autodebug.plans import stage_plan
from tests import test_publication_security as publication
from tests.test_plans import make_plan


class TechnicalClosureTests(unittest.TestCase):
    def fixture(self, *, operation_seconds=None):
        helper = publication.PublicationSecurityTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        if operation_seconds is None:
            helper.arm()
        else:
            original = publication.make_plan

            def budgeted(**kwargs):
                plan = original(**kwargs)
                return replace(plan, policy=replace(plan.policy, max_operation_seconds=operation_seconds))

            with patch("tests.test_facade.make_plan", side_effect=budgeted):
                helper.arm()
        helper.pause()
        return helper

    def test_digest_without_complete_script_is_not_a_reviewed_script(self):
        with self.assertRaises(ValueError):
            stage_plan(make_plan(reproduction=ReproductionPlan(
                mode="api_script", steps=("Run reviewed script",), script_sha256="a" * 64,
            )))

    def test_structured_selected_variable_redacts_nested_secret_name(self):
        helper = self.fixture()
        with patch.object(helper.adapter, "get_variables", return_value={"config": {"password": "synthetic-private-value"}}):
            result = helper.facade.autodebug_get_variables(
                case_id=helper.case_id, frame_id="f0", selected_names=("config",),
            )
        self.assertTrue(result["ok"], result)
        self.assertNotIn("synthetic-private-value", json.dumps(result))
        self.assertNotIn("synthetic-private-value", helper.ctx.evidence_store.events_path.read_text())

    def test_unregister_refresh_does_not_drop_active_owner(self):
        helper = self.fixture()
        session = helper.ctx.session
        helper.registry.unregister(session)
        helper.registry.register(session)
        digest = helper.create_and_stage("other")
        approval = helper.issue_approval("other", digest, helper.target, scope=publication.ALL_SCOPES)
        with patch.object(helper.adapter, "set_breakpoints", wraps=helper.adapter.set_breakpoints) as bind:
            result = helper.facade.autodebug_arm_case(
                case_id="other", approval=approval,
                capability_report=helper.adapter.probe_capabilities(publication.FULL_SUPPORT),
                reviewed_configuration=None, process_running=False,
            )
        self.assertFalse(result["ok"], result)
        bind.assert_not_called()

    def test_empty_binding_response_is_not_verified_breakpoints(self):
        helper = publication.PublicationSecurityTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        with patch.object(helper.adapter, "set_breakpoints", return_value=()):
            with self.assertRaises(AssertionError):
                helper.arm()
        self.assertNotEqual(helper.facade._cases["publication"].case.state.value, "awaiting_developer_reproduction")

    def test_nonfinite_approval_lifetime_is_rejected(self):
        helper = self.fixture()
        for ttl in (float("nan"), float("inf"), 0, -1, True):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                helper.broker.issue_approval(
                    helper.ctx.case.plan, reviewer="synthetic", backend_kind="fake",
                    target_identity=target_identity_for(helper.target),
                    scope=publication.ALL_SCOPES, ttl_seconds=ttl, human_presence_confirmed=True,
                )

    def test_complete_script_bytes_and_hash_are_bound(self):
        script = "value = '\u2603'\n"
        reproduction = ReproductionPlan(
            mode="api_script", steps=("Run reviewed synthetic script",), script_content=script,
            script_sha256=hashlib.sha256(script.encode("utf-8")).hexdigest(),
            risks=("Synthetic only; no external application",), sample_document="No sample document required",
        )
        plan = stage_plan(make_plan(reproduction=reproduction))
        with self.assertRaisesRegex(ValueError, "side effects"):
            stage_plan(replace(plan, reproduction=replace(reproduction, risks=())))
        with self.assertRaises(ValueError):
            stage_plan(replace(plan, reproduction=replace(reproduction, script_content=script + "# edit\n")))
        revised = replace(reproduction, script_content="value = 2\n", script_sha256=hashlib.sha256(b"value = 2\n").hexdigest())
        self.assertNotEqual(plan.digest_sha256, stage_plan(replace(plan, reproduction=revised)).digest_sha256)

    def test_changed_launch_configuration_cannot_reach_backend(self):
        helper = publication.PublicationSecurityTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        digest = helper.create_and_stage("launch-binding")
        approval = helper.issue_approval("launch-binding", digest, helper.target)
        result = helper.facade.autodebug_arm_case(
            case_id="launch-binding", approval=approval,
            capability_report=helper.adapter.probe_capabilities(publication.FULL_SUPPORT),
            reviewed_configuration={"launch_profile": "unreviewed"}, process_running=False,
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "PLAN_CHANGED")
        self.assertEqual(helper.adapter.launch_or_attach_calls, 0)

    def test_lost_owner_cannot_read_even_with_valid_identity_and_approval(self):
        helper = self.fixture()
        helper.registry.release_owner(helper.ctx.session, helper.ctx)
        helper.registry.claim(helper.ctx.session, object())
        with patch.object(helper.adapter, "get_variables") as read:
            result = helper.read()
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "TARGET_MISMATCH")
        read.assert_not_called()

    def test_resume_and_restop_during_read_discards_old_frame(self):
        helper = self.fixture()
        before = helper.ctx.evidence_store.read_events()

        def restop(*_args):
            helper.adapter.continue_execution(helper.ctx.session)
            helper.adapter.simulate_stop(helper.ctx.session.debug_session_id)
            return {"local_var": "stale frame value"}

        with patch.object(helper.adapter, "get_variables", side_effect=restop):
            result = helper.read()
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "SESSION_STALE")
        self.assertEqual(helper.ctx.evidence_store.read_events(), before)
        self.assertNotIn("stale frame value", json.dumps(result))
        helper.pause()
        self.assertTrue(helper.read()["ok"])

    def test_process_start_change_refuses_reused_pid(self):
        helper = self.fixture()
        helper.registry.register(replace(helper.ctx.session, process_start_id="synthetic-new-process"))
        with patch.object(helper.adapter, "get_variables") as read:
            result = helper.read()
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "TARGET_MISMATCH")
        read.assert_not_called()

    def test_stop_and_stack_evidence_include_identity_and_exact_sanitized_stack(self):
        helper = self.fixture()
        stack = helper.facade.autodebug_get_stack(case_id=helper.case_id, frame_limit=2)
        self.assertTrue(stack["ok"], stack)
        events = helper.ctx.evidence_store.read_events()
        self.assertEqual([event.event_type for event in events], ["stop_observed", "stack_observed"])
        self.assertTrue(all(event.stop_id == helper.ctx.stop.stop_id for event in events))
        self.assertTrue(all(event.process_start_id == helper.ctx.session.process_start_id for event in events))
        self.assertTrue(all(event.plan_digest == helper.ctx.case.approved_digest for event in events))
        self.assertEqual(json.loads(events[1].observation.split("=", 1)[1]), stack["result"]["frames"])

    def test_same_case_evidence_content_tampering_is_rejected(self):
        helper = self.fixture()
        self.assertTrue(helper.read()["ok"])
        store = helper.ctx.evidence_store
        lines = store.events_path.read_text().splitlines()
        record = json.loads(lines[-1])
        record["observation"] = "local_var=forged"
        lines[-1] = json.dumps(record)
        store.events_path.write_text("\n".join(lines) + "\n")
        with self.assertRaisesRegex(ValueError, "append ledger"):
            store.read_events()

    def test_deleted_event_file_is_not_empty_success(self):
        helper = self.fixture()
        helper.ctx.evidence_store.events_path.unlink()
        with self.assertRaisesRegex(ValueError, "disappeared"):
            helper.ctx.evidence_store.read_events()

    def test_evidence_base_inside_repository_is_refused_before_creation(self):
        path = Path(__file__).resolve().parents[1] / ".forbidden-evidence-base"
        self.assertFalse(path.exists())
        with self.assertRaisesRegex(ValueError, "outside"):
            EvidenceStore(path, "synthetic")
        self.assertFalse(path.exists())

    def test_incomplete_case_can_write_honest_report_without_finalized_relabel(self):
        helper = self.fixture()
        self.assertTrue(helper.read()["ok"])
        helper.facade._mark_incomplete(helper.ctx)
        result = helper.facade.autodebug_complete_case(
            case_id=helper.case_id, root_cause_statement="insufficient synthetic evidence",
            confidence=RootCauseConfidence.INCONCLUSIVE, evidence_ids=(), reproduced=False,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["state"], "incomplete")
        self.assertEqual(json.loads(helper.ctx.evidence_store.case_path.read_text())["state"], "incomplete")
        self.assertIn("Case state: incomplete", helper.ctx.evidence_store.report_path.read_text())

    def test_noncooperative_read_has_bounded_return_and_quarantined_late_cleanup(self):
        helper = self.fixture(operation_seconds=0.05)
        release, cleaned = threading.Event(), threading.Event()
        disconnect = helper.adapter.disconnect
        before = helper.ctx.evidence_store.read_events()

        def blocked(*_args):
            release.wait(3)
            return {"local_var": "late synthetic data"}

        def cleanup(session):
            disconnect(session)
            cleaned.set()

        with patch.object(helper.adapter, "get_variables", side_effect=blocked), patch.object(helper.adapter, "disconnect", side_effect=cleanup):
            try:
                started = time.monotonic()
                result = helper.read()
                self.assertLess(time.monotonic() - started, 1)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["error"]["code"], "TIMEOUT")
                self.assertEqual(helper.ctx.case.state.value, "incomplete")
                self.assertEqual(helper.ctx.evidence_store.read_events(), before)
                with self.assertRaisesRegex(AutoDebugError, "quarantined"):
                    with helper.registry.arming_lease(helper.target):
                        self.fail("quarantined backend reused")
            finally:
                release.set()
            self.assertTrue(cleaned.wait(1))
        self.assertEqual(helper.registry.all_sessions(), ())

    def test_late_backend_exception_runs_cleanup_even_without_result(self):
        release, cleaned, abandoned = threading.Event(), threading.Event(), threading.Event()

        def failing():
            release.wait(3)
            raise RuntimeError("synthetic late failure")

        try:
            with self.assertRaisesRegex(AutoDebugError, "deadline"):
                call_bounded(
                    failing, timeout=0.03, cancellation=threading.Event(),
                    on_abandon=abandoned.set, on_late_error=cleaned.set,
                )
            self.assertTrue(abandoned.is_set())
        finally:
            release.set()
        self.assertTrue(cleaned.wait(1))

    def test_approval_expiry_survives_wall_clock_rollback_and_duplicate_tokens_fail(self):
        wall = [1000.0]
        broker = ApprovalBroker(now=lambda: wall[0], make_token=lambda: "synthetic-unique-token")
        plan = stage_plan(make_plan())
        with patch("autodebug.approvals.time.monotonic", return_value=100.0):
            approval = broker.issue_approval(
                plan, reviewer="synthetic", backend_kind="fake", target_identity="synthetic",
                scope=("op:get_variables",), ttl_seconds=10, human_presence_confirmed=True,
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            broker.issue_approval(
                plan, reviewer="synthetic", backend_kind="fake", target_identity="synthetic",
                scope=("op:get_variables",), ttl_seconds=10, human_presence_confirmed=True,
            )
        wall[0] = 900.0
        with patch("autodebug.approvals.time.monotonic", return_value=111.0):
            with self.assertRaisesRegex(AutoDebugError, "expired"):
                broker.verify_approval(approval, plan=plan, backend_kind="fake", target_identity="synthetic", required_scope="op:get_variables")

    def test_evidence_capacity_is_checked_before_debugger_inspection(self):
        helper = self.fixture()
        helper.ctx.evidence_store.max_events = len(helper.ctx.evidence_store.read_events())
        with patch.object(helper.adapter, "get_variables") as read:
            result = helper.read()
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "POLICY_LIMIT")
        read.assert_not_called()

    def test_session_status_and_probe_metadata_are_redacted(self):
        helper = self.fixture()
        marker = "sk-" + "a" * 32
        sensitive_session = replace(helper.ctx.session, ide_instance_id=marker)
        helper.registry.register(sensitive_session)
        sessions = helper.facade.autodebug_list_sessions()
        self.assertNotIn(marker, json.dumps(sessions))
        helper.ctx.session = sensitive_session
        self.assertNotIn(marker, json.dumps(helper.facade.autodebug_case_status(case_id=helper.case_id)))
        report = helper.adapter.probe_capabilities(publication.FULL_SUPPORT)
        with patch.object(helper.adapter, "probe_capabilities", return_value=replace(report, reason=marker, backend_version=marker)):
            result = helper.facade.autodebug_probe_adapters(adapters=((helper.adapter, None, None),))
        self.assertTrue(result["ok"], result)
        self.assertNotIn(marker, json.dumps(result))

    def test_late_launch_cannot_leave_an_authorized_or_registered_session(self):
        helper = publication.PublicationSecurityTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        case_id = "late-synthetic-launch"
        plan = publication.make_plan(case_id=case_id)
        plan = replace(plan, policy=replace(plan.policy, max_operation_seconds=0.05))
        digest = helper.create_and_stage(case_id, plan=plan)
        approval = helper.issue_approval(case_id, digest, helper.target)
        release, cleaned = threading.Event(), threading.Event()
        launch, unregister = helper.adapter.launch_or_attach, helper.registry.unregister

        def delayed(*args, **kwargs):
            release.wait(3)
            return launch(*args, **kwargs)

        def cleanup(session):
            unregister(session)
            cleaned.set()

        with patch.object(helper.adapter, "launch_or_attach", side_effect=delayed), patch.object(helper.registry, "unregister", side_effect=cleanup):
            try:
                result = helper.facade.autodebug_arm_case(
                    case_id=case_id, approval=approval,
                    capability_report=helper.adapter.probe_capabilities(publication.FULL_SUPPORT),
                    reviewed_configuration=None, process_running=False,
                )
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["error"]["code"], "TIMEOUT")
                ctx = helper.facade._cases[case_id]
                self.assertIsNone(ctx.session)
                self.assertEqual(ctx.evidence_store.read_events(), ())
                with self.assertRaisesRegex(AutoDebugError, "revoked"):
                    helper.broker.verify_approval(
                        approval, plan=ctx.case.plan, backend_kind="fake",
                        target_identity=target_identity_for(helper.target), required_scope=publication.SCOPE_ARM,
                    )
                self.assertNotEqual(ctx.case.state.value, "awaiting_developer_reproduction")
            finally:
                release.set()
            self.assertTrue(cleaned.wait(1))
        self.assertEqual(helper.registry.all_sessions(), ())
        self.assertEqual(helper.adapter.disconnect_calls, 1)

    def test_cancellation_does_not_wait_for_blocked_value_rendering(self):
        helper = self.fixture()
        entered, release = threading.Event(), threading.Event()
        before = helper.ctx.evidence_store.read_events()
        results = []

        class BlockedValue:
            def __str__(self):
                entered.set()
                release.wait(3)
                return "late rendered synthetic value"

        with patch.object(helper.adapter, "get_variables", return_value={"local_var": BlockedValue()}):
            worker = threading.Thread(target=lambda: results.append(helper.read()))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                result = helper.facade.autodebug_cancel_case(case_id=helper.case_id)
                self.assertLess(time.monotonic() - started, 1)
                self.assertTrue(result["ok"], result)
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results[0]["error"]["code"], "CANCELLED")
                self.assertEqual(helper.ctx.evidence_store.read_events(), before)
            finally:
                release.set()
                worker.join(3)

    def test_cancellation_keeps_owner_until_disconnect_retires(self):
        helper = self.fixture()
        entered, release = threading.Event(), threading.Event()
        results = []
        disconnect = helper.adapter.disconnect

        def blocked_disconnect(session):
            entered.set()
            release.wait(3)
            disconnect(session)

        with patch.object(helper.adapter, "disconnect", side_effect=blocked_disconnect):
            worker = threading.Thread(target=lambda: results.append(helper.facade.autodebug_cancel_case(case_id=helper.case_id)))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(AutoDebugError):
                    helper.registry.claim(helper.ctx.session, object())
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0]["ok"], results)

    def test_cancel_interrupts_blocked_read_without_late_evidence(self):
        helper = self.fixture()
        entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
        results = []
        before = helper.ctx.evidence_store.read_events()
        disconnect = helper.adapter.disconnect

        def blocked(*_args):
            entered.set()
            release.wait(3)
            return {"local_var": "cancelled synthetic data"}

        def cleanup(session):
            disconnect(session)
            cleaned.set()

        with patch.object(helper.adapter, "get_variables", side_effect=blocked), patch.object(helper.adapter, "disconnect", side_effect=cleanup):
            worker = threading.Thread(target=lambda: results.append(helper.read()))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                cancelled = helper.facade.autodebug_cancel_case(case_id=helper.case_id)
                self.assertTrue(cancelled["ok"], cancelled)
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results[0]["error"]["code"], "CANCELLED")
                self.assertEqual(helper.ctx.evidence_store.read_events(), before)
            finally:
                release.set()
                worker.join(3)
            self.assertTrue(cleaned.wait(1))
