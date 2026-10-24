"""B3 — VSCodeBridgeAdapter against the fake bridge (BR-02, BR-06, BR-07, BR-08)."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from autodebug.adapters.vscode_bridge import VSCodeBridgeAdapter
from autodebug.bridge.client import bridges_dir
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.models import Breakpoint
from autodebug.plans import bind_resolved_inputs, stage_plan
from tests.fixtures.fake_bridge import DEMO_LAUNCH, FakeBridge
from tests.test_bridge_plan import WORKSPACE, bridge_plan


class BridgeAdapterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = bridges_dir(Path(tmp.name))
        self.fake = self.make_fake()
        self.adapter = VSCodeBridgeAdapter("vscode", self.folder)
        self.addCleanup(self.adapter.close)
        self.plan = stage_plan(bridge_plan())

    def make_fake(self, **kwargs) -> FakeBridge:
        fake = FakeBridge(self.folder, kwargs.pop("workspace", WORKSPACE), **kwargs)
        self.addCleanup(fake.close)
        return fake

    def assertCode(self, code, function, *args):
        with self.assertRaises(AutoDebugError) as caught:
            function(*args)
        self.assertIs(caught.exception.detail.code, code)
        return caught.exception

    def approve(self):
        bound = bind_resolved_inputs(self.plan, self.adapter.resolve(self.plan))
        self.adapter.bind(bound)
        request = self.adapter.request_approval(bound.case_id, {"title": "test"})
        self.fake.answer("approve")
        self.assertEqual(self.adapter.approval_status(request), "approved")
        return bound

    def launch(self):
        plan = self.approve()
        return plan, self.adapter.launch_or_attach(plan.target, {})


class Resolve(BridgeAdapterTest):
    def test_resolves_the_named_configuration_and_files(self):
        inputs = dict(self.adapter.resolve(self.plan))
        self.assertEqual(sorted(inputs), ["file:geometry.py", "launch"])
        self.assertEqual(self.fake.calls[-1][0], "resolve_plan")
        self.assertEqual(self.adapter.window_id, "window-1")

    def test_no_window_for_the_workspace(self):
        error = self.assertCode(ErrorCode.BACKEND_UNAVAILABLE, self.adapter.resolve,
                                replace(self.plan, workspace_folder="C:\\elsewhere"))
        self.assertIn("autodebug bridge install", error.detail.message)

    def test_cursor_adapter_does_not_use_a_vscode_window(self):
        cursor = VSCodeBridgeAdapter("cursor", self.folder)
        self.addCleanup(cursor.close)
        plan = replace(self.plan, target=replace(self.plan.target, ide="cursor"))
        self.assertCode(ErrorCode.BACKEND_UNAVAILABLE, cursor.resolve, plan)

    def test_missing_configuration_or_file(self):
        self.assertCode(ErrorCode.TARGET_MISMATCH, self.adapter.resolve,
                        replace(self.plan, launch_configuration_name="Nope"))
        self.assertCode(ErrorCode.TARGET_MISMATCH, self.adapter.resolve,
                        replace(self.plan, breakpoints=(Breakpoint("missing.py", 1),)))

    def test_attach_configuration_is_refused(self):
        self.fake.launch_configs = {"Debug tests": {**DEMO_LAUNCH, "request": "attach"}}
        self.assertCode(ErrorCode.PLAN_CHANGED, self.adapter.resolve, self.plan)

    def test_only_other_ides_are_refused(self):
        with self.assertRaises(ValueError):
            VSCodeBridgeAdapter("clion", self.folder)


class Approval(BridgeAdapterTest):
    def test_nothing_runs_before_approval(self):
        plan = bind_resolved_inputs(self.plan, self.adapter.resolve(self.plan))
        self.adapter.bind(plan)
        self.assertCode(ErrorCode.NOT_APPROVED, self.adapter.launch_or_attach, plan.target, {})
        self.assertNotIn("launch", [op for op, _ in self.fake.calls])

    def test_pending_then_denied(self):
        plan = bind_resolved_inputs(self.plan, self.adapter.resolve(self.plan))
        self.adapter.bind(plan)
        request = self.adapter.request_approval(plan.case_id, {"title": "t"})
        self.assertEqual(self.fake.requests[-1]["digest"], plan.digest_sha256)
        self.assertEqual(self.adapter.approval_status(request), "pending")
        self.fake.answer("deny")
        self.assertEqual(self.adapter.approval_status(request), "denied")
        self.assertCode(ErrorCode.NOT_APPROVED, self.adapter.launch_or_attach, plan.target, {})

    def test_the_bridge_rejects_a_forged_approval_id(self):
        plan = bind_resolved_inputs(self.plan, self.adapter.resolve(self.plan))
        self.adapter.bind(plan)
        self.adapter._approval_id = "forged"
        self.assertCode(ErrorCode.NOT_APPROVED, self.adapter.launch_or_attach, plan.target, {})


class Debugging(BridgeAdapterTest):
    def test_launch_reports_full_identity(self):
        plan, session = self.launch()
        self.assertEqual((session.host_id, session.ide, session.ide_instance_id), ("local-windows", "vscode", "window-1"))
        self.assertEqual((session.debug_session_id, session.pid), ("dap-session-1", 4242))
        self.assertTrue(session.process_start_id)
        self.assertEqual(self.fake.calls[-1], ("launch", {
            "breakpoints": [{"file": "geometry.py", "line": 15}], "approval_id": self.adapter._approval_id}))

    def test_breakpoint_binding(self):
        plan, session = self.launch()
        (result,) = self.adapter.set_breakpoints(session, plan.breakpoints)
        self.assertEqual((result.file, result.line, result.bound), ("geometry.py", 15, True))

    def test_unbound_breakpoint_is_reported(self):
        self.fake.bind = False
        plan, session = self.launch()
        (result,) = self.adapter.set_breakpoints(session, plan.breakpoints)
        self.assertFalse(result.bound)
        self.assertEqual(result.reason, "unverified")

    def test_stop_stack_variables_and_steps(self):
        plan, session = self.launch()
        stop = self.adapter.get_stop(session)
        self.assertEqual((stop.reason, stop.breakpoint_file, stop.breakpoint_line, stop.location),
                         ("breakpoint", "geometry.py", 15, "geometry.py:15"))
        frames = self.adapter.get_stack(session, 1)
        self.assertEqual(frames, ({"frame": "1", "name": "polygon_area", "file": "geometry.py", "line": 15},))
        self.assertEqual(self.adapter.get_variables(session, "1", ("i", "total", "nope")), {"i": "0", "total": "0.0"})
        self.assertIn({"name": "password", "type": "str"}, self.adapter.list_variables(session, "1"))
        self.adapter.step(session, "step_over")
        self.assertEqual(self.fake.calls[-1][1]["kind"], "next")
        after = self.adapter.get_stop(session)
        self.assertEqual((after.reason, after.location, after.breakpoint_file), ("step", "geometry.py:12", None))
        self.assertNotEqual(after.stop_id, stop.stop_id)
        self.adapter.continue_execution(session)
        self.assertEqual(self.adapter.get_stop(session).location, "geometry.py:15")
        self.adapter.continue_execution(session)  # the third pass through line 15
        self.adapter.continue_execution(session)  # no breakpoint left: the program exits
        self.assertCode(ErrorCode.SESSION_STALE, self.adapter.get_stop, session)

    def test_breakpoint_outside_the_plan_is_labelled(self):
        plan, session = self.launch()
        original = self.fake.op_stop_state
        self.fake.op_stop_state = lambda args: {**original(args), "planned_breakpoint": None}
        stop = self.adapter.get_stop(session)
        self.assertEqual(stop.reason, "breakpoint not in the plan")
        self.assertIsNone(stop.breakpoint_file)

    def test_unknown_step_kind(self):
        plan, session = self.launch()
        self.assertCode(ErrorCode.CAPABILITY_UNSUPPORTED, self.adapter.step, session, "step_back")

    def test_foreign_session_is_stale(self):
        plan, session = self.launch()
        self.assertCode(ErrorCode.SESSION_STALE, self.adapter.get_stack, replace(session, pid=1), 5)

    def test_disconnect_ends_the_session(self):
        plan, session = self.launch()
        self.adapter.disconnect(session)
        self.assertEqual(self.fake.calls[-1][0], "end")
        self.assertTrue(self.fake.ended)
        self.assertEqual(self.adapter.list_sessions(), ())
        self.assertCode(ErrorCode.SESSION_STALE, self.adapter.get_stop, session)


if __name__ == "__main__":
    unittest.main()
