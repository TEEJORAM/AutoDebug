"""The agent tools against a fake extension speaking the real protocol."""

import json
import tempfile
import unittest
from pathlib import Path

from autodebug.connection import DebugError, discover
from autodebug.tools import Debugger
from tests.fake_extension import FakeExtension


class ToolsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workspace = self.root / "AutoDebugDemo"
        self.workspace.mkdir()
        self.bridges = self.root / "state" / "bridges"
        self.fake = self.extension()
        self.debugger = Debugger(find_windows=lambda: discover(self.bridges))
        self.addCleanup(self.debugger.close)

    def extension(self, **kwargs) -> FakeExtension:
        fake = FakeExtension(self.bridges, str(self.workspace), **kwargs)
        self.addCleanup(fake.close)
        return fake

    def assertCode(self, code, function, *args, **kwargs):
        with self.assertRaises(DebugError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.message)
        return caught.exception

    def start(self, **kwargs):
        args = {"launch_configuration": "Debug tests", "breakpoints": [{"file": "geometry.py", "line": 15}],
                "goal": "find why the area changes", "wait_seconds": 0.2, **kwargs}
        result = self.debugger.start_session(**args)
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertIn("Approve", result["next"])
        self.assertIn("Cursor", result["next"])
        return result

    def start_paused(self, **kwargs):
        self.start(**kwargs)
        self.fake.approve()
        result = self.debugger.wait(5)
        self.assertEqual(result["status"], "paused")
        return result


class Targets(ToolsTest):
    def test_lists_windows_and_targets(self):
        found = self.debugger.list_targets()
        (window,) = found["windows"]
        self.assertEqual(window["ide"], "cursor")
        self.assertEqual(window["folders"][0]["launch"][0]["name"], "Debug tests")
        self.assertEqual(window["folders"][0]["tasks"][0]["label"], "build")

    def test_no_window_explains_setup(self):
        self.fake.close()
        error = self.assertCode("NO_WINDOW", self.debugger.list_targets)
        self.assertIn("autodebug setup", error.message)

    def test_two_windows_need_a_folder(self):
        other = self.root / "Other"
        other.mkdir()
        second = FakeExtension(self.bridges, str(other), ide="vscode")
        self.addCleanup(second.close)
        self.assertCode("AMBIGUOUS_WINDOW", self.debugger.start_session, launch_configuration="Debug tests",
                        breakpoints=[], goal="x")
        self.start(workspace_folder=str(self.workspace))


