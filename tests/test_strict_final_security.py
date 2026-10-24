"""Strict-review regressions use only synthetic sessions and disposable files."""

import json
import os
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from autodebug import _winfs
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import RootCauseConfidence
from tests import test_publication_security as publication
from tests.fixtures.fake_backend import FULL_SUPPORT


class StrictFinalSecurityTests(unittest.TestCase):
    def fixture(self, *, paused=True, armed=True):
        helper = publication.PublicationSecurityTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        if armed:
            helper.arm()
            if paused:
                helper.pause()
        return helper

    def stage_extra(self, helper, case_id, *, target=None):
        target = helper.target if target is None else target
        digest = helper.create_and_stage(case_id, target=target)
        return helper.issue_approval(case_id, digest, target, scope=publication.ALL_SCOPES)

    def arm_extra(self, helper, case_id, approval):
        return helper.facade.autodebug_arm_case(
            case_id=case_id, approval=approval,
            capability_report=helper.adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None, process_running=False,
        )

    def complete(self, helper, *, reproduced=True, evidence_ids=("E0001",)):
        return helper.facade.autodebug_complete_case(
            case_id=helper.case_id, root_cause_statement="synthetic conclusion",
            confidence=RootCauseConfidence.LIKELY if evidence_ids else RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=evidence_ids, reproduced=reproduced,
        )

    def test_expiration_during_launch_stops_breakpoint_mutation(self):
        helper = self.fixture(armed=False)
        approval = self.stage_extra(helper, "expiry-at-arm")
        launch = helper.adapter.launch_or_attach

        def expire(*args):
            session = launch(*args)
            helper.clock["t"] += 61
            return session

        with patch.object(helper.adapter, "launch_or_attach", side_effect=expire):
            with patch.object(helper.adapter, "set_breakpoints", wraps=helper.adapter.set_breakpoints) as bind:
                result = self.arm_extra(helper, "expiry-at-arm", approval)
        bind.assert_not_called()
        self.assertFalse(result["ok"], result)
        self.assertEqual(helper.registry.all_sessions(), ())

    def test_revocation_during_launch_stops_breakpoint_mutation(self):
        helper = self.fixture(armed=False)
        approval = self.stage_extra(helper, "revoke-at-arm")
        launch = helper.adapter.launch_or_attach

        def revoke(*args):
            session = launch(*args)
            helper.broker.revoke(approval.token)
            return session

        with patch.object(helper.adapter, "launch_or_attach", side_effect=revoke):
            with patch.object(helper.adapter, "set_breakpoints", wraps=helper.adapter.set_breakpoints) as bind:
                result = self.arm_extra(helper, "revoke-at-arm", approval)
        bind.assert_not_called()
        self.assertFalse(result["ok"], result)

    def test_arm_obeys_existing_session_lease(self):
        helper = self.fixture()
        approval = self.stage_extra(helper, "second")
        with helper.registry.lease(helper.ctx.session):
            with patch.object(helper.adapter, "set_breakpoints", wraps=helper.adapter.set_breakpoints) as bind:
                result = self.arm_extra(helper, "second", approval)
        bind.assert_not_called()
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "POLICY_LIMIT")

    def test_second_case_cannot_disconnect_or_rebind_first_case(self):
        helper = self.fixture()
        session = helper.ctx.session
        approval = self.stage_extra(helper, "failed-second")
        helper.adapter.can_bind_breakpoints = False
        result = self.arm_extra(helper, "failed-second", approval)
        self.assertFalse(result["ok"], result)
        self.assertIn(session, helper.registry.all_sessions())
        self.assertEqual(helper.adapter.disconnect_calls, 0)

    def test_rollback_preserves_preexisting_unowned_ide_session(self):
        helper = self.fixture(armed=False)
        session = helper.adapter.launch_or_attach(helper.target, None)
        helper.registry.register(session)
        approval = self.stage_extra(helper, "reuse")
        helper.adapter.can_bind_breakpoints = False
        result = self.arm_extra(helper, "reuse", approval)
        self.assertFalse(result["ok"], result)
        self.assertIn(session, helper.registry.all_sessions())
        self.assertEqual(helper.adapter.disconnect_calls, 0)

    def test_returned_session_matches_approved_process(self):
        for field, value in (
            ("pid", 999), ("host_id", "local-other"), ("ide", "other-fake"),
            ("debug_session_id", "wrong-session"), ("ide_instance_id", "wrong-window"),
        ):
            with self.subTest(field=field):
                helper = self.fixture(armed=False)
                target = replace(helper.target, pid=100, debug_session_id="fake-session-1",
                                 ide_instance_id="fake-fake-window")
                approval = self.stage_extra(helper, "wrong-process", target=target)
                launch = helper.adapter.launch_or_attach

                def wrong(*args, launch=launch, field=field, value=value):
                    return replace(launch(*args), **{field: value})

                with patch.object(helper.adapter, "launch_or_attach", side_effect=wrong):
                    with patch.object(helper.adapter, "set_breakpoints", wraps=helper.adapter.set_breakpoints) as bind:
                        result = self.arm_extra(helper, "wrong-process", approval)
                bind.assert_not_called()
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["error"]["code"], "TARGET_MISMATCH")
                self.assertEqual(helper.registry.all_sessions(), ())

    def test_sensitive_named_stack_fields_are_redacted(self):
        helper = self.fixture()
        marker = "synthetic-password-not-a-token-shape"
        frames = ({"arguments": {"password": marker}},)
        with patch.object(helper.adapter, "get_stack", return_value=frames):
            result = helper.facade.autodebug_get_stack(case_id=helper.case_id, frame_limit=1)
        self.assertTrue(result["ok"], result)
        self.assertNotIn(marker, json.dumps(result))

    def test_stack_has_global_byte_budget(self):
        helper = self.fixture()
        leaves = {str(i): "x" * 500 for i in range(20)}
        nested = {str(i): leaves for i in range(20)}
        frame = {str(i): nested for i in range(20)}
        with patch.object(helper.adapter, "get_stack", return_value=(frame,)):
            result = helper.facade.autodebug_get_stack(case_id=helper.case_id, frame_limit=1)
        self.assertTrue(result["ok"], result)
        self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 65536)
        self.assertIn("truncated", json.dumps(result))
        visited = 0

        class CountedLeaf:
            def __str__(self):
                nonlocal visited
                visited += 1
                return ""

        frames = ({"children": [[CountedLeaf()] * 50] * 50},) * 50
        with patch.object(helper.adapter, "get_stack", return_value=frames):
            result = helper.facade.autodebug_get_stack(case_id=helper.case_id, frame_limit=50)
        self.assertTrue(result["ok"], result)
        self.assertGreater(visited, 3000)
        self.assertLessEqual(visited, 4096)
        self.assertIn("truncated", json.dumps(result))

    def test_backend_disconnect_marks_incomplete(self):
        helper = self.fixture()
        with patch.object(
            helper.adapter, "get_variables",
            side_effect=AutoDebugError(ErrorDetail(code=ErrorCode.BACKEND_UNAVAILABLE, message="synthetic disconnect")),
        ):
            result = helper.read()
        self.assertFalse(result["ok"], result)
        self.assertEqual(helper.ctx.case.state.value, "incomplete")
        self.assertTrue(helper.ctx.evidence_store.case_path.exists())

    def test_report_write_failure_leaves_retryable_case(self):
        helper = self.fixture()
        self.assertTrue(helper.read()["ok"])
        store = helper.ctx.evidence_store
        original = store._open_file

        def fail_report(name, mode):
            if name == "report.md":
                raise OSError("synthetic disk-write failure")
            return original(name, mode)

        with patch.object(store, "_open_file", side_effect=fail_report):
            result = self.complete(helper)
        self.assertFalse(result["ok"], result)
        self.assertNotEqual(helper.ctx.case.state.value, "finalized")
        if store.case_path.exists():
            self.assertNotEqual(json.loads(store.case_path.read_text())["state"], "finalized")
        self.assertTrue(self.complete(helper)["ok"])
        self.assertTrue(store.events_path.exists())
        self.assertTrue(store.case_path.exists())
        self.assertTrue(store.report_path.exists())

    def test_deadline_crossed_during_final_pause_check_discards_output(self):
        helper = self.fixture()
        before = helper.ctx.evidence_store.read_events()
        helper.ctx.inspection_started_at = helper.clock["t"] - 299.5
        calls = 0

        def paused(_session):
            nonlocal calls
            calls += 1
            if calls == 2:
                helper.clock["t"] += 1
            return True

        with patch.object(helper.adapter, "is_paused", side_effect=paused):
            result = helper.read()
        self.assertFalse(result["ok"], result)
        self.assertEqual(helper.ctx.evidence_store.read_events(), before)

    def test_no_confirmed_pause_cannot_claim_reproduction(self):
        helper = self.fixture(paused=False)
        result = self.complete(helper, evidence_ids=())
        self.assertFalse(result["ok"], result)
        self.assertTrue(self.complete(helper, reproduced=False, evidence_ids=())["ok"])
        self.assertTrue(helper.ctx.evidence_store.events_path.exists())

    def test_lossy_case_identity_is_rejected_at_intake(self):
        helper = self.fixture(armed=False)
        for case_id in ("ghp_" + "r" * 36, "c" * 501):
            with self.subTest(case_id=case_id):
                result = helper.facade.autodebug_create_case(
                    case_id=case_id, intake_source=publication.IntakeSource.DEVELOPER_TEXT,
                    intake_description="synthetic", adapter=helper.adapter, target=helper.target,
                )
                self.assertFalse(result["ok"], result)
                self.assertNotIn(case_id, helper.facade._cases)

    def test_cancel_during_final_pause_check_blocks_persistence(self):
        helper = self.fixture()
        before = helper.ctx.evidence_store.read_events()
        calls = 0

        def paused(_session):
            nonlocal calls
            calls += 1
            if calls == 2:
                helper.facade.autodebug_cancel_case(case_id=helper.case_id)
            return True

        with patch.object(helper.adapter, "is_paused", side_effect=paused):
            result = helper.read()
        self.assertFalse(result["ok"], result)
        self.assertEqual(helper.ctx.evidence_store.read_events(), before)

    def test_cancelled_arm_does_not_issue_later_breakpoint_call(self):
        helper = self.fixture(armed=False)
        approval = self.stage_extra(helper, "cancel-at-arm")
        launch = helper.adapter.launch_or_attach

        def cancel(*args):
            session = launch(*args)
            helper.facade.autodebug_cancel_case(case_id="cancel-at-arm")
            return session

        with patch.object(helper.adapter, "launch_or_attach", side_effect=cancel):
            with patch.object(helper.adapter, "set_breakpoints", wraps=helper.adapter.set_breakpoints) as bind:
                result = self.arm_extra(helper, "cancel-at-arm", approval)
        bind.assert_not_called()
        self.assertFalse(result["ok"], result)
        self.assertEqual(helper.registry.all_sessions(), ())


    def test_concurrent_same_case_arm_has_one_launch_and_binding(self):
        helper = self.fixture(armed=False)
        approval = self.stage_extra(helper, "concurrent-arm")
        entered, release = threading.Event(), threading.Event()
        launch = helper.adapter.launch_or_attach
        results = []

        def blocked(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("synthetic launch was not released")
            return launch(*args)

        with patch.object(helper.adapter, "launch_or_attach", side_effect=blocked):
            worker = threading.Thread(target=lambda: results.append(self.arm_extra(helper, "concurrent-arm", approval)))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                rejected = self.arm_extra(helper, "concurrent-arm", approval)
                self.assertFalse(rejected["ok"], rejected)
                self.assertEqual(rejected["error"]["code"], "POLICY_LIMIT")
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"], results)
        self.assertEqual(helper.adapter.launch_or_attach_calls, 1)
        helper.adapter.simulate_stop(helper.facade._cases["concurrent-arm"].session.debug_session_id)
        waited = helper.facade.autodebug_wait_for_stop(case_id="concurrent-arm", timeout_seconds=1)
        self.assertTrue(waited["ok"], waited)

    def test_cancellation_during_mutation_is_reported_without_invalid_transition(self):
        for method in ("step", "continue_execution"):
            with self.subTest(method=method):
                helper = self.fixture()

                def cancel(*_args, helper=helper):
                    helper.facade.autodebug_cancel_case(case_id=helper.case_id)

                with patch.object(helper.adapter, method, side_effect=cancel):
                    if method == "step":
                        result = helper.facade.autodebug_step(case_id=helper.case_id, approval=helper.approval, kind="step_over")
                    else:
                        result = helper.facade.autodebug_continue(case_id=helper.case_id, approval=helper.approval)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["error"]["code"], "CANCELLED")
                self.assertEqual(helper.ctx.case.state.value, "cancelled")

    def test_revocation_during_inspection_records_nothing(self):
        # Every inspection re-verifies approval after each backend call, so
        # a revocation that lands mid-call must refuse the result and record
        # no evidence for it.
        for method in ("get_stack", "get_variables"):
            with self.subTest(method=method):
                helper = self.fixture()
                original = getattr(helper.adapter, method)
                recorded_before = len(helper.ctx.evidence_store.read_events())

                def revoke_then_answer(*args, helper=helper, original=original):
                    helper.facade._broker.revoke(helper.approval.token)
                    return original(*args)

                with patch.object(helper.adapter, method, side_effect=revoke_then_answer):
                    if method == "get_stack":
                        result = helper.facade.autodebug_get_stack(case_id=helper.case_id, frame_limit=1)
                    else:
                        result = helper.facade.autodebug_get_variables(
                            case_id=helper.case_id, frame_id="frame-0", selected_names=("local_var",),
                        )
                self.assertEqual(result["error"]["code"], "CANCELLED", result)
                self.assertEqual(len(helper.ctx.evidence_store.read_events()), recorded_before)

    def test_completion_cannot_race_an_inflight_inspection(self):
        helper = self.fixture()
        entered, release = threading.Event(), threading.Event()
        results = []

        def blocked(*_args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("synthetic inspection was not released")
            return {"local_var": "42"}

        with patch.object(helper.adapter, "get_variables", side_effect=blocked):
            worker = threading.Thread(target=lambda: results.append(helper.read()))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                result = self.complete(helper, evidence_ids=())
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["error"]["code"], "POLICY_LIMIT")
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0]["ok"], results)
        completed = self.complete(helper)
        self.assertTrue(completed["ok"], completed)
        self.assertEqual(set(completed["result"]["artifacts"]), {"case.json", "events.jsonl", "report.md"})

    def test_atomic_snapshot_failure_preserves_old_file_and_removes_temporary(self):
        helper = self.fixture()
        store = helper.ctx.evidence_store
        store.finalize(case_state="inspecting", report=None)
        previous = store.case_path.read_bytes()
        with self.assertRaisesRegex(OSError, "synthetic interrupted write"):
            with store._open_file("case.json", "w") as stream:
                stream.write("incomplete")
                raise OSError("synthetic interrupted write")
        self.assertEqual(store.case_path.read_bytes(), previous)
        self.assertEqual(list(store.case_dir.glob(".*.tmp")), [])
        # Fail while wrapping the new temporary file in a stream, on either backend.
        stream_seam = patch.object(_winfs, "_text_stream", side_effect=OSError("synthetic fdopen failure")) \
            if os.name == "nt" else patch.object(os, "fdopen", side_effect=OSError("synthetic fdopen failure"))
        with stream_seam:
            with self.assertRaisesRegex(OSError, "synthetic fdopen failure"):
                with store._open_file("case.json", "w"):
                    self.fail("failed file must not be yielded")
        self.assertEqual(list(store.case_dir.glob(".*.tmp")), [])
        self.assertEqual(store.case_path.read_bytes(), previous)

    def test_stack_descriptor_values_and_escaped_unicode_are_bounded(self):
        helper = self.fixture()
        frames = ({"locals": [{"name": "password", "value": "synthetic-private-value"}],
                   "unicode": ["\u2603" * 500] * 50},) * 50
        with patch.object(helper.adapter, "get_stack", return_value=frames):
            result = helper.facade.autodebug_get_stack(case_id=helper.case_id, frame_limit=50)
        self.assertTrue(result["ok"], result)
        encoded = json.dumps(result).encode("utf-8")
        self.assertNotIn(b"synthetic-private-value", encoded)
        self.assertLessEqual(len(encoded), 65536)


if __name__ == "__main__":
    unittest.main()
