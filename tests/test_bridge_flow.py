"""B4 — the whole bridge flow through the MCP dispatcher (BR-04, BR-06–BR-08).

The fake bridge stands in for VS Code: `answer()` is the developer's click.
"""

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from autodebug.approvals import APPROVED_BACKEND_KINDS, BRIDGE_BACKEND_KIND
from autodebug.bridge.client import bridges_dir
from autodebug.cli import create_run_dir
from autodebug.server import build_dispatcher
from tests.fixtures.fake_bridge import FakeBridge
from tests.test_bridge_plan import WORKSPACE, bridge_plan

CASE = "DEMO-AREA-MOVE"
TARGET = {"host_id": "local-windows", "ide": "vscode", "debug_session_id": None, "pid": None}


class BridgeFlow(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "evidence"
        self.run_dir = create_run_dir(root)
        self.fake = FakeBridge(bridges_dir(root), WORKSPACE)
        self.addCleanup(self.fake.close)
        self.dispatcher = build_dispatcher(self.run_dir, demo=False, bridges_folder=bridges_dir(root))
        self.addCleanup(lambda: self.call("autodebug_cancel_case"))

    def call(self, name: str, **arguments) -> dict:
        arguments.setdefault("case_id", CASE)
        return self.dispatcher.call(name, self.dispatcher.decode(name, arguments))

    def ok(self, name: str, **arguments) -> dict:
        result = self.call(name, **arguments)
        self.assertTrue(result["ok"], result)
        return result["result"]

    def assertRefused(self, code: str, name: str, **arguments) -> dict:
        result = self.call(name, **arguments)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], code, result)
        return result

    def stage(self, **plan_overrides) -> None:
        self.ok("autodebug_create_case", intake_source="developer_text",
                intake_description="moving a shape changes its area", target=TARGET)
        plan = json.loads(json.dumps(asdict(bridge_plan(**plan_overrides))))
        self.ok("autodebug_stage_plan", plan=plan)

    def approve(self) -> None:
        self.stage()
        self.assertEqual(self.ok("autodebug_request_approval")["status"], "pending")
        self.assertEqual(self.ok("autodebug_wait_for_approval", timeout_seconds=0.3)["status"], "pending")
        self.fake.answer("approve")
        self.assertEqual(self.ok("autodebug_wait_for_approval", timeout_seconds=5)["status"], "approved")

    def arm(self) -> dict:
        self.approve()
        return self.ok("autodebug_arm_case", reviewed_configuration={}, process_running=False)


class Approval(BridgeFlow):
    def test_health_reports_the_bridge_gate(self):
        health = self.dispatcher.call("autodebug_health", {})["result"]
        self.assertEqual(health["backend_mode"], "vscode-bridge")
        self.assertIn("Approve", health["security_gate"])

    def test_allowlist_is_exactly_fake_and_bridge(self):
        self.assertEqual(APPROVED_BACKEND_KINDS, frozenset({"fake", BRIDGE_BACKEND_KIND}))

    def test_nothing_can_be_armed_before_the_click(self):
        self.stage()
        self.assertRefused("NOT_APPROVED", "autodebug_arm_case", reviewed_configuration={}, process_running=False)
        self.ok("autodebug_request_approval")
        self.assertRefused("NOT_APPROVED", "autodebug_arm_case", reviewed_configuration={}, process_running=False)
        self.assertNotIn("launch", [op for op, _ in self.fake.calls])

    def test_dialog_shows_the_whole_plan(self):
        self.stage()
        digest = self.ok("autodebug_request_approval")["digest_sha256"]
        (request,) = self.fake.requests
        self.assertEqual(request["digest"], digest)
        summary = request["summary"]
        self.assertEqual(summary["launch_configuration"], "Debug tests")
        self.assertEqual(summary["breakpoints"], ["geometry.py:15"])
        self.assertEqual(summary["workspace_folder"], WORKSPACE)
        self.assertEqual(summary["max_steps"], 20)

    def test_denial_runs_nothing_and_a_new_request_is_allowed(self):
        self.stage()
        self.ok("autodebug_request_approval")
        self.fake.answer("deny")
        self.assertEqual(self.ok("autodebug_wait_for_approval", timeout_seconds=5)["status"], "denied")
        self.assertRefused("NOT_APPROVED", "autodebug_arm_case", reviewed_configuration={}, process_running=False)
        self.ok("autodebug_request_approval")
        self.assertEqual(len(self.fake.requests), 2)

    def test_wait_needs_a_request_and_bounds_its_timeout(self):
        self.stage()
        self.assertRefused("NOT_APPROVED", "autodebug_wait_for_approval", timeout_seconds=1)
        with self.assertRaises(Exception):
            self.dispatcher.decode("autodebug_wait_for_approval", {"case_id": CASE, "timeout_seconds": 31})

    def test_no_token_or_approval_id_reaches_the_agent(self):
        self.approve()
        approval_id = next(r["approval_id"] for r in self.fake.approvals.values())
        transcript = json.dumps([self.ok("autodebug_wait_for_approval", timeout_seconds=1),
                                 self.ok("autodebug_case_status"), self.ok("autodebug_get_plan")])
        for secret in (self.fake.token, approval_id, self.dispatcher._local_approvals[CASE].token):
            self.assertNotIn(secret, transcript)

    def test_other_ides_are_not_offered(self):
        result = self.call("autodebug_create_case", intake_source="developer_text", intake_description="x",
                           target={**TARGET, "ide": "clion"})
        self.assertEqual(result["error"]["code"], "CAPABILITY_UNSUPPORTED")

    def test_missing_bridge_window(self):
        self.stage(workspace_folder="C:\\not-open")
        result = self.assertRefused("BACKEND_UNAVAILABLE", "autodebug_request_approval")
        self.assertIn("autodebug bridge install", result["error"]["message"])


