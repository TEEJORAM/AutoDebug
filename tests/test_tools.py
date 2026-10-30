"""The agent tools and the Python session against a fake extension speaking the real
relay protocol, with the scripted debug adapter in-process. Runs without Node.js."""

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
        for name in ("geometry.py", "test_geometry.py"):
            (self.workspace / name).write_text("# scripted\n", encoding="utf-8")
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


class NotBuilt(ToolsTest):
    def test_a_program_under_the_workspace_folder_is_checked_before_asking(self):
        self.fake.close()
        launch = [{"name": "Run app", "type": "debugpy", "request": "launch", "program": "${workspaceFolder}/build/app.py"},
                  {"name": "Run file", "type": "debugpy", "request": "launch", "program": "${file}"}]
        self.fake = self.extension(launch=launch)
        args = {"breakpoints": [{"file": "geometry.py", "line": 15}], "goal": "x", "wait_seconds": 0}
        error = self.assertCode("NOT_BUILT", self.debugger.start_session, launch_configuration="Run app", **args)
        self.assertIn("app.py does not exist yet", error.message)
        self.assertIn("'build'", error.message)
        self.assertFalse(any(name == "approve" for name, _ in self.fake.calls))
        self.assertEqual(self.debugger.start_session(launch_configuration="Run app", build_task="build", **args)["status"],
                         "awaiting_approval")
        self.debugger.stop_session()
        (self.workspace / "build").mkdir()
        (self.workspace / "build" / "app.py").write_text("", encoding="utf-8")
        self.assertEqual(self.debugger.start_session(launch_configuration="Run app", **args)["status"], "awaiting_approval")
        self.debugger.stop_session()
        # A path AutoDebug cannot resolve itself is left to the debugger.
        self.assertEqual(self.debugger.start_session(launch_configuration="Run file", **args)["status"], "awaiting_approval")


class TwoIdes(ToolsTest):
    """Cursor (where the developer chats) and Visual Studio (where they debug) have the same project open."""

    def setUp(self):
        super().setUp()
        import os
        from unittest import mock
        patch = mock.patch.dict(os.environ, {"AUTODEBUG_HOME": str(self.root / "state")})
        patch.start()
        self.addCleanup(patch.stop)
        self.vs = self.extension(ide="visualstudio", launch=[
            {"name": "geometry (Debug|x64)", "type": "debugpy", "request": "launch", "module": "unittest"}])

    def args(self, launch):
        return {"launch_configuration": launch, "breakpoints": [{"file": "geometry.py", "line": 15}],
                "goal": "x", "wait_seconds": 0}

    def test_the_window_with_the_launch_configuration_is_chosen(self):
        result = self.debugger.start_session(**self.args("geometry (Debug|x64)"))
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertIn("Visual Studio", result["next"])
        self.assertTrue(any(op == "approve" for op, _ in self.vs.calls))
        self.assertFalse(any(op == "approve" for op, _ in self.fake.calls))

    def test_a_configuration_in_both_needs_the_ide_or_the_developers_choice(self):
        both = self.extension(ide="visualstudio")  # Visual Studio also has "Debug tests"
        error = self.assertCode("AMBIGUOUS_WINDOW", self.debugger.start_session, **self.args("Debug tests"))
        self.assertIn("autodebug setup --debug-in", error.message)
        from autodebug.connection import set_preferred_ide
        set_preferred_ide("cursor")
        self.assertIn("Cursor", self.debugger.start_session(**self.args("Debug tests"))["next"])
        self.debugger.stop_session()
        self.assertEqual(self.debugger.list_targets()["debug_in"], "cursor")
        self.assertIn("ide=cursor", self.debugger.list_targets()["next"])
        self.assertTrue(both)


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

    def test_the_ide_picks_the_window(self):
        other = self.root / "Other"
        other.mkdir()
        second = FakeExtension(self.bridges, str(other), ide="visualstudio")
        self.addCleanup(second.close)
        (listed,) = self.debugger.list_targets(ide="visualstudio")["windows"]
        self.assertEqual(listed["ide"], "visualstudio")
        self.assertEqual(self.debugger.start_session(launch_configuration="Debug tests", breakpoints=[], goal="x",
                                                     ide="cursor", wait_seconds=0)["status"], "awaiting_approval")
        self.assertCode("NO_WINDOW", self.debugger.list_targets, ide="vscode")


