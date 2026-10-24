"""examples/AutoDebugDemo: the bug reproduces and the documented fix works."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "examples" / "AutoDebugDemo"
BUGGY = """    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]"""
FIXED = """    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]"""


def tests_in(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-m", "unittest"], cwd=folder, capture_output=True, text=True, timeout=60)


class Demo(unittest.TestCase):
    def test_bug_reproduces(self):
        result = tests_in(DEMO)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AssertionError: 2.0 != 1.0", result.stderr)

    def test_documented_fix_works(self):
        source = (DEMO / "geometry.py").read_text(encoding="utf-8")
        self.assertIn(BUGGY, source)
        self.assertIn(FIXED, (DEMO / "README.md").read_text(encoding="utf-8"))
        self.assertIn("total += x1 * y2 - x2 * y1", source.splitlines()[14])
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("geometry.py", "test_geometry.py"):
                shutil.copy(DEMO / name, tmp)
            (Path(tmp) / "geometry.py").write_text(source.replace(BUGGY, FIXED), encoding="utf-8")
            self.assertEqual(tests_in(Path(tmp)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
