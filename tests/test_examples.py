"""Keep examples/AutoDebugDemo truthful: the bug reproduces, the documented
fix works, and the sample plan is a valid AutoDebug plan."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from autodebug.plans import stage_plan
from autodebug.server import TOOLS, _decode

DEMO = Path(__file__).resolve().parents[1] / "examples" / "AutoDebugDemo"
BUGGY_LOOP = """    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]"""
FIXED_LOOP = """    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]"""


def run_demo_tests(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-m", "unittest", "-v"], cwd=folder,
                          capture_output=True, text=True, timeout=60, check=False)


class AutoDebugDemoTests(unittest.TestCase):
    def test_bug_reproduces(self):
        result = run_demo_tests(DEMO)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("AssertionError: 2.0 != 1.0", result.stderr)
        report = subprocess.run([sys.executable, "-B", "report.py"], cwd=DEMO,
                                capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(report.returncode, 1)
        self.assertIn("3 of 3 shapes change area when moved.", report.stdout)

    def test_documented_fix_works(self):
        source = (DEMO / "geometry.py").read_text(encoding="utf-8")
        self.assertIn(BUGGY_LOOP, source)
        self.assertIn(FIXED_LOOP, (DEMO / "README.md").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            fixed = Path(tmp)
            for name in ("geometry.py", "report.py", "test_geometry.py"):
                shutil.copy(DEMO / name, fixed / name)
            (fixed / "geometry.py").write_text(source.replace(BUGGY_LOOP, FIXED_LOOP), encoding="utf-8")
            result = run_demo_tests(fixed)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_sample_plan_is_valid_and_targets_the_bug(self):
        raw = json.loads((DEMO / "autodebug-plan.json").read_text(encoding="utf-8"))
        plan = stage_plan(_decode(raw, TOOLS["autodebug_stage_plan"].parameters["plan"]))
        self.assertEqual(len(plan.digest_sha256), 64)
        (breakpoint,) = plan.breakpoints
        lines = (DEMO / breakpoint.file).read_text(encoding="utf-8").splitlines()
        self.assertIn("total +=", lines[breakpoint.line - 1])

    def test_cpp_twin_has_the_same_bug_line(self):
        source = (DEMO / "cpp" / "geometry.cpp").read_text(encoding="utf-8")
        self.assertIn("for (std::size_t i = 0; i + 1 < points.size(); ++i)", source)
        self.assertIn("const auto [x2, y2] = points[i + 1];", source)


if __name__ == "__main__":
    unittest.main()