class OldExtension(ToolsTest):
    def setUp(self):
        super().setUp()
        self.fake.write_file(protocol=2, version="0.2.0")  # the window still runs the old extension

    def test_tools_name_the_old_extension_and_the_fix(self):
        for call in (self.debugger.list_targets,
                     lambda: self.debugger.start_session(launch_configuration="Debug tests", breakpoints=[], goal="x")):
            error = self.assertCode("OLD_EXTENSION", call)
            self.assertIn("AutoDebug extension 0.2.0 (protocol 2)", error.message)
            self.assertIn("`autodebug setup cursor`", error.message)
            self.assertIn("Developer: Reload Window", error.message)
            self.assertIn("Restarting only the extension host keeps the old extension", error.message)

    def test_a_current_window_is_still_used(self):
        other = self.root / "Other"
        other.mkdir()
        current = self.extension()
        current.workspace = str(other)
        current.write_file(folders=[str(other)])
        (window,) = self.debugger.list_targets()["windows"]
        self.assertEqual(window["folders"][0]["folder"], str(other))
        error = self.assertCode("OLD_EXTENSION", self.debugger.start_session, launch_configuration="Debug tests",
                                breakpoints=[], goal="x", workspace_folder=str(self.workspace))
        self.assertIn(str(self.workspace), error.message)


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
        self.assertNotIn("2 minutes", result["next"])

    def test_no_answer_is_not_reported_as_deny(self):
        self.start()
        self.fake.deny("no answer within 2 minutes")
        result = self.debugger.wait(5)
        self.assertEqual((result["status"], result["reason"]), ("denied", "no answer within 2 minutes"))
        self.assertIn("Nobody answered the Approve dialog", result["next"])
        self.assertIn("not a Deny", result["next"])

    def test_first_stop_shows_location_and_redacted_variables(self):
        result = self.start_paused()
        self.assertEqual((result["location"], result["reason"]), ("geometry.py:15", "breakpoint"))
        values = {v["name"]: v["value"] for v in result["variables"]}
        self.assertEqual(values["i"], "0")
        self.assertEqual(values["password"], "***REDACTED***")
        self.assertNotIn("hunter2", json.dumps(result))
        self.assertEqual(result["breakpoints"], [{"at": "geometry.py:15", "source": "session", "verified": True}])

    def test_step_reports_changed_variables(self):
        self.start_paused()
        result = self.debugger.step("over")
        self.assertEqual(result["location"], "geometry.py:12")
        self.assertIn({"name": "total", "before": "0.0", "after": "-1.0"}, result["changed"])
        multi = self.debugger.step("over", count=3)
        self.assertEqual(multi["path"], ["geometry.py:15", "geometry.py:12", "geometry.py:15"])
        self.assertEqual(multi["steps"], "4 used")

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

    def test_trace_shows_before_and_after_each_pass(self):
        self.start_paused(breakpoints=[{"file": "geometry.py", "line": 12}])
        result = self.debugger.trace("geometry.py", 15, ["i", "total"], hits=5)
        self.assertEqual([(r["i"], r["total"]) for r in result["rows"]],
                         [("0", "0.0 → -1.0"), ("1", "-1.0 → 2.0"), ("2", "2.0 → 4.0")])
        self.assertEqual(result["rows"][0]["caller"], "test_geometry.py:18")
        self.assertIn("3 of 5 hits", result["note"])

    def test_trace_stops_at_other_breakpoints(self):
        self.fake.editor_breakpoints = [("geometry.py", 12)]
        self.assertEqual(self.start_paused()["location"], "geometry.py:12")  # the editor breakpoint stops it first
        result = self.debugger.trace("geometry.py", 15, ["i"], hits=5, after=False)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["location"], "geometry.py:12")
        self.assertIn("another breakpoint", result["note"])

    def test_continue_until_runs_past_other_breakpoints(self):
        self.fake.editor_breakpoints = [("geometry.py", 12)]
        result = self.start_paused()
        self.assertIn({"at": "geometry.py:12", "source": "editor", "verified": True}, result["breakpoints"])
        reached = self.debugger.continue_(10, until={"file": "geometry.py", "line": 16})
        self.assertEqual(reached["location"], "geometry.py:16")
        self.assertEqual(reached["skipped_stops"], ["geometry.py:15", "geometry.py:12", "geometry.py:15", "geometry.py:12",
                                                    "geometry.py:15"])

    def test_program_output_arrives_when_it_ends(self):
        self.start_paused()
        for _ in range(3):
            ended = self.debugger.continue_(5)
        self.assertEqual(ended["status"], "ended")
        self.assertIn("AssertionError: 2.0 != 1.0", ended["output"])
        self.assertIn("AssertionError: 2.0 != 1.0", self.debugger.timeline[-1].detail)

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
        self.debugger.trace("geometry.py", 15, ["i"], hits=2, after=False)
        self.debugger.stop_session()
        path = Path(self.debugger.write_report(
            model="test model", title="Area changes when a shape moves", problem="Moving a square changes its area from 1 to 2.",
            what_went_wrong="The closing edge is never added.", why="The loop stops at len(points) - 1.",
            solution="Use range(n) and points[(i + 1) % n].", confidence="confirmed",
            how_confirmed="The failing test passes with the fix.", verification="python -m unittest passes.",
            fix_verified=True,
        )["report_file"])
        self.assertEqual(path.parent, self.workspace / "autodebug-reports")
        text = path.read_text(encoding="utf-8")
        headings = ["**Ticket:** none", "## Problem", "## Steps to reproduce", "## Debug sessions", "## Root cause",
                    "### What went wrong", "### Why", "## Solution", "## AI usage"]
        positions = [text.index(h) for h in headings]
        self.assertEqual(positions, sorted(positions))  # exactly the sections asked for, in this order
        self.assertEqual(text.count("\n## "), 6)  # and no others (no timeline, no tables)
        self.assertIn("Not tried.\n\nSteps: NA", text)
        self.assertIn("Confidence: Confirmed. The failing test passes with the fix.", text)
        self.assertIn("Verified: python -m unittest passes. (reported by the AI agent)", text)
        self.assertIn("Debugged in Cursor with `Debug tests`, interpreted language: no build type.", text)
        for absent in ("| stopped |", "Call stack", "total: 0.0", "Timeline", "|---|"):
            self.assertNotIn(absent, text)
        self.assertIn("- Model: test model (as the agent reported it)", text)
        self.assertIn("- Tokens: not reported by the agent.", text)
        self.assertRegex(text, r"- AutoDebug: 0 tool calls, about 0 tokens")  # tools called directly, not over MCP

    def test_ai_usage_counts_the_tool_traffic(self):
        from autodebug.mcp_server import call_tool

        call_tool(self.debugger, "list_targets", {})
        call_tool(self.debugger, "stack", {})  # an error is traffic too
        path = Path(call_tool(self.debugger, "write_report", {
            "model": "Claude Opus (Cursor)", "token_usage": "about 180k (Cursor usage page)", "title": "t",
            "problem": "p", "what_went_wrong": "w", "why": "r", "solution": "s", "confidence": "likely",
            "workspace_folder": str(self.workspace)})[0]["report_file"])
        text = path.read_text(encoding="utf-8")
        self.assertIn("- Model: Claude Opus (Cursor) (as the agent reported it)", text)
        self.assertIn("- Tokens: about 180k (Cursor usage page)", text)
        self.assertRegex(text, r"- AutoDebug: 2 tool calls, about \d[\d,]* tokens")
        self.assertEqual(self.debugger.usage, {"calls": 0, "characters": 0})

    def test_an_unverified_fix_says_so(self):
        path = Path(self.debugger.write_report(
            model="m", title="t", problem="p", what_went_wrong="w", why="r", solution="s", confidence="likely",
            verification="The fix was not applied. The repro still fails.", workspace_folder=str(self.workspace))["report_file"])
        text = path.read_text(encoding="utf-8")
        self.assertIn("Not verified yet: the fix has not been applied and tested.", text)
        self.assertNotIn("The fix was not applied", text)
        self.assertNotIn("Verified:", text)
        self.assertCode("BAD_REQUEST", self.debugger.write_report, model="m", title="t", problem="p",
                        what_went_wrong="w", why="r", solution="s", confidence="likely", fix_verified=True,
                        workspace_folder=str(self.workspace))

    def test_the_model_is_required(self):
        self.assertCode("BAD_REQUEST", self.debugger.write_report, model=" ", title="t", problem="p",
                        what_went_wrong="w", why="r", solution="s", confidence="likely",
                        workspace_folder=str(self.workspace))

    def test_timeline_covers_every_session_until_the_report(self):
        self.start_paused()
        self.debugger.trace("geometry.py", 15, ["i"], hits=2)
        self.debugger.stop_session()
        self.start_paused(breakpoints=[{"file": "geometry.py", "line": 16}])
        self.debugger.stop_session()
        kinds = [e.kind for e in self.debugger.timeline]
        for kind in ("session 1", "trace", "session 2"):
            self.assertIn(kind, kinds)
        self.debugger.write_report(model="test model", title="Two sessions", problem="p", what_went_wrong="w",
                                   why="r", solution="s", confidence="likely")
        self.assertEqual(self.debugger.timeline, [])

    def test_confirmed_needs_how(self):
        self.assertCode("BAD_REQUEST", self.debugger.write_report, model="test model", title="t", problem="p", what_went_wrong="w", why="r",
                        solution="s", confidence="confirmed", workspace_folder=str(self.workspace))


