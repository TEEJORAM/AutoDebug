"""Synthetic publication regressions for approval, pause and quota boundaries."""

import json
import math
import unittest
from dataclasses import replace
from unittest.mock import patch

from autodebug.errors import AutoDebugError
from autodebug.facade import SCOPE_ARM, SCOPE_CONTINUE, SCOPE_STEP
from autodebug.models import CasePolicy, IntakeSource, TargetRef
from autodebug.plans import stage_plan
from tests.test_facade import FacadeTestBase, make_plan
from tests.fixtures.fake_backend import FULL_SUPPORT

READ_SCOPES = ("op:wait_for_stop", "op:get_stack", "op:get_variables")
ALL_SCOPES = (SCOPE_ARM, SCOPE_STEP, SCOPE_CONTINUE) + READ_SCOPES


class PublicationSecurityTests(FacadeTestBase):
    def arm(self, *, scopes=ALL_SCOPES):
        self.case_id = "publication"
        digest = self.create_and_stage(self.case_id)
        self.approval = self.issue_approval(self.case_id, digest, self.target, scope=scopes)
        result = self.facade.autodebug_arm_case(
            case_id=self.case_id, approval=self.approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None, process_running=False,
        )
        self.assertTrue(result["ok"], result)
        self.ctx = self.facade._cases[self.case_id]
        self.adapter.simulate_stop(self.ctx.session.debug_session_id)
        return self.ctx

    def pause(self):
        result = self.facade.autodebug_wait_for_stop(case_id=self.case_id, timeout_seconds=1)
        self.assertTrue(result["ok"], result)

    def read(self):
        return self.facade.autodebug_get_variables(
            case_id=self.case_id, frame_id="0", selected_names=("local_var",),
        )

    def assert_error(self, result, code):
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], code, result)

    def test_foreign_case_plan_rejected_without_mutating_case(self):
        self.facade.autodebug_create_case(
            case_id="recipient", intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="synthetic", adapter=self.adapter, target=self.target,
        )
        result = self.facade.autodebug_stage_plan(case_id="recipient", plan=make_plan(case_id="donor"))
        self.assert_error(result, "PLAN_CHANGED")
        self.assertIsNone(self.facade._cases["recipient"].case.plan)
        self.assertEqual(self.adapter.launch_or_attach_calls, 0)

    def test_foreign_target_plan_rejected(self):
        self.facade.autodebug_create_case(
            case_id="recipient", intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="synthetic", adapter=self.adapter, target=self.target,
        )
        other = TargetRef(host_id="local-other", ide="fake", debug_session_id=None, pid=None)
        result = self.facade.autodebug_stage_plan(
            case_id="recipient", plan=make_plan(case_id="recipient", target=other),
        )
        self.assert_error(result, "TARGET_MISMATCH")

    def test_inspection_requires_explicit_scope_before_backend_call(self):
        self.arm(scopes=(SCOPE_ARM,))
        with patch.object(self.adapter, "is_paused", wraps=self.adapter.is_paused) as paused:
            result = self.facade.autodebug_wait_for_stop(case_id=self.case_id, timeout_seconds=1)
            self.assert_error(result, "PERMISSION_DENIED")
            paused.assert_not_called()

    def test_expiration_blocks_each_sensitive_inspection(self):
        for operation in ("wait", "stack", "variables"):
            with self.subTest(operation=operation):
                self.setUp()
                self.arm()
                self.pause()
                self.clock["t"] += 60
                with patch.object(self.adapter, "is_paused") as paused:
                    if operation == "wait":
                        result = self.facade.autodebug_wait_for_stop(case_id=self.case_id, timeout_seconds=1)
                    elif operation == "stack":
                        result = self.facade.autodebug_get_stack(case_id=self.case_id, frame_limit=1)
                    else:
                        result = self.read()
                    self.assert_error(result, "APPROVAL_EXPIRED")
                    paused.assert_not_called()
                self.assertEqual(self.ctx.case.state.value, "incomplete")

    def test_continue_invalidates_cached_pause(self):
        self.arm()
        self.pause()
        self.assertTrue(self.read()["ok"])
        resumed = self.facade.autodebug_continue(case_id=self.case_id, approval=self.approval)
        self.assertTrue(resumed["ok"], resumed)
        with patch.object(self.adapter, "get_variables") as variables:
            self.assert_error(self.read(), "NOT_PAUSED")
            variables.assert_not_called()
        self.adapter.simulate_stop(self.ctx.session.debug_session_id)
        self.pause()
        self.assertTrue(self.read()["ok"])

    def test_external_resume_invalidates_cached_pause(self):
        self.arm()
        self.pause()
        self.adapter.continue_execution(self.ctx.session)
        self.assert_error(self.read(), "NOT_PAUSED")

    def test_inspection_uses_same_lease_as_mutations(self):
        self.arm()
        self.pause()
        with self.registry.lease(self.ctx.session):
            self.assert_error(self.read(), "POLICY_LIMIT")

    def test_unregister_reregister_cannot_replace_active_lease(self):
        self.arm()
        session = self.ctx.session
        with self.registry.lease(session):
            self.registry.unregister(session)
            self.registry.register(session)
            with self.assertRaises(AutoDebugError):
                with self.registry.lease(session):
                    self.fail("replacement lease acquired")

    def test_stale_unregister_does_not_remove_new_generation(self):
        self.arm()
        replacement = replace(self.ctx.session, session_generation=2)
        self.registry.register(replacement)
        self.registry.unregister(self.ctx.session)
        self.assertEqual(self.registry.all_sessions(), (replacement,))

    def test_failed_storage_initialization_never_arms_backend(self):
        digest = self.create_and_stage("storage")
        approval = self.issue_approval("storage", digest, self.target)
        with patch("autodebug.facade.EvidenceStore", side_effect=OSError("synthetic storage failure")):
            try:
                result = self.facade.autodebug_arm_case(
                    case_id="storage", approval=approval,
                    capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
                    reviewed_configuration=None, process_running=False,
                )
            finally:
                self.assertEqual(self.adapter.launch_or_attach_calls, 0)
                self.assertEqual(self.registry.all_sessions(), ())
        self.assert_error(result, "INTERNAL_ERROR")

    def test_deadline_blocks_reads_before_approval_expiry(self):
        self.arm()
        self.pause()
        self.ctx.inspection_started_at = self.clock["t"] - 300
        with patch.object(self.adapter, "get_variables") as variables:
            self.assert_error(self.read(), "POLICY_LIMIT")
            variables.assert_not_called()

    def test_stack_and_variable_names_are_redacted_and_bounded(self):
        self.arm()
        self.pause()
        secret = "ghp_" + "z" * 36
        with patch.object(self.adapter, "get_stack", return_value=({"function": secret, "file": "x" * 10000},)):
            result = self.facade.autodebug_get_stack(case_id=self.case_id, frame_limit=1)
        self.assertTrue(result["ok"], result)
        self.assertNotIn(secret, json.dumps(result))
        self.assertLess(len(json.dumps(result)), 2000)
        with patch.object(self.adapter, "get_variables", return_value={secret: "value"}):
            result = self.facade.autodebug_get_variables(
                case_id=self.case_id, frame_id="0", selected_names=(secret,),
            )
        self.assertTrue(result["ok"], result)
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, self.ctx.evidence_store.events_path.read_text())

    def test_nonpositive_or_nonfinite_wait_is_rejected_without_poll(self):
        self.arm()
        for timeout in (0, -1, math.nan, math.inf, True):
            with self.subTest(timeout=timeout), patch.object(self.adapter, "is_paused") as paused:
                result = self.facade.autodebug_wait_for_stop(case_id=self.case_id, timeout_seconds=timeout)
                self.assert_error(result, "POLICY_LIMIT")
                paused.assert_not_called()

    def test_plan_budgets_require_positive_integers(self):
        for steps, seconds in ((-1, 1), (1, 0), (True, 1), (1, math.inf)):
            with self.subTest(steps=steps, seconds=seconds), self.assertRaises(ValueError):
                stage_plan(replace(make_plan(), policy=CasePolicy(steps, seconds)))

    def test_repeated_arm_has_no_backend_side_effects(self):
        self.arm()
        with patch.object(self.adapter, "set_breakpoints") as bind:
            result = self.facade.autodebug_arm_case(
                case_id=self.case_id, approval=self.approval,
                capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
                reviewed_configuration=None, process_running=False,
            )
        self.assertFalse(result["ok"])
        bind.assert_not_called()
        self.assertEqual(self.adapter.launch_or_attach_calls, 1)

    def test_each_read_requires_its_own_scope(self):
        self.arm(scopes=(SCOPE_ARM, "op:wait_for_stop"))
        self.pause()
        with patch.object(self.adapter, "get_stack") as stack, patch.object(self.adapter, "get_variables") as variables:
            self.assert_error(
                self.facade.autodebug_get_stack(case_id=self.case_id, frame_limit=1), "PERMISSION_DENIED",
            )
            self.assert_error(self.read(), "PERMISSION_DENIED")
            stack.assert_not_called()
            variables.assert_not_called()

    def test_revoked_approval_blocks_read_and_wait(self):
        self.arm()
        self.pause()
        self.broker.revoke(self.approval.token)
        with patch.object(self.adapter, "get_variables") as variables:
            self.assert_error(self.read(), "CANCELLED")
            variables.assert_not_called()
        self.assert_error(
            self.facade.autodebug_wait_for_stop(case_id=self.case_id, timeout_seconds=1), "CANCELLED",
        )

    def test_expiration_during_read_discards_late_result(self):
        self.arm()
        self.pause()
        before = self.ctx.evidence_store.read_events()

        def expire(*_args):
            self.clock["t"] += 60
            return {"local_var": "not authorized to return"}

        with patch.object(self.adapter, "get_variables", side_effect=expire):
            result = self.read()
        self.assert_error(result, "APPROVAL_EXPIRED")
        self.assertNotIn("not authorized", json.dumps(result))
        self.assertEqual(self.ctx.evidence_store.read_events(), before)

    def test_wait_rechecks_identity_after_each_poll(self):
        self.arm()
        self.adapter.continue_execution(self.ctx.session)

        def unregister(_seconds):
            self.registry.unregister(self.ctx.session)
            self.clock["t"] += 1

        self.facade._sleep = unregister
        self.assert_error(
            self.facade.autodebug_wait_for_stop(case_id=self.case_id, timeout_seconds=1), "SESSION_STALE",
        )

    def test_reused_case_storage_is_rejected_before_arming(self):
        self.arm()
        from autodebug.facade import AutoDebugFacade
        fresh = AutoDebugFacade(
            registry=type(self.registry)(), broker=self.broker,
            evidence_base_dir=self.facade._evidence_base_dir,
        )
        fresh.autodebug_create_case(
            case_id=self.case_id, intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="new investigation", adapter=self.adapter, target=self.target,
        )
        fresh.autodebug_stage_plan(case_id=self.case_id, plan=make_plan(case_id=self.case_id))
        result = fresh.autodebug_arm_case(
            case_id=self.case_id, approval=self.approval,
            capability_report=self.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None, process_running=False,
        )
        self.assert_error(result, "INTERNAL_ERROR")
        self.assertEqual(self.adapter.launch_or_attach_calls, 1)

    def test_unselected_backend_values_are_never_returned_or_persisted(self):
        self.arm()
        self.pause()
        with patch.object(self.adapter, "get_variables", return_value={"local_var": "42", "unselected": "private"}):
            result = self.read()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["variables"], {"local_var": "42"})
        self.assertNotIn("private", self.ctx.evidence_store.events_path.read_text())


if __name__ == "__main__":
    unittest.main()