class Debugging(BridgeFlow):
    def test_full_investigation(self):
        armed = self.arm()
        self.assertEqual(armed["session"]["ide_instance_id"], "window-1")
        stop = self.ok("autodebug_wait_for_stop", timeout_seconds=5)
        self.assertEqual((stop["reason"], stop["location"]), ("breakpoint", "geometry.py:15"))
        frames = self.ok("autodebug_get_stack", frame_limit=5)["frames"]
        self.assertEqual(frames[0]["name"], "polygon_area")
        variables = self.ok("autodebug_get_variables", frame_id="1", selected_names=["i", "total", "password"])
        self.assertEqual(variables["variables"]["i"], "0")
        self.assertNotIn("hunter2", json.dumps(variables))
        step = self.ok("autodebug_step", kind="step_over")
        self.assertEqual((step["steps_taken"], step["location"], step["reason"]), (1, "geometry.py:12", "step"))
        self.ok("autodebug_continue")
        self.assertEqual(self.ok("autodebug_wait_for_stop", timeout_seconds=5)["location"], "geometry.py:15")
        events = (self.run_dir / CASE / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("step at geometry.py:12", events)
        self.assertNotIn("hunter2", events)
        ids = [json.loads(line)["evidence_id"] for line in events.splitlines()]
        done = self.ok("autodebug_complete_case", root_cause_statement="The loop skips the closing edge.",
                       confidence="likely", evidence_ids=ids, reproduced=True)
        self.assertEqual(done["state"], "finalized")
        self.assertTrue(self.fake.ended)
        self.assertEqual(self.fake.calls[-1][0], "end")

    def test_approval_record_is_bound_to_the_bridge_click(self):
        self.approve()
        self.ok("autodebug_arm_case", reviewed_configuration={}, process_running=False)
        self.ok("autodebug_wait_for_stop", timeout_seconds=5)
        record = self.dispatcher._local_approvals[CASE]
        self.assertIn("backend:vscode-bridge", record.scope)
        self.assertIn("developer clicked Approve", record.reviewer)

    def test_cancel_ends_the_ide_session(self):
        self.arm()
        self.ok("autodebug_cancel_case")
        self.assertTrue(self.fake.ended)

    def test_program_exit_marks_the_case_incomplete(self):
        self.arm()
        self.ok("autodebug_wait_for_stop", timeout_seconds=5)
        for _ in range(2):  # the second and third pass through line 15
            self.ok("autodebug_continue")
            self.ok("autodebug_wait_for_stop", timeout_seconds=5)
        self.ok("autodebug_continue")  # no breakpoint left: the program exits
        result = self.assertRefused("SESSION_STALE", "autodebug_wait_for_stop", timeout_seconds=1)
        self.assertIn("exited", result["error"]["message"])


class DemoModeHasNoBridge(unittest.TestCase):
    def test_approval_tools_are_unsupported_in_the_demo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dispatcher = build_dispatcher(create_run_dir(Path(tmp.name) / "e"), demo=True)
        for name, args in (("autodebug_request_approval", {}), ("autodebug_wait_for_approval", {"timeout_seconds": 1})):
            result = dispatcher.call(name, dispatcher.decode(name, {"case_id": "AUTODEBUG-DEMO", **args}))
            self.assertEqual(result["error"]["code"], "CAPABILITY_UNSUPPORTED")
        dispatcher.facade.autodebug_cancel_case(case_id="AUTODEBUG-DEMO")


if __name__ == "__main__":
    unittest.main()