class Tickets(ToolsTest):
    """Working from a ticket: program arguments, the reproduction run and the report."""

    def test_args_replace_the_configurations_and_the_dialog_says_so(self):
        self.start(args=["-k", "test_area, moved"], ticket="https://github.com/o/r/issues/1771")
        approve = self.fake.session["args"]
        self.assertEqual(approve["launch"]["args"], ["-k", "test_area, moved"])
        notes = "\n".join(approve["notes"])
        self.assertIn('Program arguments chosen by the AI agent (they replace the configuration\'s): '
                      '["-k", "test_area, moved"]', notes)
        self.assertIn("Ticket: https://github.com/o/r/issues/1771", notes)
        self.assertIn("Ticket text can come from anyone", notes)

    def test_without_args_the_configuration_is_unchanged(self):
        self.start()
        self.assertEqual(self.fake.session["args"]["launch"]["args"], ["-v"])
        self.assertFalse(any("Ticket" in n for n in self.fake.session["args"]["notes"]))

    def test_unsafe_args_are_refused_before_the_dialog(self):
        for args, text in ((["ok\nrm -rf /"], "line break"), (["${input:x}"], "variable"),
                           (["--key=ghp_" + "a" * 36], "looks like a secret"), (["x"] * 33, "at most 32")):
            error = self.assertCode("BAD_REQUEST", self.debugger.start_session, launch_configuration="Debug tests",
                                    breakpoints=[], goal="x", args=args)
            self.assertIn(text, error.message)
        self.assertIsNone(self.fake.session)  # nothing was shown to the developer

    def test_args_are_only_for_launch(self):
        from autodebug.launch import program_arguments

        with self.assertRaises(DebugError) as caught:
            program_arguments({"request": "attach", "type": "debugpy"}, ["x"])
        self.assertIn("only for launch", caught.exception.message)

    def test_visual_studio_gets_one_quoted_command_line(self):
        from autodebug.launch import program_arguments

        launch = {"request": "launch", "type": "visualstudio", "args": ["--old"]}
        program_arguments(launch, ["-m", "D:\\Projects\\my repro\\issue 1771.js"])
        self.assertEqual(launch["args"], ['-m "D:\\Projects\\my repro\\issue 1771.js"'])

    def test_reproduce_runs_without_breakpoints_and_the_report_shows_it(self):
        started = self.debugger.reproduce(launch_configuration="Debug tests", symptom="area 2.0 instead of 1.0",
                                          args=["-v"], ticket="PROJ-42", wait_seconds=0.2)
        self.assertEqual(started["status"], "awaiting_approval")
        approve = self.fake.session["args"]
        self.assertEqual(approve["breakpoints"], [])
        self.assertIn("This run only reproduces the bug", "\n".join(approve["notes"]))
        self.fake.approve()
        ended = self.debugger.wait(10)
        self.assertEqual((ended["status"], ended["exit_code"]), ("ended", 1))
        self.assertIn("AssertionError: 2.0 != 1.0", ended["output"])
        self.assertIn("Compare the output and exit code with the reported symptom: 'area 2.0 instead of 1.0'",
                      ended["next"])
        self.assertIn("do not debug a bug you have not seen", ended["next"])
        self.assertEqual(self.debugger.wait(0)["next"], ended["next"])  # recorded once
        self.assertEqual(len(self.debugger.reproductions), 1)

        paused = self.start_paused(args=["-v"], ticket="PROJ-42")  # then the real session
        self.assertEqual(paused["location"], "geometry.py:15")
        self.assertNotIn("reported symptom", self.debugger.stop_session()["next"])
        self.assertCode("BAD_REQUEST", self.debugger.write_report, model="test model", title="t", problem="p", what_went_wrong="w", why="r",
                        solution="s", confidence="confirmed", how_confirmed="h", reproduced="no")
        path = Path(self.debugger.write_report(
            model="test model", title="Area changes", problem="p", what_went_wrong="w", why="r", solution="s", confidence="likely",
            steps_to_reproduce=["Run repro/area.py", "It moves a unit square by (2, 1)"], reproduced="yes")["report_file"])
        text = path.read_text(encoding="utf-8")
        for expected in ("**Ticket:** PROJ-42", "Reproducible: yes.\n\n1. Run repro/area.py\n2. It moves a unit square by (2, 1)",
                         "The run without breakpoints ended with exit code 1."):
            self.assertIn(expected, text)
        self.assertEqual((self.debugger.reproductions, self.debugger.ticket), ([], None))

    def test_the_agent_is_told_where_and_what_it_debugs(self):
        (window,) = self.debugger.list_targets()["windows"]
        (config,) = window["folders"][0]["launch"]
        self.assertEqual(config["start_with"], {"launch_configuration": "Debug tests", "ide": "cursor"})
        self.assertEqual(config["build"]["source"], "interpreted language: no build type")
        started = self.start()
        self.assertEqual(started["debugging"], {"ide": "Cursor", "folder": str(self.workspace),
                                                "launch_configuration": "Debug tests",
                                                "build": "interpreted language: no build type"})
        self.assertNotIn("build_note", started)

    def test_reproduced_must_be_known(self):
        self.assertCode("BAD_REQUEST", self.debugger.write_report, model="test model", title="t", problem="p", what_went_wrong="w", why="r",
                        solution="s", confidence="likely", reproduced="yes", workspace_folder=str(self.workspace))
        self.assertCode("BAD_REQUEST", self.debugger.write_report, model="test model", title="t", problem="p", what_went_wrong="w", why="r",
                        solution="s", confidence="likely", reproduced="maybe", workspace_folder=str(self.workspace))


