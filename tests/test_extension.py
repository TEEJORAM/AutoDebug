"""The real extension relay (relay.js) through tests/harness.js and a real debug
adapter process (tests/fake_adapter.py unless a test picks debugpy or gdb),
driven by the real Python tools over the real protocol. Skipped without Node.js."""

import json
import os
import sys
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


class HarnessMixin:
    """Runs a relay harness (the IDE stand-in) and drives it with the real Python tools.
    Subclasses say which harness to run; the HARNESS_* flags work for every harness."""

    debugpy: str | None = None
    build_exit = 0
    debuggers = "debugpy"
    editor_bp = ""
    start_defaults = {"launch_configuration": "Debug tests", "breakpoints": [{"file": "geometry.py", "line": 15}]}

    def harness_command(self, bridges: Path, workspace: Path) -> list[str]:
        return [NODE, str(ROOT / "tests" / "harness.js"), str(bridges), str(workspace)]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.workspace = base / "AutoDebugDemo"
        shutil.copytree(DEMO, self.workspace, ignore=shutil.ignore_patterns("__pycache__", ".cursor", "mcp.json"))
        tasks = {"version": "2.0.0", "tasks": [{"label": "check", "type": "shell", "command": "python", "args": ["-m", "py_compile", "geometry.py"]}]}
        (self.workspace / ".vscode" / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        self.bridges = base / "state" / "bridges"
        env = dict(os.environ, HARNESS_PYTHON=sys.executable, HARNESS_BUILD_EXIT=str(self.build_exit), HARNESS_DEBUGGERS=self.debuggers,
                   HARNESS_EDITOR_BP=self.editor_bp, HARNESS_LATE_BP=getattr(self, "late_bp", ""),
                   HARNESS_BUILD_HANG=getattr(self, "build_hang", ""),
                   HARNESS_STEP_FAIL=getattr(self, "step_fail", ""),
                   HARNESS_EXCEPTION=getattr(self, "exception_stop", ""),
                   HARNESS_BP_MESSAGE=getattr(self, "bp_message", ""),
                   HARNESS_BUILD_MINUTE_MS=getattr(self, "build_minute_ms", ""),
                   HARNESS_APPROVAL_MS=getattr(self, "approval_ms", ""),
                   HARNESS_STACK_THROW=getattr(self, "stack_throw", ""),
                   HARNESS_SLOW_STACK=getattr(self, "slow_stack", ""),
                   HARNESS_STOP_THEN_CONTINUE=getattr(self, "stop_then_continue", ""),
                   HARNESS_FLOOD=getattr(self, "flood", ""), HARNESS_KEEP_MS="200")
        if self.debugpy:
            env["HARNESS_DEBUGPY"] = self.debugpy
        self.lines: queue.Queue[str] = queue.Queue()
        self.node = subprocess.Popen(self.harness_command(self.bridges, self.workspace),
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
        args = {**self.start_defaults, "goal": "Find why moving a shape changes its area", "wait_seconds": 0.5, **kwargs}
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


@unittest.skipIf(NODE is None, "needs Node.js")
class HarnessTest(HarnessMixin, unittest.TestCase):
    pass


class Extension(HarnessTest):
    def test_dialog_shows_exactly_what_will_run(self):
        dialog = self.start(build_task="check", max_steps=7)
        self.assertTrue(dialog["modal"])
        self.assertEqual(dialog["items"], ["Approve"])
        detail = dialog["detail"]
        for expected in ("Goal: Find why moving a shape changes its area",
                         'Build first: "check": python -m py_compile geometry.py',
                         '"Debug tests" (debugpy) unittest -v', "Breakpoints: geometry.py:15", "Limits: 7 steps"):
            self.assertIn(expected, detail)

    def test_agent_args_and_ticket_are_in_the_dialog(self):
        dialog = self.start(args=["-k", "area"], ticket="PROJ-42")
        detail = dialog["detail"]
        for expected in ("Ticket: PROJ-42", "Ticket text can come from anyone",
                         'Program arguments chosen by the AI agent (they replace the configuration\'s): ["-k", "area"]',
                         '"Debug tests" (debugpy) unittest -k area', '"-k",'):
            self.assertIn(expected, detail)
        self.assertNotIn('"-v"', detail)

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
        self.assertEqual([(r["i"], r["total"]) for r in trace["rows"]], [("1", "-1.0 → 2.0"), ("2", "2.0 → 4.0")])
        kinds = [(e.kind, e.where) for e in self.debugger.timeline]
        self.assertIn(("trace", "geometry.py:15"), kinds)
        self.assertIn(("session 1", ""), kinds)

    def test_targets_and_locals(self):
        (window,) = self.debugger.list_targets()["windows"]
        tests = next(c for c in window["folders"][0]["launch"] if c["name"] == "Debug tests")
        self.assertEqual((tests["program"], tests["module"], tests["console"]), (None, "unittest", "internalConsole"))
        _, result = self.approved()
        self.assertNotIn("Point", [v["name"] for v in result["variables"]])  # module globals are left out
        self.assertEqual(self.debugger.inspect(names=["Point"])["variables"][0]["value"], "tuple[float, float]")

    def test_output_when_the_program_ends(self):
        self.approved()
        self.debugger.breakpoints(remove=[{"file": "geometry.py", "line": 15}])
        ended = self.debugger.continue_(10)
        self.assertEqual((ended["status"], ended["exit_code"]), ("ended", 1))
        self.assertEqual(ended["output"][-1], "AssertionError: 2.0 != 1.0")

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
        for op in ("evaluate", "setVariable", "start"):
            with self.assertRaises(DebugError) as caught:
                connection.call(op, {"expression": "1"})
            self.assertEqual(caught.exception.code, "BAD_REQUEST")
        self.approved()
        for command in ("evaluate", "setVariable", "setExpression", "disconnect", "writeMemory", "goto", "restartFrame",
                        "restart", "terminateThreads"):
            with self.assertRaises(DebugError) as caught:
                connection.call("dap", {"command": command, "arguments": {"expression": "1"}})
            self.assertEqual(caught.exception.code, "BAD_REQUEST", command)
        self.debugger.stop_session()
        launch = {"name": "Debug tests", "type": "debugpy", "request": "launch", "module": "unittest"}
        outside = str(self.workspace.parent / "x.py")
        with self.assertRaises(DebugError) as caught:
            connection.call("approve", {"launch": launch, "breakpoints": [{"file": outside, "line": 1}]})
        self.assertEqual(caught.exception.code, "OUTSIDE_WORKSPACE")

    def test_the_extension_enforces_the_step_limit_itself(self):
        self.approved(max_steps=1)
        (window,) = discover(self.bridges)
        connection = Connection(window)
        self.addCleanup(connection.close)
        connection.call("dap", {"command": "next", "arguments": {"threadId": 1}})
        with self.assertRaises(DebugError) as caught:
            connection.call("dap", {"command": "next", "arguments": {"threadId": 1}})
        self.assertEqual(caught.exception.code, "LIMIT")

    def test_a_deleted_connection_file_is_written_again(self):
        (window,) = discover(self.bridges)
        for path in self.bridges.glob("*.json"):
            path.unlink()
        self.assertEqual(discover(self.bridges), [])
        self.expect("LOG the connection file was deleted; wrote it again", 5)
        self.assertEqual([w.port for w in discover(self.bridges)], [window.port])

    def test_connection_file_goes_away_with_the_window(self):
        self.send("exit")
        self.node.wait(10)
        self.assertEqual(discover(self.bridges), [])


class ApprovalDetail(HarnessTest):
    def _launch(self, config, tasks=()):
        folder = self.workspace / ".vscode"
        launch = json.loads((folder / "launch.json").read_text(encoding="utf-8"))
        launch["configurations"].append(config)
        (folder / "launch.json").write_text(json.dumps(launch), encoding="utf-8")
        if tasks:
            task_file = json.loads((folder / "tasks.json").read_text(encoding="utf-8"))
            task_file["tasks"].extend(tasks)
            (folder / "tasks.json").write_text(json.dumps(task_file), encoding="utf-8")

    def test_prelaunch_task_command_is_shown(self):
        self._launch(
            {"name": "With pre", "type": "debugpy", "request": "launch", "module": "unittest", "preLaunchTask": "build"},
            [{"label": "configure", "type": "shell", "command": "cmake", "args": ["-S", ".", "-B", "build"]},
             {"label": "build", "type": "shell", "command": "cmake", "args": ["--build", "build"], "dependsOn": "configure"}],
        )
        dialog = self.start(launch_configuration="With pre", breakpoints=[])
        self.assertIn(
            'Before the debugger starts (preLaunchTask): "build": cmake --build build (first: "configure": cmake -S . -B build)',
            dialog["detail"],
        )

    def test_input_variable_and_remote_host_are_refused(self):
        self._launch({"name": "Inputs", "type": "debugpy", "request": "launch", "program": "${input:x}"})
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Inputs", breakpoints=[], goal="x")
        self.assertEqual(caught.exception.code, "BAD_REQUEST")
        self.assertIn("${input:x}", caught.exception.message)
        self._launch({"name": "Remote", "type": "debugpy", "request": "launch", "program": "a.py", "host": "example.com"})
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Remote", breakpoints=[], goal="x")
        self.assertIn("only programs on this computer", caught.exception.message)

    def test_platform_block_is_applied(self):
        self._launch({"name": "Platform", "type": "debugpy", "request": "launch", "program": "fallback.py",
                      "linux": {"program": "linux.py"}, "windows": {"program": "win.py"}, "osx": {"program": "osx.py"}})
        dialog = self.start(launch_configuration="Platform", breakpoints=[])
        program = {"linux": "linux.py", "win32": "win.py", "darwin": "osx.py"}[sys.platform]
        self.assertIn(f'"program": "{program}"', dialog["detail"])
        for key in ("windows", "osx", "linux"):
            self.assertNotIn(f'"{key}"', dialog["detail"])

    def test_attach_dialog_and_detach(self):
        self._launch({"name": "Attach py", "type": "debugpy", "request": "attach",
                      "connect": {"host": "localhost", "port": 5678}})
        dialog = self.start(launch_configuration="Attach py",
                            breakpoints=[{"file": "geometry.py", "line": 15}])
        self.assertIn('attach the debugger for "', dialog["message"])
        self.assertIn("Attach to: the debugger listening on localhost:5678", dialog["detail"])
        self.assertIn("the debugger detaches and the program keeps running", dialog["detail"])
        self.send("approve")
        self.assertEqual(self.debugger.wait(30)["status"], "paused")
        self.debugger.stop_session()
        self.assertIn('"terminateDebuggee":false', self.expect("DISCONNECT"))

    def test_process_id_on_a_launch_configuration_is_refused(self):
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Debug tests", breakpoints=[], goal="x", process_id=1234)
        self.assertEqual(caught.exception.code, "BAD_REQUEST")
        self.assertIn("process_id is only for attach", caught.exception.message)


class LateBreakpoint(HarnessTest):
    late_bp = "1"

    def test_unverified_breakpoint_binds_when_the_module_loads(self):
        _, result = self.approved()
        self.assertTrue(result["breakpoints"][0]["verified"])


class NestedAndThreads(HarnessTest):
    def test_paths_depth_and_child_redaction(self):
        self.approved()
        threads = self.debugger.threads()
        self.assertEqual([item["name"] for item in threads["threads"]], ["main", "worker"])
        point = self.debugger.inspect(names=["points[2]"], depth=1)["variables"][0]
        self.assertEqual(point["value"], "(3, 2)")
        coordinate = self.debugger.inspect(names=["mesh.verts[2].co"], depth=1)["variables"][0]
        self.assertEqual(coordinate["value"], "(1, 2, 3)")
        hidden = self.debugger.inspect(names=["credentials"], depth=1)["variables"][0]["children"][0]
        self.assertEqual(hidden["name"], "note")
        self.assertEqual(hidden["value"], "***REDACTED***")
        self.assertNotIn("visible-child", json.dumps(hidden))


class CursorCpp(HarnessTest):
    def test_microsoft_cpp_debugger_is_refused_in_cursor(self):
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Debug C++ (gdb)", breakpoints=[], goal="x")
        self.assertIn('("type": "lldb")', caught.exception.message)


class BuildChain(HarnessTest):
    def _write(self, config, tasks):
        folder = self.workspace / ".vscode"
        launch = json.loads((folder / "launch.json").read_text(encoding="utf-8"))
        launch["configurations"].append(config)
        (folder / "launch.json").write_text(json.dumps(launch), encoding="utf-8")
        task_file = json.loads((folder / "tasks.json").read_text(encoding="utf-8"))
        task_file["tasks"].extend(tasks)
        (folder / "tasks.json").write_text(json.dumps(task_file), encoding="utf-8")

    def test_build_task_shows_its_dependency_chain(self):
        self._write(
            {"name": "Built", "type": "debugpy", "request": "launch", "module": "unittest"},
            [{"label": "prep", "type": "shell", "command": "cmake", "args": ["-S", "cpp"]},
             {"label": "b2", "type": "shell", "command": "cmake", "args": ["--build", "build"], "dependsOn": "prep"}],
        )
        dialog = self.start(launch_configuration="Built", breakpoints=[], build_task="b2")
        self.assertIn('Build first: "b2": cmake --build build (first: "prep": cmake -S cpp)', dialog["detail"])

    def test_an_unused_task_with_an_input_variable_does_not_block_the_session(self):
        self._write(
            {"name": "Plain", "type": "debugpy", "request": "launch", "module": "unittest"},
            [{"label": "unused", "type": "shell", "command": "echo", "args": ["${input:x}"]}],
        )
        dialog = self.start(launch_configuration="Plain", breakpoints=[])
        self.assertIn("Approve", dialog["items"])

    def test_attach_without_process_id_is_refused(self):
        self._write(
            {"name": "Pick", "type": "debugpy", "request": "attach", "processId": "${command:pickProcess}"},
            [],
        )
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Pick", breakpoints=[], goal="x")
        self.assertEqual(caught.exception.code, "BAD_REQUEST")
        self.assertIn("pass process_id", caught.exception.message)


class AskDeveloper(HarnessTest):
    def test_the_note_returns_before_the_notification_is_closed_and_is_shown_once(self):
        self.approved()
        result = self.debugger.wait(0.4, ask_developer="move the square")
        self.assertEqual(result["status"], "paused")
        self.assertEqual(self.expect("INFO", 2), "AutoDebug: the AI agent asks you to: move the square")
        self.debugger.wait(0.2, ask_developer="move the square")
        try:
            extra = self.lines.get_nowait()
        except queue.Empty:
            extra = ""
        self.assertFalse(str(extra).startswith("INFO"))


class StepFailure(HarnessTest):
    step_fail = "1"

    def test_a_rejected_step_stays_paused_and_does_not_spend_a_step(self):
        self.approved()
        with self.assertRaises(DebugError):
            self.debugger.step()
        state = self.debugger.wait(2)
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["steps"], "0 of 100 used")


class HungBuild(HarnessTest):
    build_hang = "1"
    build_minute_ms = "40"

    def test_a_build_that_exceeds_build_minutes_is_terminated(self):
        started = time.monotonic()
        self.start(build_task="check", build_minutes=1, wait_seconds=0.2)
        self.send("approve")
        deadline = time.monotonic() + 5
        result = {"status": "building"}
        while result["status"] == "building" and time.monotonic() < deadline:
            result = self.debugger.wait(1)
        self.assertEqual(result["status"], "build_failed", result)
        self.assertEqual(result.get("message"), "the build took longer than 1 minute")
        self.expect("LOG build terminated", 5)
        self.assertLess(time.monotonic() - started, 5)


class ExceptionStop(HarnessTest):
    exception_stop = "1"

    def test_exception_details_arrive_with_the_pause(self):
        _, result = self.approved()
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["exception"]["id"], "AssertionError")
        self.assertIn("2.0 != 1.0", result["exception"]["description"])

    def test_exception_filters_can_be_listed_and_unknown_ids_are_refused(self):
        self.start()
        with self.assertRaises(DebugError) as caught:
            self.debugger.exceptions()
        self.assertEqual(caught.exception.code, "NOT_FOUND")
        self.send("approve")
        self.assertEqual(self.debugger.wait(30)["status"], "paused")
        listed = self.debugger.exceptions()
        self.assertEqual([item["id"] for item in listed["filters"]], ["raised", "uncaught"])
        self.debugger.exceptions(enable=["uncaught"])
        with self.assertRaises(DebugError) as caught:
            self.debugger.exceptions(enable=["nope"])
        self.assertEqual(caught.exception.code, "BAD_REQUEST")
        self.assertIn("unknown exception filters: nope", caught.exception.message)
        self.assertIn("uncaught", caught.exception.message)


