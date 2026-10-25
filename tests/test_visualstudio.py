"""The Visual Studio relay's shared core (src/autodebug/visualstudio/Core) through its
test harness, with a scripted C++ program in place of Visual Studio, driven by the
real Python tools over the real protocol. Skipped without the .NET SDK."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from autodebug.connection import Connection, DebugError, discover
from tests.test_extension import ROOT, HarnessMixin

DOTNET = shutil.which("dotnet")
SOURCE = ROOT / "src" / "autodebug" / "visualstudio"
_BUILT: dict[str, Path] = {}


def harness_dll() -> Path:
    """Build the harness once per source version and return its assembly."""
    files = sorted((SOURCE / "Core").glob("*.cs")) + sorted((SOURCE / "Harness").glob("*.*"))
    digest = hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()[:16]
    if digest not in _BUILT:
        out = Path(tempfile.gettempdir()) / f"autodebug-vs-harness-{digest}"
        dll = out / "AutoDebug.Harness.dll"
        if not dll.exists():
            env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
            result = subprocess.run([DOTNET, "build", str(SOURCE / "Harness"), "-c", "Release", "-o", str(out)],
                                    capture_output=True, text=True, timeout=600, env=env)
            if result.returncode != 0:
                raise RuntimeError(f"the harness did not build:\n{result.stdout[-4000:]}")
        _BUILT[digest] = dll
    return _BUILT[digest]


@unittest.skipIf(DOTNET is None, "needs the .NET SDK")
class VisualStudioTest(HarnessMixin, unittest.TestCase):
    debuggers = "visualstudio"
    start_defaults = {"launch_configuration": "geometry (Debug|x64)", "breakpoints": [{"file": "cpp/geometry.cpp", "line": 16}]}

    def harness_command(self, bridges: Path, workspace: Path) -> list[str]:
        return [DOTNET, str(harness_dll()), str(bridges), str(workspace)]


class NoAnswer(VisualStudioTest):
    approval_ms = "300"

    def test_unanswered_dialog_is_closed_and_refused(self):
        start = self.debugger.start_session(**self.start_defaults, goal="x", wait_seconds=0)
        self.assertIn("closes unanswered after 2 minutes", start["next"])
        self.expect("DIALOG")
        self.assertEqual(self.expect("DIALOG_CLOSED", 5), "")
        result = self.debugger.wait(5)
        self.assertEqual((result["status"], result["reason"]), ("denied", "no answer within 2 minutes"))
        self.assertIn("not a Deny", result["next"])
        self.send("approve")  # a click after the dialog closed starts nothing
        self.assertEqual(self.debugger.wait(0.5)["status"], "denied")


class Session(VisualStudioTest):
    def test_the_window_is_found_as_visual_studio(self):
        (window,) = discover(self.bridges)
        self.assertEqual((window.ide, window.current), ("visualstudio", True))
        (listed,) = self.debugger.list_targets()["windows"]
        names = [c["name"] for c in listed["folders"][0]["launch"]]
        self.assertEqual(names, ["geometry (Debug|x64)", "Attach to a process (native)"])
        self.assertIn("Visual Studio", self.debugger.start_session(**self.start_defaults, goal="x", wait_seconds=0)["next"])

    def test_dialog_shows_exactly_what_will_run(self):
        dialog = self.start(build_task="Build geometry (Debug|x64)", max_steps=7)
        self.assertEqual((dialog["modal"], dialog["items"]), (True, ["Approve"]))
        for expected in ("Goal: Find why moving a shape changes its area",
                         'Build first: "Build geometry (Debug|x64)": build project geometry (Debug|x64)',
                         '"geometry (Debug|x64)" (visualstudio)', "Breakpoints: cpp/geometry.cpp:16", "Limits: 7 steps",
                         "When the session ends: the program is stopped", '"configuration": "Debug|x64"'):
            self.assertIn(expected, dialog["detail"])

    def test_full_session(self):
        _, result = self.approved(build_task="Build geometry (Debug|x64)")
        self.assertEqual((result["status"], result["location"]), ("paused", "cpp/geometry.cpp:16"))
        self.assertTrue(result["breakpoints"][0]["verified"])
        self.assertEqual({v["name"]: v["value"] for v in result["variables"]}["password"], "***REDACTED***")
        step = self.debugger.step("over")
        self.assertEqual(step["location"], "cpp/geometry.cpp:13")
        self.assertIn({"name": "total", "before": "0", "after": "-1"}, step["changed"])
        self.assertEqual(self.debugger.stack()["frames"][1]["location"], "cpp/geometry.cpp:37")
        trace = self.debugger.trace("cpp/geometry.cpp", 16, ["i", "total"], hits=5)
        self.assertEqual([(r["i"], r["total"]) for r in trace["rows"]], [("1", "-1 → 2"), ("2", "2 → 4")])
        report = Path(self.debugger.write_report(title="Area bug", problem="p", root_cause="r", solution="s",
                                                 confidence="likely")["report_file"]).read_text(encoding="utf-8")
        self.assertIn("| build | Build geometry (Debug\\|x64) | succeeded, exit code 0 |", report)
        self.assertLess(report.index("| approved |"), report.index("| build |"))
        self.assertIn("| trace | cpp/geometry.cpp:16 |", report)

    def test_nested_values_threads_and_redaction(self):
        self.approved()
        self.assertEqual([t["name"] for t in self.debugger.threads()["threads"]], ["main", "worker"])
        self.assertEqual(self.debugger.inspect(names=["points[2]"])["variables"][0]["value"], "(3, 2)")
        self.assertEqual(self.debugger.inspect(names=["mesh->verts[2].co"])["variables"][0]["value"], "(1, 2, 3)")
        hidden = self.debugger.inspect(names=["credentials"], depth=1)["variables"][0]["children"][0]
        self.assertEqual((hidden["name"], hidden["value"]), ("note", "***REDACTED***"))

    def test_the_program_ends_and_breakpoints_are_removed(self):
        self.approved()
        self.debugger.breakpoints(remove=[{"file": "cpp/geometry.cpp", "line": 16}])
        ended = self.debugger.continue_(10)
        self.assertEqual((ended["status"], ended["exit_code"]), ("ended", 1))
        self.assertEqual(ended["output"][-1], "geometry: 1 of 3 shapes change area when moved")
        self.send("breakpoints")
        self.assertEqual(self.expect("BREAKPOINTS"), "0")

    def test_denied_and_busy(self):
        self.start()
        self.send("deny")
        self.assertEqual(self.debugger.wait(10)["status"], "denied")
        self.approved()
        from autodebug.tools import Debugger
        with self.assertRaises(DebugError) as caught:
            Debugger(find_windows=lambda: discover(self.bridges)).start_session(**self.start_defaults, goal="x")
        self.assertEqual(caught.exception.code, "BUSY")

    def test_ask_developer_and_stop(self):
        self.approved()
        self.debugger.wait(0.3, ask_developer="Delete the last item")
        self.assertEqual(self.expect("INFO", 5), "AutoDebug: the AI agent asks you to: Delete the last item")
        self.debugger.stop_session()
        self.assertEqual(json.loads(self.expect("DISCONNECT")), {"detach": False})


class Attach(VisualStudioTest):
    def test_attach_needs_a_process_and_detaches(self):
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Attach to a process (native)", breakpoints=[], goal="x")
        self.assertIn("pass process_id", caught.exception.message)
        self.debugger.close()
        dialog = self.start(launch_configuration="Attach to a process (native)", process_id=os.getpid())
        self.assertIn(f"Attach to: process {os.getpid()}", dialog["detail"])
        self.assertIn("the debugger detaches and the program keeps running", dialog["detail"])
        self.send("approve")
        self.assertEqual(self.debugger.wait(10)["status"], "paused")
        self.debugger.stop_session()
        self.assertEqual(json.loads(self.expect("DISCONNECT")), {"detach": True})


class Guards(VisualStudioTest):
    def test_the_relay_refuses_what_was_not_approved(self):
        (window,) = discover(self.bridges)
        connection = Connection(window)
        self.addCleanup(connection.close)
        launch = {"name": "x", "type": "visualstudio", "request": "launch", "program": "x.exe"}
        with self.assertRaises(DebugError) as caught:
            connection.call("approve", {"launch": launch, "breakpoints": [{"file": str(self.workspace.parent / "x.cpp"), "line": 1}]})
        self.assertEqual(caught.exception.code, "OUTSIDE_WORKSPACE")
        with self.assertRaises(DebugError) as caught:
            connection.call("dap", {"command": "next"})
        self.assertEqual(caught.exception.code, "NOT_FOUND")  # nothing approved, nothing runs
        self.approved(max_steps=1)
        for command in ("evaluate", "setVariable", "setExpression", "disconnect"):
            with self.assertRaises(DebugError) as caught:
                connection.call("dap", {"command": command, "arguments": {"expression": "1"}})
            self.assertEqual(caught.exception.code, "BAD_REQUEST", command)
        connection.call("dap", {"command": "next", "arguments": {"threadId": 1}})
        with self.assertRaises(DebugError) as caught:
            connection.call("dap", {"command": "next", "arguments": {"threadId": 1}})
        self.assertEqual(caught.exception.code, "LIMIT")

    def test_a_deleted_connection_file_is_written_again(self):
        (window,) = discover(self.bridges)
        for path in self.bridges.glob("*.json"):
            path.unlink()
        self.expect("LOG the connection file was deleted; wrote it again", 5)
        self.assertEqual([w.port for w in discover(self.bridges)], [window.port])

    def test_the_connection_file_goes_away_with_visual_studio(self):
        self.send("exit")
        self.node.wait(10)
        self.assertEqual(discover(self.bridges), [])


class LateBinding(VisualStudioTest):
    late_bp = "1"

    def test_a_breakpoint_binds_when_the_module_loads(self):
        _, result = self.approved()
        self.assertEqual(result["location"], "cpp/geometry.cpp:16")
        self.assertTrue(result["breakpoints"][0]["verified"])


class UnboundMessage(VisualStudioTest):
    bp_message = "The breakpoint will not currently be hit. No symbols have been loaded for this document."

    def test_the_debugger_message_is_kept(self):
        self.start()
        self.send("approve")
        time.sleep(0.5)
        note = self.debugger.wait(1)["breakpoints"][0]["note"]
        self.assertIn("No symbols have been loaded for this document.", note)


class Flood(VisualStudioTest):
    flood = "7000"

    def test_heavy_output_never_pushes_out_the_stop(self):
        _, result = self.approved()
        self.assertEqual((result["status"], result["location"]), ("paused", "cpp/geometry.cpp:16"))


class ExceptionStop(VisualStudioTest):
    exception_stop = "1"

    def test_exception_details_and_filters(self):
        _, result = self.approved()
        self.assertEqual(result["exception"]["id"], "std::out_of_range")
        self.assertEqual([f["id"] for f in self.debugger.exceptions()["filters"]], ["cpp", "win32"])
        self.debugger.exceptions(enable=["cpp"])


class Builds(VisualStudioTest):
    build_exit = 2

    def test_a_failed_build_launches_nothing(self):
        _, result = self.approved(build_task="Build geometry (Debug|x64)")
        self.assertEqual((result["status"], result["exit_code"]), ("build_failed", 2))


class HungBuild(VisualStudioTest):
    build_hang = "1"
    build_minute_ms = "40"

    def test_a_build_that_exceeds_build_minutes_is_cancelled(self):
        self.start(build_task="Build geometry (Debug|x64)", build_minutes=1)
        self.send("approve")
        deadline = time.monotonic() + 5
        result = {"status": "building"}
        while result["status"] in ("building", "awaiting_approval", "starting") and time.monotonic() < deadline:
            result = self.debugger.wait(1)
        self.assertEqual((result["status"], result.get("message")), ("build_failed", "the build took longer than 1 minute"))
        self.expect("LOG build terminated", 5)


class EditorBreakpoint(VisualStudioTest):
    editor_bp = "cpp/geometry.cpp:13"

    def test_the_developers_breakpoints_are_listed_and_run_past(self):
        _, result = self.approved()
        self.assertEqual(result["location"], "cpp/geometry.cpp:13")
        self.assertIn("cpp/geometry.cpp:13", [b["at"] for b in result["breakpoints"] if b["source"] == "editor"])
        reached = self.debugger.continue_(10, until={"file": "cpp/geometry.cpp", "line": 18})
        self.assertEqual(reached["location"], "cpp/geometry.cpp:18")


class NoEvaluation(unittest.TestCase):
    def test_the_extension_never_evaluates_or_writes_values(self):
        for path in SOURCE.rglob("*.cs"):
            source = path.read_text(encoding="utf-8")
            for forbidden in ("GetExpression", "ExecuteStatement", "SetValueAsString", ".Value ="):
                self.assertNotIn(forbidden, source, f"{path.name} uses {forbidden}")


if __name__ == "__main__":
    unittest.main()