class Captures(ToolsTest):
    def test_a_stop_without_a_screenshot_says_why(self):
        self.start_paused()
        self.assertCode("BAD_REQUEST", self.debugger.capture, names=["i"], note="x", frame_index=50)
        captured = self.debugger.capture(names=["i", "total", "password"], wrong=["total", "nope"],
                                         note="total is wrong after the last pass \u2014 the closing edge is missing")
        self.assertEqual((captured["captured"], captured["location"]), (1, "geometry.py:15"))
        self.assertEqual([v["name"] for v in captured["variables"]], ["i", "total", "password"])
        self.assertEqual(captured["variables"][2]["value"], "***REDACTED***")
        self.assertIn("Cursor cannot take screenshots; only Visual Studio can", captured["screenshot_note"])
        self.debugger.stop_session()
        path = Path(self.debugger.write_report(
            model="test model", title="Area", problem="p",
            what_went_wrong="The closing edge is never added \u2014 so the area is wrong.",
            why="The loop stops one corner early.", solution="Loop over every corner.", confidence="likely",
            pattern="perimeter() already loops with (i + 1) % n.",
            debug_findings="The trace showed three passes for four corners.")["report_file"])
        text = path.read_text(encoding="utf-8")
        for expected in ("The trace showed three passes for four corners.",
                         "### Stop 1: total is wrong after the last pass, the closing edge is missing",
                         "No screenshot: Cursor cannot take screenshots; only Visual Studio can",
                         "The closing edge is never added, so the area is wrong.",
                         "Follows the existing pattern: perimeter() already loops with (i + 1) % n."):
            self.assertIn(expected, text)
        for absent in ("\u2014", "hunter2", ".svg", "polygon_area", "| `total`"):
            self.assertNotIn(absent, text)
        self.assertEqual(list((self.workspace / "autodebug-reports").iterdir()), [path])
        self.assertEqual(self.debugger.evidence, [])

    def test_captures_are_limited(self):
        self.start_paused()
        for _ in range(5):
            self.debugger.capture(names=["i"], note="x")
        self.assertCode("LIMIT", self.debugger.capture, names=["i"], note="x")