class FunctionBreakpoints(HarnessTest):
    def test_function_breakpoints_are_listed_and_logged(self):
        _, result = self.approved(function_breakpoints=["polygon_area"])
        self.assertIn({"at": "function polygon_area", "source": "session", "verified": False}, result["breakpoints"])
        changed = self.debugger.breakpoints(add_functions=["move"])
        self.assertIn("function move", [item["at"] for item in changed["breakpoints"]])
        self.assertTrue(any(event.kind == "breakpoints" and "move" in event.detail for event in self.debugger.timeline))
        self.debugger.stop_session()
        self.expect("LOG stopped")
        self.send("breakpoints")
        self.assertEqual(self.expect("BREAKPOINTS"), "0")


class SourceFolders(HarnessTest):
    def test_source_folders_allow_an_outside_file_and_reject_the_rest(self):
        outside = self.workspace.parent / "addon"
        outside.mkdir()
        extra = outside / "extra.py"
        extra.write_text("value = 1\n", encoding="utf-8")
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(
                launch_configuration="Debug tests", breakpoints=[{"file": str(extra), "line": 1}], goal="x")
        self.assertEqual(caught.exception.code, "OUTSIDE_WORKSPACE")
        self.debugger.close()
        self.debugger = Debugger(find_windows=lambda: discover(self.bridges))
        dialog = self.start(breakpoints=[{"file": str(extra.resolve()), "line": 1}], source_folders=[str(outside.resolve())])
        self.assertIn(str(outside.resolve()), dialog["detail"])


