"""B6 — structured report and export into the workspace (BR-09)."""

import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from autodebug.bridge.client import bridges_dir
from autodebug.cli import create_run_dir
from autodebug.evidence import REPORTS_FOLDER, write_workspace_report
from autodebug.server import build_dispatcher
from tests.fixtures.fake_bridge import FakeBridge
from tests.test_bridge_flow import CASE, TARGET
from tests.test_bridge_plan import bridge_plan

SECTIONS = ["## Problem", "## Reproduction", "## Debug timeline", "## Root cause", "## Solution",
            "## Verification", "## Uncertainties", "## Next steps", "## Evidence index"]


class StructuredReport(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name) / "AutoDebugDemo"
        self.workspace.mkdir()
        root = Path(tmp.name) / "evidence"
        self.run_dir = create_run_dir(root)
        self.fake = FakeBridge(bridges_dir(root), str(self.workspace))
        self.addCleanup(self.fake.close)
        self.dispatcher = build_dispatcher(self.run_dir, demo=False, bridges_folder=bridges_dir(root))

    def call(self, name, **arguments):
        arguments.setdefault("case_id", CASE)
        result = self.dispatcher.call(name, self.dispatcher.decode(name, arguments))
        self.assertTrue(result["ok"], result)
        return result["result"]

    def investigate(self, **plan_overrides) -> dict:
        self.call("autodebug_create_case", intake_source="developer_text", intake_description="area changes", target=TARGET)
        plan = asdict(bridge_plan(workspace_folder=str(self.workspace), **plan_overrides))
        self.call("autodebug_stage_plan", plan=json.loads(json.dumps(plan)))
        self.call("autodebug_request_approval")
        self.fake.answer("approve")
        self.call("autodebug_wait_for_approval", timeout_seconds=5)
        self.call("autodebug_arm_case", reviewed_configuration={}, process_running=False)
        self.call("autodebug_wait_for_stop", timeout_seconds=5)
        self.call("autodebug_get_variables", frame_id="1", selected_names=["i", "password"])
        self.call("autodebug_step", kind="step_over")
        events = (self.run_dir / CASE / "events.jsonl").read_text(encoding="utf-8").splitlines()
        return self.call(
            "autodebug_complete_case", confidence="confirmed", reproduced=True,
            evidence_ids=[json.loads(e)["evidence_id"] for e in events],
            problem="Moving a shape changes its area | e.g. 1.0 becomes 2.0.",
            root_cause_statement="polygon_area loops to len(points) - 1 and never adds the closing edge.",
            solution="Loop over every edge and wrap to the first point with (i + 1) % n.",
            verification="Applied the fix; python -m unittest passes.",
            causal_validation="The test fails before the fix and passes after it.",
            uncertainties=["Only the demo shapes were checked."], next_steps=["Add a test for a moved triangle."],
        )

    def test_report_has_every_section_and_is_written_to_the_workspace(self):
        done = self.investigate()
        path = Path(done["report_file"])
        self.assertEqual(path, self.workspace / REPORTS_FOLDER / f"{CASE}.md")
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text, (self.run_dir / CASE / "report.md").read_text(encoding="utf-8"))
        positions = [text.index(section) for section in SECTIONS]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("**CONFIRMED**", text)
        self.assertIn("- Launch configuration: `Debug tests`", text)
        self.assertIn("`geometry.py:15`", text)
        self.assertIn("| E0001 | Stopped | geometry.py:15 | breakpoint |", text)
        self.assertIn("| E0002 | Variable | frame 1 | i=0 |", text)
        self.assertIn("| E0004 | Stopped | geometry.py:12 | step |", text)
        self.assertIn("Reported by the AI agent; AutoDebug did not run this check.", text)
        self.assertIn("1.0 becomes 2.0", text)
        self.assertNotIn("hunter2", text)

    def test_table_cells_cannot_break_the_table(self):
        text = Path(self.investigate()["report_file"]).read_text(encoding="utf-8")
        timeline = text[text.index("## Debug timeline"):text.index("## Root cause")]
        for row in [line for line in timeline.splitlines() if line.startswith("| E")]:
            self.assertEqual(row.count(" | "), 3, row)

    def test_export_can_be_turned_off(self):
        done = self.investigate(report_to_workspace=False)
        self.assertNotIn("report_file", done)
        self.assertFalse((self.workspace / REPORTS_FOLDER).exists())
        self.assertIn("## Root cause", (self.run_dir / CASE / "report.md").read_text(encoding="utf-8"))


class WorkspaceExport(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)

    def test_never_overwrites(self):
        first = write_workspace_report(str(self.workspace), "CASE-1", "one")
        second = write_workspace_report(str(self.workspace), "CASE-1", "two")
        self.assertEqual((first.name, second.name), ("CASE-1.md", "CASE-1-2.md"))
        self.assertEqual(first.read_text(encoding="utf-8"), "one")

    def test_refuses_bad_targets(self):
        with self.assertRaises(ValueError):
            write_workspace_report(str(self.workspace / "missing"), "CASE-1", "x")
        with self.assertRaises(ValueError):
            write_workspace_report(str(self.workspace), "../escape", "x")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_refuses_a_linked_reports_folder(self):
        elsewhere = self.workspace / "elsewhere"
        elsewhere.mkdir()
        (self.workspace / REPORTS_FOLDER).symlink_to(elsewhere)
        with self.assertRaises(ValueError):
            write_workspace_report(str(self.workspace), "CASE-1", "x")
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_secrets_are_redacted_again(self):
        key = "sk-" + "A1b2C3d4" * 3
        path = write_workspace_report(str(self.workspace), "CASE-1", f"key {key} leaked")
        self.assertNotIn(key, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
