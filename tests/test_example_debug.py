"""Local geometry.py trace. It records real stops and does not drive an IDE."""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

from autodebug.example_debug import debug_example
from autodebug.server import ToolDispatcher

ROOT = Path(__file__).resolve().parents[1]
BUGGY = '''"""sample"""
Point = tuple[float, float]

def polygon_area(points: list[Point]) -> float:
    total = 0.0
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2

def move(points: list[Point], dx: float, dy: float) -> list[Point]:
    return [(x + dx, y + dy) for x, y in points]
'''
FIXED = BUGGY.replace(
    "for i in range(len(points) - 1):\n        x1, y1 = points[i]\n        x2, y2 = points[i + 1]",
    "n = len(points)\n    for i in range(n):\n        x1, y1 = points[i]\n        x2, y2 = points[(i + 1) % n]",
)


class TestExampleDebug(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="autodebug-example-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_missing_edge_is_confirmed_from_recorded_stops(self):
        (self.root / "geometry.py").write_text(BUGGY, encoding="utf-8")
        result = debug_example(self.root)
        self.assertTrue(result["ok"], result)
        body = result["result"]
        self.assertEqual(body["ide_debugger"], "not_connected")
        self.assertEqual(body["area_before"], 1.0)
        self.assertEqual(body["area_after"], 2.0)
        self.assertEqual(body["confidence"], "confirmed")
        self.assertEqual([stop["i"] for stop in body["stops"] if stop["call"] == 0], [0, 1, 2])
        report = (self.root / "investigation.md").read_text(encoding="utf-8")
        self.assertIn("Not done. No IDE debugger is connected.", report)
        self.assertIn("The area line ran 3 times", report)
        self.assertIn("(i + 1) % n", report)
        self.assertIsNone(sys.gettrace())

    def test_closing_edge_keeps_the_area(self):
        (self.root / "geometry.py").write_text(FIXED, encoding="utf-8")
        result = debug_example(self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["area_before"], result["result"]["area_after"])
        self.assertEqual([stop["i"] for stop in result["result"]["stops"] if stop["call"] == 0], [0, 1, 2, 3])

    def test_repo_sample_is_accepted_syntax(self):
        source = (ROOT / "examples" / "AutoDebugDemo" / "geometry.py").read_text(encoding="utf-8")
        ast.parse(source)
        found = debug_example(ROOT)
        self.assertTrue(found["ok"], found)
        self.assertEqual(found["result"]["area_before"], 1.0)
        self.assertEqual(found["result"]["area_after"], 2.0)
        report = ROOT / "examples" / "AutoDebugDemo" / "investigation.md"
        self.addCleanup(report.unlink, missing_ok=True)
        self.assertTrue(report.is_file())

    def test_import_and_unknown_calls_are_refused(self):
        (self.root / "geometry.py").write_text(BUGGY + "\nimport os\n", encoding="utf-8")
        result = debug_example(self.root)
        self.assertFalse(result["ok"])
        self.assertFalse((self.root / "investigation.md").exists())

    def test_tool_takes_no_arguments(self):
        tool = next(tool for tool in ToolDispatcher(
            facade=None, adapter=None, capability_report=None,
        ).list_tools() if tool["name"] == "autodebug_debug_example")
        self.assertEqual(tool["inputSchema"]["properties"], {})
        self.assertIn("Does not set an IDE breakpoint", tool["description"])
