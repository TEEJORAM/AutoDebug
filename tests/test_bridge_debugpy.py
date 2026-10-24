"""B9 — the AutoDebugDemo bug, found through the extension core and the real
Python debugger (debugpy) speaking the real Debug Adapter Protocol.

Only the IDE's window and dialog are stand-ins (tests/fixtures/vscode_harness.js).
Skipped unless Node.js and debugpy are installed.
"""

import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path

from tests.test_bridge_extension import NODE, ExtensionCore

HAS_DEBUGPY = importlib.util.find_spec("debugpy") is not None


@unittest.skipIf(NODE is None or not HAS_DEBUGPY, "needs Node.js and debugpy")
class RealDebugpy(ExtensionCore):
    debugpy_python = sys.executable

    def test_demo_bug_through_real_debugpy(self):
        self.approve()
        self.ok("autodebug_arm_case", reviewed_configuration={}, process_running=False)
        stop = self.ok("autodebug_wait_for_stop", timeout_seconds=30)
        self.assertEqual((stop["reason"], stop["location"]), ("breakpoint", "geometry.py:15"))
        status = self.ok("autodebug_case_status")
        self.assertTrue(status["bound_breakpoints"][0]["bound"], status)
        self.assertGreater(status["session"]["pid"], 0)

        frames = self.ok("autodebug_get_stack", frame_limit=10)["frames"]
        self.assertEqual((frames[0]["name"], frames[0]["file"], frames[0]["line"]), ("polygon_area", "geometry.py", 15))
        self.assertIn("test_geometry.py", [f["file"] for f in frames])
        top = frames[0]["frame"]
        names = {v["name"] for v in self.ok("autodebug_list_variables", frame_id=top)["variables"]}
        self.assertTrue({"points", "total", "i", "x1", "y1", "x2", "y2"} <= names, names)

        def values():
            return self.ok("autodebug_get_variables", frame_id=self.ok("autodebug_get_stack", frame_limit=1)["frames"][0]["frame"],
                           selected_names=["i", "total", "points"])["variables"]

        first = values()
        self.assertEqual((first["i"], first["total"]), ("0", "0.0"))
        # unittest runs test_area_does_not_change_when_moved first: the moved square.
        self.assertEqual(first["points"], "[(2, 1), (3, 1), (3, 2), (2, 2)]")

        step = self.ok("autodebug_step", kind="step_over")
        self.assertEqual((step["reason"], step["location"]), ("step", "geometry.py:12"))
        self.ok("autodebug_continue")
        self.assertEqual(self.ok("autodebug_wait_for_stop", timeout_seconds=30)["location"], "geometry.py:15")
        self.assertEqual(values()["i"], "1")
        self.ok("autodebug_continue")
        self.ok("autodebug_wait_for_stop", timeout_seconds=30)
        third = values()
        self.assertEqual(third["i"], "2")  # the last pass: i stops at len(points) - 2, never 3
        step_in = self.ok("autodebug_step", kind="step_over")
        self.assertEqual(step_in["location"], "geometry.py:12")
        out = self.ok("autodebug_step", kind="step_over")
        self.assertEqual(out["location"], "geometry.py:16", "the loop ends without visiting the closing edge")

        events = [json.loads(line) for line in (self.run_dir / "DEMO-AREA-MOVE" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        done = self.ok("autodebug_complete_case", confidence="likely", reproduced=True,
                       evidence_ids=[e["evidence_id"] for e in events],
                       problem="Moving a shape changes its area.",
                       root_cause_statement="polygon_area loops while i < len(points) - 1, so the edge from the last "
                                            "corner back to the first is never added.",
                       solution="Loop over all n edges and use points[(i + 1) % n] as the second corner.")
        report = Path(done["report_file"]).read_text(encoding="utf-8")
        self.assertIn("| Stopped | geometry.py:16 | step |", report)
        self.expect("LOG debug session stopped", timeout=15)


if __name__ == "__main__":
    unittest.main()
