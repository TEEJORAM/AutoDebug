"""Keep examples/AutoDebugDemo truthful: areas stay stable when shapes move,
and the sample plan is a valid AutoDebug plan."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from autodebug.plans import stage_plan
from autodebug.server import TOOLS, _decode

DEMO = Path(__file__).resolve().parents[1] / "examples" / "AutoDebugDemo"
FIXED_LOOP = """    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]"""


def run_demo_tests(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-m", "unittest", "-v"], cwd=folder,
                          capture_output=True, text=True, timeout=60, check=False)


class AutoDebugDemoTests(unittest.TestCase):
    def test_areas_do_not_change_when_moved(self):
        result = run_demo_tests(DEMO)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = subprocess.run([sys.executable, "-B", "report.py"], cwd=DEMO,
                                capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(report.returncode, 0, report.stdout)
        self.assertIn("0 of 3 shapes change area when moved.", report.stdout)
        self.assertNotIn("WRONG", report.stdout)

    def test_closing_edge_is_in_the_loop(self):
        source = (DEMO / "geometry.py").read_text(encoding="utf-8")
        self.assertIn(FIXED_LOOP, source)

    def test_sample_plan_is_valid_and_targets_the_bug(self):
        raw = json.loads((DEMO / "autodebug-plan.json").read_text(encoding="utf-8"))
        plan = stage_plan(_decode(raw, TOOLS["autodebug_stage_plan"].parameters["plan"]))
        self.assertEqual(len(plan.digest_sha256), 64)
        (breakpoint,) = plan.breakpoints
        lines = (DEMO / breakpoint.file).read_text(encoding="utf-8").splitlines()
        self.assertIn("total +=", lines[breakpoint.line - 1])

    def test_cpp_twin_includes_the_closing_edge(self):
        source = (DEMO / "cpp" / "geometry.cpp").read_text(encoding="utf-8")
        self.assertIn("for (std::size_t i = 0; i < n; ++i)", source)
        self.assertIn("const auto [x2, y2] = points[(i + 1) % n];", source)


if __name__ == "__main__":
    unittest.main()