class OpenIde(ToolsTest):
    def setUp(self):
        super().setUp()
        from unittest import mock
        from autodebug import ide_launch

        self.started = []
        patches = [mock.patch.object(ide_launch, "start", side_effect=self.started.append),
                   mock.patch.object(ide_launch, "command", side_effect=lambda ide, p: [f"{ide}-launcher", str(p)]),
                   mock.patch.object(ide_launch, "state_folder", return_value=self.root / "state")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_an_open_window_is_reused(self):
        result = self.debugger.open_ide("cursor", str(self.workspace), wait_seconds=0)
        self.assertEqual((result["status"], result["started"], self.started), ("open", False, []))

    def test_the_ide_is_started_once_while_it_loads(self):
        other = self.root / "Other"
        other.mkdir()
        first = self.debugger.open_ide("vscode", str(other), wait_seconds=0)
        self.assertEqual((first["status"], first["started"]), ("opening", True))
        self.assertIn("never starts a second copy", first["next"])
        second = self.debugger.open_ide("vscode", str(other), wait_seconds=0)
        self.assertEqual((second["status"], second["started"]), ("opening", False))
        self.assertEqual(self.started, [["vscode-launcher", str(other)]])
        self.extension(ide="vscode").close()  # a window that opens the folder later is found
        fake = FakeExtension(self.bridges, str(other), ide="vscode")
        self.addCleanup(fake.close)
        self.assertEqual(self.debugger.open_ide("vscode", str(other), wait_seconds=2)["status"], "open")
        self.assertEqual(len(self.started), 1)

    def test_visual_studio_finds_the_solution_and_its_cmake_source(self):
        from autodebug import ide_launch

        source = self.root / "quickjs"
        build = source / "build"
        build.mkdir(parents=True)
        self.assertCode("NOT_FOUND", ide_launch.target, "visualstudio", str(source))
        (build / "quickjs.sln").write_text("", encoding="utf-8")
        (build / "CMakeCache.txt").write_text(f"CMAKE_HOME_DIRECTORY:INTERNAL={source}\n", encoding="utf-8")
        self.assertEqual(ide_launch.target("visualstudio", str(source)), (build / "quickjs.sln", source))
        (source / "other.sln").write_text("", encoding="utf-8")
        self.assertCode("AMBIGUOUS_WINDOW", ide_launch.target, "visualstudio", str(source))
        self.assertCode("BAD_REQUEST", ide_launch.target, "visualstudio", "relative/path")

    def test_no_window_points_at_open_ide(self):
        self.fake.close()
        error = self.assertCode("NO_WINDOW", self.debugger.list_targets)
        self.assertIn("Call open_ide", error.message)
        self.assertIn("Do not start the IDE yourself", error.message)


class OutdatedExtension(unittest.TestCase):
    def test_an_older_visual_studio_extension_is_named_with_the_fix(self):
        from autodebug import __version__
        from autodebug.connection import Window, outdated_extension

        def window(ide, version):
            return Window("w", ide, ("D:/p",), 1, "0" * 64, version)

        note = outdated_extension(window("visualstudio", "0.6.0"))
        self.assertIn(f"Visual Studio's AutoDebug extension is 0.6.0, older than AutoDebug {__version__}", note)
        self.assertIn("close every Visual Studio window and run `autodebug setup`", note)
        self.assertIsNone(outdated_extension(window("visualstudio", __version__)))
        self.assertIsNone(outdated_extension(window("cursor", "0.5.0")))  # its own version line


if __name__ == "__main__":
    unittest.main()
