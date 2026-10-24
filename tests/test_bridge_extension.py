"""B8 — the real extension core (bridge-core.js) driven over the real protocol.

`tests/fixtures/vscode_harness.js` stands in for VS Code and a debug session;
the Python side is the real server. Skipped when Node.js is not installed.
"""

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from autodebug.bridge.client import BridgeConnection, bridges_dir, discover
from autodebug.cli import create_run_dir
from autodebug.models import CasePolicy
from autodebug.server import build_dispatcher
from tests.test_bridge_flow import CASE, TARGET
from tests.test_bridge_plan import bridge_plan

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "AutoDebugDemo"
HARNESS = ROOT / "tests" / "fixtures" / "vscode_harness.js"
NODE = shutil.which("node")
TASKS = {"version": "2.0.0", "tasks": [{"label": "build demo", "type": "shell", "command": "python", "args": ["-m", "compileall", "."]}]}


@unittest.skipIf(NODE is None, "Node.js is not installed")
class ExtensionCore(unittest.TestCase):
    build_exit = 0
    #: Python whose debugpy the harness runs; None means the scripted session.
    debugpy_python: str | None = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name) / "AutoDebugDemo"
        shutil.copytree(DEMO, self.workspace, ignore=shutil.ignore_patterns("__pycache__", "mcp.json"))
        (self.workspace / ".vscode" / "tasks.json").write_text(json.dumps(TASKS), encoding="utf-8")
        root = Path(tmp.name) / "evidence"
        self.run_dir = create_run_dir(root)
        self.folder = bridges_dir(root)
        self.lines: queue.Queue[str] = queue.Queue()
        env = dict(os.environ, HARNESS_BUILD_EXIT=str(self.build_exit))
        if self.debugpy_python:
            env["HARNESS_DEBUGPY"] = self.debugpy_python
        self.node = subprocess.Popen([NODE, str(HARNESS), str(self.folder), str(self.workspace)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        self.addCleanup(self.stop_node)
        threading.Thread(target=lambda: [self.lines.put(line.rstrip("\n")) for line in self.node.stdout], daemon=True).start()
        self.expect("READY")
        self.dispatcher = build_dispatcher(self.run_dir, demo=False, bridges_folder=self.folder)

    def stop_node(self):
        if self.node.poll() is None:
            self.dispatcher.call("autodebug_cancel_case", {"case_id": CASE})
            self.send("exit")
            try:
                self.node.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.node.kill()
        self.node.stdout.close()
        self.node.stdin.close()

    def send(self, command: str) -> None:
        self.node.stdin.write(command + "\n")
        self.node.stdin.flush()

    def expect(self, prefix: str, timeout: float = 10) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        self.fail(f"harness never printed {prefix!r}")

    def call(self, name, **arguments):
        arguments.setdefault("case_id", CASE)
        return self.dispatcher.call(name, self.dispatcher.decode(name, arguments))

    def ok(self, name, **arguments):
        result = self.call(name, **arguments)
        self.assertTrue(result["ok"], result)
        return result["result"]

    def stage(self, **overrides):
        self.ok("autodebug_create_case", intake_source="developer_text", intake_description="area changes", target=TARGET)
        plan = bridge_plan(workspace_folder=str(self.workspace),
                           policy=CasePolicy(max_steps=20, max_inspection_seconds=600, max_operation_seconds=20), **overrides)
        self.ok("autodebug_stage_plan", plan=json.loads(json.dumps(asdict(plan))))
        self.ok("autodebug_request_approval")
        return json.loads(self.expect("DIALOG"))

    def approve(self, **overrides):
        dialog = self.stage(**overrides)
        self.send("approve")
        deadline = time.monotonic() + 10
        while self.ok("autodebug_wait_for_approval", timeout_seconds=1)["status"] != "approved":
            self.assertLess(time.monotonic(), deadline)
        return dialog


class Investigation(ExtensionCore):
    def test_dialog_lists_exactly_what_will_run(self):
        dialog = self.stage()
        self.assertTrue(dialog["modal"])
        self.assertEqual(dialog["items"], ["Approve", "Deny"])
        self.assertIn('"Debug tests"', dialog["detail"])
        self.assertIn("Stop at: geometry.py:15", dialog["detail"])
        self.assertIn("up to 20 steps", dialog["detail"])
        self.assertIn(str(self.workspace), dialog["detail"])

    def test_full_investigation_through_the_extension(self):
        self.approve()
        self.ok("autodebug_arm_case", reviewed_configuration={}, process_running=False)
        stop = self.ok("autodebug_wait_for_stop", timeout_seconds=10)
        self.assertEqual((stop["reason"], stop["location"]), ("breakpoint", "geometry.py:15"))
        status = self.ok("autodebug_case_status")
        self.assertEqual(status["bound_breakpoints"][0]["bound"], True)
        self.assertEqual(status["session"]["pid"], 4242)
        frames = self.ok("autodebug_get_stack", frame_limit=5)["frames"]
        self.assertEqual([f["file"] for f in frames], ["geometry.py", "test_geometry.py"])
        names = [v["name"] for v in self.ok("autodebug_list_variables", frame_id=frames[0]["frame"])["variables"]]
        self.assertEqual(names, ["i", "total", "password"])
        values = self.ok("autodebug_get_variables", frame_id=frames[0]["frame"], selected_names=["i", "password"])
        self.assertEqual(values["variables"]["i"], "0")
        self.assertNotIn("hunter2", json.dumps(values))
        step = self.ok("autodebug_step", kind="step_over")
        self.assertEqual((step["reason"], step["location"]), ("step", "geometry.py:12"))
        self.ok("autodebug_continue")
        self.assertEqual(self.ok("autodebug_wait_for_stop", timeout_seconds=10)["location"], "geometry.py:15")
        events = [json.loads(line) for line in (self.run_dir / CASE / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        done = self.ok("autodebug_complete_case", confidence="likely", reproduced=True,
                       evidence_ids=[e["evidence_id"] for e in events],
                       problem="Moving a shape changes its area.", root_cause_statement="The closing edge is skipped.",
                       solution="Wrap the loop with (i + 1) % n.")
        self.assertTrue(Path(done["report_file"]).is_file())
        self.expect("LOG debug session stopped")
        self.send("breakpoints")
        self.assertEqual(self.expect("BREAKPOINTS"), "0")

    def test_denial_launches_nothing(self):
        self.stage()
        self.send("deny")
        deadline = time.monotonic() + 10
        while (status := self.ok("autodebug_wait_for_approval", timeout_seconds=1)["status"]) == "pending":
            self.assertLess(time.monotonic(), deadline)
        self.assertEqual(status, "denied")
        result = self.call("autodebug_arm_case", reviewed_configuration={}, process_running=False)
        self.assertEqual(result["error"]["code"], "NOT_APPROVED")

    def test_editing_the_launch_configuration_after_approval_blocks_the_launch(self):
        self.approve()
        launch = self.workspace / ".vscode" / "launch.json"
        launch.write_text(launch.read_text(encoding="utf-8").replace('"-v"', '"-q"'), encoding="utf-8")
        result = self.call("autodebug_arm_case", reviewed_configuration={}, process_running=False)
        self.assertEqual(result["error"]["code"], "PLAN_CHANGED")

    def test_build_task_runs_in_the_ide(self):
        self.approve(build_task="build demo")
        self.ok("autodebug_run_build")
        deadline = time.monotonic() + 10
        while self.ok("autodebug_wait_for_build", timeout_seconds=1)["status"] != "succeeded":
            self.assertLess(time.monotonic(), deadline)
        self.ok("autodebug_arm_case", reviewed_configuration={}, process_running=False)

    def test_wrong_token_and_unknown_operations(self):
        (info,) = discover(self.folder)
        with self.assertRaises(Exception):
            BridgeConnection(replace(info, token="0" * 64))
        connection = BridgeConnection(info)
        self.addCleanup(connection.close)
        for op in ("evaluate", "setVariable"):
            with self.assertRaises(Exception) as caught:
                connection.request(op, {"expression": "1"})
            self.assertEqual(caught.exception.detail.code.value, "CAPABILITY_UNSUPPORTED")
        with self.assertRaises(Exception) as caught:
            connection.request("launch", {"approval_id": "forged"})
        self.assertEqual(caught.exception.detail.code.value, "NOT_APPROVED")

    def test_connection_file_is_removed_when_the_window_closes(self):
        (info,) = discover(self.folder)
        self.send("exit")
        self.node.wait(timeout=5)
        self.assertEqual(discover(self.folder), ())


class FailedBuild(ExtensionCore):
    build_exit = 2

    def test_failed_build_launches_nothing(self):
        self.approve(build_task="build demo")
        self.ok("autodebug_run_build")
        deadline = time.monotonic() + 10
        while True:
            result = self.call("autodebug_wait_for_build", timeout_seconds=1)
            if not result["ok"]:
                break
            self.assertLess(time.monotonic(), deadline)
        self.assertEqual(result["error"]["code"], "BUILD_FAILED")
        self.assertIn("IDE terminal", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