class UnboundMessage(HarnessTest):
    bp_message = "No source file named geometry.cpp"

    def test_the_adapter_message_is_kept(self):
        _, result = self.approved()
        self.assertEqual(
            result["breakpoints"][0]["note"],
            "not bound yet (No source file named geometry.cpp); it may bind when its module loads",
        )


class StopHandling(HarnessTest):
    stack_throw = "1"

    def test_a_stop_error_is_logged_and_the_pause_is_still_reported(self):
        with self.assertLogs("autodebug", "WARNING") as logged:
            _, result = self.approved()
        self.assertEqual(result["status"], "paused")
        self.assertNotIn("location", result)
        self.assertTrue(any("error handling stopped:" in line and "stack trace failed" in line for line in logged.output),
                        logged.output)


class StopThenResume(HarnessTest):
    slow_stack = "80"
    stop_then_continue = "1"

    def test_a_resume_arriving_during_a_stop_is_not_left_paused(self):
        self.approved()
        self.debugger._call("continue")
        time.sleep(0.3)
        self.assertEqual(self.debugger.wait(0.5)["status"], "running")


class FloodedOutput(HarnessTest):
    flood = "7000"  # more than the 5000 events the extension keeps

    def test_heavy_output_never_pushes_out_the_stop(self):
        _, result = self.approved()
        self.assertEqual((result["status"], result["location"]), ("paused", "geometry.py:15"))
        self.assertTrue(result["breakpoints"][0]["verified"])
        self.assertIn("loading part 6999", self.debugger.connection.snapshot()["output"])
        self.assertEqual(self.debugger.step("over")["location"], "geometry.py:12")


class EditorBreakpoint(HarnessTest):
    editor_bp = "geometry.py:12"

    def test_editor_breakpoints_are_listed_and_can_be_run_past(self):
        _, result = self.approved()
        self.assertIn({"at": "geometry.py:12", "source": "editor", "verified": True}, result["breakpoints"])
        reached = self.debugger.continue_(10, until={"file": "geometry.py", "line": 16})
        self.assertEqual(reached["location"], "geometry.py:16")
        self.assertIn("geometry.py:12", reached["skipped_stops"])


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
