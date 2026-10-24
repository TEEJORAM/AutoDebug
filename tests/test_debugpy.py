"""AutoDebugDemo's bug found through the extension core and the real Python
debugger (debugpy) over the real Debug Adapter Protocol. Only the IDE window is
a stand-in. Skipped without Node.js and debugpy."""

import importlib.util
import sys
import unittest
from pathlib import Path

from tests.test_extension import NODE, HarnessTest

HAS_DEBUGPY = importlib.util.find_spec("debugpy") is not None


@unittest.skipIf(NODE is None or not HAS_DEBUGPY, "needs Node.js and debugpy")
class RealDebugpy(HarnessTest):
    debugpy = sys.executable

    def test_finds_the_skipped_closing_edge(self):
        _, first = self.approved()
        self.assertEqual((first["status"], first["location"], first["reason"]), ("paused", "geometry.py:15", "breakpoint"))
        self.assertTrue(first["breakpoints"][0]["verified"])
        values = {v["name"]: v["value"] for v in first["variables"]}
        # unittest runs test_area_does_not_change_when_moved first: the moved square.
        self.assertEqual((values["i"], values["total"]), ("0", "0.0"))
        self.assertEqual(values["points"], "[(2, 1), (3, 1), (3, 2), (2, 2)]")

        step = self.debugger.step("over")
        self.assertEqual(step["location"], "geometry.py:12")
        self.assertIn({"name": "total", "before": "0.0", "after": "-1.0"}, step["changed"])

        trace = self.debugger.trace("geometry.py", 15, ["i", "total"], hits=2)
        self.assertEqual([(r["i"], r["total"]) for r in trace["rows"]], [("1", "-1.0"), ("2", "2.0")])

        out = self.debugger.step("over", count=2)
        self.assertEqual(out["path"], ["geometry.py:12", "geometry.py:16"], "the loop ends after i = 2: no closing edge")
        self.assertEqual(self.debugger.stack()["frames"][0]["function"], "polygon_area")

        self.debugger.stop_session()
        report = Path(self.debugger.write_report(
            title="Moving a shape changes its area", problem="A moved unit square reports area 2.0 instead of 1.0.",
            root_cause="polygon_area loops i over range(len(points) - 1), so the edge from the last corner back to "
                       "the first is never added (the trace shows i stops at 2 for 4 corners).",
            solution="Loop over range(n) and use points[(i + 1) % n].", confidence="likely",
        )["report_file"])
        text = report.read_text(encoding="utf-8")
        self.assertIn("geometry.py:12 → geometry.py:16", text)
        self.assertIn("i=1, total=-1.0", text)


if __name__ == "__main__":
    unittest.main()
