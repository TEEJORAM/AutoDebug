"""The real extension core (bridge.js) through tests/harness.js, driven by the
real Python tools over the real protocol. Skipped without Node.js."""

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

from autodebug.connection import Connection, DebugError, discover
from autodebug.tools import Debugger

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "AutoDebugDemo"
NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "needs Node.js")
class HarnessTest(unittest.TestCase):
    debugpy: str | None = None
    build_exit = 0
    debuggers = "debugpy"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name) / "AutoDebugDemo"
        shutil.copytree(DEMO, self.workspace, ignore=shutil.ignore_patterns("__pycache__", ".cursor", "mcp.json"))
        tasks = {"version": "2.0.0", "tasks": [{"label": "check", "type": "shell", "command": "python", "args": ["-m", "py_compile", "geometry.py"]}]}
        (self.workspace / ".vscode" / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        self.bridges = Path(tmp.name) / "state" / "bridges"
        env = dict(os.environ, HARNESS_BUILD_EXIT=str(self.build_exit), HARNESS_DEBUGGERS=self.debuggers)
        if self.debugpy:
            env["HARNESS_DEBUGPY"] = self.debugpy
        self.lines: queue.Queue[str] = queue.Queue()
        self.node = subprocess.Popen([NODE, str(ROOT / "tests" / "harness.js"), str(self.bridges), str(self.workspace)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        threading.Thread(target=lambda: [self.lines.put(l.rstrip("\n")) for l in self.node.stdout], daemon=True).start()
        self.addCleanup(self.stop_node)
        self.expect("READY", 30)
        self.debugger = Debugger(find_windows=lambda: discover(self.bridges))

    def stop_node(self):
        if hasattr(self, "debugger"):
            try:
                if self.debugger.connection:
                    self.debugger.stop_session()
            except DebugError:
                pass
            self.debugger.close()
        if self.node.poll() is None:
            self.send("exit")
            try:
                self.node.wait(10)
            except subprocess.TimeoutExpired:
                self.node.kill()
        self.node.stdin.close()
        self.node.stdout.close()

    def send(self, text):
        self.node.stdin.write(text + "\n")
        self.node.stdin.flush()

    def expect(self, prefix, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        self.fail(f"harness never printed {prefix!r}")

    def start(self, **kwargs):
        args = {"launch_configuration": "Debug tests", "breakpoints": [{"file": "geometry.py", "line": 15}],
                "goal": "Find why moving a shape changes its area", "wait_seconds": 0.5, **kwargs}
        self.assertEqual(self.debugger.start_session(**args)["status"], "awaiting_approval")
        return json.loads(self.expect("DIALOG"))

    def approved(self, **kwargs):
        dialog = self.start(**kwargs)
        self.send("approve")
        deadline = time.monotonic() + 60
        result = self.debugger.wait(30)
        while result["status"] not in ("paused", "ended", "build_failed") and time.monotonic() < deadline:
            result = self.debugger.wait(30)
        return dialog, result


class Extension(HarnessTest):
    def test_dialog_shows_exactly_what_will_run(self):
        dialog = self.start(build_task="check", max_steps=7)
        self.assertTrue(dialog["modal"])
        self.assertEqual(dialog["items"], ["Approve"])
        detail = dialog["detail"]
        for expected in ("Goal: Find why moving a shape changes its area", "Build first: python -m py_compile geometry.py",
                         '"Debug tests" (debugpy) unittest -v', "Breakpoints: geometry.py:15", "Limits: 7 steps"):
            self.assertIn(expected, detail)

    def test_full_session(self):
        _, result = self.approved()
        self.assertEqual((result["status"], result["location"]), ("paused", "geometry.py:15"))
        self.assertTrue(result["breakpoints"][0]["verified"])
        self.assertEqual({v["name"]: v["value"] for v in result["variables"]}["password"], "***REDACTED***")
        step = self.debugger.step("over")
        self.assertEqual(step["location"], "geometry.py:12")
        self.assertIn({"name": "total", "before": "0.0", "after": "-1.0"}, step["changed"])
        self.assertEqual(self.debugger.stack()["frames"][1]["location"], "test_geometry.py:18")
        trace = self.debugger.trace("geometry.py", 15, ["i", "total"], hits=5)
        self.assertEqual([r["i"] for r in trace["rows"]], ["1", "2"])
        report = Path(self.debugger.write_report(title="Area bug", problem="p", root_cause="r", solution="s",
                                                 confidence="likely")["report_file"])
        self.assertIn("| trace | geometry.py:15 |", report.read_text(encoding="utf-8"))
        self.assertIn("| session 1 |", report.read_text(encoding="utf-8"))

    def test_denied(self):
        self.start()
        self.send("deny")
        self.assertEqual(self.debugger.wait(10)["status"], "denied")

    def test_build_runs_first(self):
        _, result = self.approved(build_task="check")
        self.assertEqual(result["status"], "paused")
        build = next(e for e in self.debugger.timeline if e.kind == "build")
        self.assertEqual((build.where, build.detail), ("check", "succeeded, exit code 0"))

    def test_breakpoints_are_removed_when_the_session_stops(self):
        self.approved()
        self.debugger.stop_session()
        self.expect("LOG stopped")
        self.send("breakpoints")
        self.assertEqual(self.expect("BREAKPOINTS"), "0")

    def test_one_session_at_a_time(self):
        self.approved()
        with self.assertRaises(DebugError) as caught:
            Debugger(find_windows=lambda: discover(self.bridges)).start_session(
                launch_configuration="Debug tests", breakpoints=[], goal="x")
        self.assertEqual(caught.exception.code, "BUSY")

    def test_protocol_guards(self):
        (window,) = discover(self.bridges)
        self.assertEqual(window.ide, "cursor")
        with self.assertRaises(DebugError):
            Connection(replace(window, token="0" * 64))
        connection = Connection(window)
        self.addCleanup(connection.close)
        for op in ("evaluate", "setVariable"):
            with self.assertRaises(DebugError) as caught:
                connection.call(op, {"expression": "1"})
            self.assertEqual(caught.exception.code, "BAD_REQUEST")
        with self.assertRaises(DebugError) as caught:
            connection.call("start", {"launch": "Debug tests", "breakpoints": [{"file": "../x.py", "line": 1}]})
        self.assertEqual(caught.exception.code, "OUTSIDE_WORKSPACE")

    def test_connection_file_goes_away_with_the_window(self):
        self.send("exit")
        self.node.wait(10)
        self.assertEqual(discover(self.bridges), [])


class MissingDebugger(HarnessTest):
    debuggers = ""

    def test_missing_debugger_is_reported_before_asking_for_approval(self):
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Debug tests", breakpoints=[], goal="x")
        self.assertEqual(caught.exception.code, "NOT_FOUND")
        self.assertIn('no debugger for type "debugpy"', caught.exception.message)
        self.assertIn("Python Debugger extension", caught.exception.message)


class FailedBuild(HarnessTest):
    build_exit = 2

    def test_failed_build_launches_nothing(self):
        _, result = self.approved(build_task="check")
        self.assertEqual((result["status"], result["exit_code"]), ("build_failed", 2))


if __name__ == "__main__":
    unittest.main()