class Session(ToolsTest):
    def test_nothing_runs_until_approved(self):
        self.start()
        self.assertEqual(self.debugger.wait(0.2)["status"], "awaiting_approval")
        self.assertCode("BAD_REQUEST", self.debugger.stack)  # not paused: still awaiting approval

    def test_denied(self):
        self.start()
        self.fake.deny()
        result = self.debugger.wait(5)
        self.assertEqual(result["status"], "denied")
        self.assertIn("nothing ran", result["next"])

    def test_first_stop_shows_location_and_redacted_variables(self):
        result = self.start_paused()
        self.assertEqual((result["location"], result["reason"]), ("geometry.py:15", "breakpoint"))
        values = {v["name"]: v["value"] for v in result["variables"]}
        self.assertEqual(values["i"], "0")
        self.assertEqual(values["password"], "***REDACTED***")
        self.assertNotIn("hunter2", json.dumps(result))
        self.assertEqual(result["breakpoints"], [{"at": "geometry.py:15", "verified": True}])

    def test_step_reports_changed_variables(self):
        self.start_paused()
        result = self.debugger.step("over")
        self.assertEqual(result["location"], "geometry.py:12")
        self.assertIn({"name": "total", "before": "0.0", "after": "-1.0"}, result["changed"])
        multi = self.debugger.step("over", count=3)
        self.assertEqual(multi["path"], ["geometry.py:15", "geometry.py:12", "geometry.py:15"])
        self.assertEqual(multi["steps"], "4 of 50 used")

    def test_step_limit(self):
        self.start_paused(max_steps=1)
        self.debugger.step()
        self.assertCode("LIMIT", self.debugger.step)

    def test_continue_runs_to_the_next_stop_then_the_end(self):
        self.start_paused()
        self.assertEqual(self.debugger.continue_(5)["location"], "geometry.py:15")
        self.debugger.continue_(5)
        ended = self.debugger.continue_(5)
        self.assertEqual((ended["status"], ended["exit_code"]), ("ended", 1))
        self.assertIn("write_report", ended["next"])

    def test_inspect_and_stack(self):
        self.start_paused()
        full = self.debugger.inspect(names=["i", "password", "missing"])
        self.assertEqual(full["variables"][0]["value"], "0")
        self.assertEqual(full["variables"][1]["value"], "***REDACTED***")
        self.assertEqual(full["not_found"], ["missing"])
        frames = self.debugger.stack()["frames"]
        self.assertEqual(frames[0], {"index": 0, "function": "polygon_area", "location": "geometry.py:15"})
        self.assertEqual(self.debugger.inspect(frame_index=1)["variables"][0]["name"], "self")

    def test_trace_collects_every_pass_through_a_line(self):
        self.start_paused(breakpoints=[{"file": "geometry.py", "line": 12}])
        result = self.debugger.trace("geometry.py", 15, ["i", "total"], hits=5)
        self.assertEqual([r["i"] for r in result["rows"]], ["0", "1", "2"])
        self.assertIn("3 of 5 hits", result["note"])

    def test_breakpoints_can_change_during_the_session(self):
        self.start_paused()
        result = self.debugger.breakpoints(add=[{"file": "geometry.py", "line": 16}],
                                           remove=[{"file": "geometry.py", "line": 15}])
        self.assertEqual([b["at"] for b in result["breakpoints"]], ["geometry.py:16"])
        self.assertEqual(self.debugger.continue_(5)["location"], "geometry.py:16")

    def test_build_failure(self):
        self.fake.build_exit = 2
        self.start(build_task="build")
        self.fake.approve()
        result = self.debugger.wait(5)
        self.assertEqual((result["status"], result["exit_code"]), ("build_failed", 2))

    def test_unknown_configuration_and_outside_files(self):
        self.assertCode("NOT_FOUND", self.debugger.start_session, launch_configuration="Nope", breakpoints=[], goal="x")
        self.assertCode("OUTSIDE_WORKSPACE", self.debugger.start_session, launch_configuration="Debug tests",
                        breakpoints=[{"file": "../secret.py", "line": 1}], goal="x")

    def test_tools_before_a_session(self):
        self.assertCode("NOT_FOUND", self.debugger.step)
        self.assertCode("NOT_FOUND", self.debugger.wait)


class Report(ToolsTest):
    def test_report_has_the_whole_story(self):
        self.start_paused()
        self.debugger.step()
        self.debugger.trace("geometry.py", 15, ["i"], hits=2)
        self.debugger.stop_session()
        path = Path(self.debugger.write_report(
            title="Area changes when a shape moves", problem="Moving a square changes its area from 1 to 2.",
            root_cause="The loop stops at len(points) - 1, so the closing edge is never added.",
            solution="Use range(n) and points[(i + 1) % n].", confidence="confirmed",
            how_confirmed="The failing test passes with the fix.", verification="python -m unittest passes.",
        )["report_file"])
        self.assertEqual(path.parent, self.workspace / "autodebug-reports")
        text = path.read_text(encoding="utf-8")
        for heading in ("## Problem", "## How it was debugged", "### Timeline", "## Root cause", "## Solution",
                        "## Verification"):
            self.assertIn(heading, text)
        self.assertIn("| stopped | geometry.py:15 | breakpoint |", text)
        self.assertIn("total: 0.0 → -1.0", text)
        self.assertIn("**Confirmed**", text)
        self.assertNotIn("hunter2", text)

    def test_confirmed_needs_how(self):
        self.assertCode("BAD_REQUEST", self.debugger.write_report, title="t", problem="p", root_cause="r",
                        solution="s", confidence="confirmed", workspace_folder=str(self.workspace))


if __name__ == "__main__":
    unittest.main()
