"""Breakpoint options, watchpoints, paging, scopes, modules, code without a file, machine code, memory, stepping
options and child debug sessions: the real relay (relay.js) and the real Python tools against the scripted debug
adapter (tests/fake_adapter.py), which prints what it was sent. Skipped without Node.js."""

import json
import os
import unittest

from autodebug.connection import DebugError
from tests.test_extension import HarnessTest


def sent(output: list[str], what: str) -> dict:
    """The last request of this kind the scripted adapter printed."""
    line = next(line for line in reversed(output) if line.startswith(f"sent {what} "))
    return json.loads(line[len(f"sent {what} "):])


class BreakpointOptions(HarnessTest):
    def test_hit_condition_skips_the_first_passes(self):
        dialog, result = self.approved(breakpoints=[{"file": "geometry.py", "line": 15, "hit_condition": ">=2"}])
        self.assertIn("geometry.py:15 at hit >=2", dialog["detail"])
        values = {v["name"]: v["value"] for v in result["variables"]}
        self.assertEqual((result["location"], values["i"]), ("geometry.py:15", "1"), "the first pass (i = 0) is skipped")
        self.assertEqual(result["breakpoints"][0]["hits"], ">=2")

    def test_log_point_prints_without_stopping(self):
        dialog, result = self.approved(breakpoints=[{"file": "geometry.py", "line": 15, "log_message": "i={i} total={total}"},
                                                    {"file": "geometry.py", "line": 16}])
        self.assertIn('logs "i={i} total={total}" without stopping', dialog["detail"])
        self.assertEqual(result["location"], "geometry.py:16", "the log point did not stop the program")
        output = self.debugger.connection.snapshot()["output"]
        self.assertIn("i=1 total=-1.0", output)
        self.assertIn("i=2 total=2.0", output)

    def test_log_message_cannot_be_an_expression(self):
        with self.assertRaises(DebugError) as caught:
            self.start(breakpoints=[{"file": "geometry.py", "line": 15, "log_message": "{total * 2}"}])
        self.assertIn("variables by name only", caught.exception.message)

    def test_column_reaches_the_debugger(self):
        self.approved(breakpoints=[{"file": "geometry.py", "line": 15, "column": 9}])
        options = sent(self.debugger.connection.snapshot()["output"], "setBreakpoints")
        self.assertEqual(options, [{"column": 9, "line": 15}])

    def test_valid_lines(self):
        self.approved()
        found = self.debugger.breakpoints(check={"file": "geometry.py", "line": 10, "end_line": 20})
        self.assertEqual(found["valid_lines"]["lines"], [12, 15, 16])


class Watchpoints(HarnessTest):
    def test_stops_where_the_watched_value_changes(self):
        _, first = self.approved(breakpoints=[{"file": "geometry.py", "line": 15}])
        watched = self.debugger.watch(add=[{"name": "total"}])
        self.assertEqual(watched["watches"], [{"name": "total", "access": "write", "verified": True, "what": "total (8 bytes)"}])
        self.debugger.breakpoints(remove=[{"file": "geometry.py", "line": 15}])
        stopped = self.debugger.continue_(10)
        self.assertEqual(stopped["status"], "paused")
        self.assertEqual(stopped["reason"], "data breakpoint: total changed")
        self.assertEqual({v["name"]: v["value"] for v in stopped["variables"]}["total"], "-1.0")
        self.assertEqual(stopped["watches"][0]["name"], "total")
        self.assertEqual(self.debugger.watch(remove=["total"])["watches"], [])

    def test_unknown_variable_and_unwatchable_value(self):
        self.approved()
        with self.assertRaises(DebugError) as caught:
            self.debugger.watch(add=[{"name": "nothing"}])
        self.assertEqual(caught.exception.code, "NOT_FOUND")
        with self.assertRaises(DebugError) as caught:
            self.debugger.watch(add=[{"name": "points"}])
        self.assertEqual(caught.exception.code, "NOT_SUPPORTED")
        self.assertIn("not in memory the debugger can watch", caught.exception.message)


class PlainDebugger(HarnessTest):
    def setUp(self):
        os.environ["HARNESS_PLAIN"] = "1"
        self.addCleanup(os.environ.pop, "HARNESS_PLAIN", None)
        super().setUp()

    def test_what_the_debugger_cannot_do_is_said_plainly(self):
        self.approved()
        for call, words in ((lambda: self.debugger.watch(add=[{"name": "total"}]), "stop when a value changes"),
                            (lambda: self.debugger.disassemble(), "disassemble"),
                            (lambda: self.debugger.memory(name="points"), "read memory"),
                            (lambda: self.debugger.step("back"), "step backwards"),
                            (lambda: self.debugger.inspect(hex=True), "hex"),
                            (lambda: self.debugger.step("into", target="len"), "step into a chosen call")):
            with self.assertRaises(DebugError) as caught:
                call()
            self.assertEqual(caught.exception.code, "NOT_SUPPORTED")
            self.assertIn(words, caught.exception.message)
            self.assertIn("(debugpy)", caught.exception.message)


class Variables(HarnessTest):
    def test_large_arrays_page(self):
        self.approved()
        items = self.debugger.inspect(names=["items"], depth=1)["variables"][0]
        self.assertEqual((items["size"], len(items["children"]), items["more"]), (10000, 50, 9950))
        page = self.debugger.inspect(names=["items"], start=5000, count=3)["variables"][0]
        self.assertEqual([c["value"] for c in page["children"]], ["25000000", "25010001", "25020004"])
        self.assertEqual(page["page"], {"start": 5000, "count": 3, "total": 10000})
        one = self.debugger.inspect(names=["items[9999]"])["variables"][0]
        self.assertEqual(one["value"], str(9999 * 9999))

    def test_scopes_by_name_and_hex(self):
        self.approved()
        result = self.debugger.inspect()
        self.assertEqual(result["scopes"], ["Locals", "Globals", "Registers (slow)"])
        registers = self.debugger.inspect(scope="registers")["variables"]
        self.assertEqual([r["name"] for r in registers], ["rip", "rsp"])
        self.assertEqual(self.debugger.inspect(scope="Globals")["variables"][0]["name"], "Point")
        with self.assertRaises(DebugError) as caught:
            self.debugger.inspect(scope="Statics")
        self.assertIn("this frame has: Locals, Globals, Registers", caught.exception.message)
        values = {v["name"]: v["value"] for v in self.debugger.inspect(hex=True)["variables"]}
        self.assertEqual(values["i"], "0x0")
        self.assertEqual(self.debugger.inspect(names=["items"], start=255, count=1, hex=True)["variables"][0]["children"][0]["value"],
                         hex(255 * 255))


class Exceptions(HarnessTest):
    def test_conditions_and_types_reach_the_debugger(self):
        self.approved()
        listed = self.debugger.exceptions()
        self.assertEqual([(f["id"], f["condition"]) for f in listed["filters"]], [("raised", True), ("uncaught", False)])
        self.assertTrue(listed["types_supported"])
        self.debugger.exceptions(enable=["uncaught", {"id": "raised", "condition": "x is None"}], types=["KeyError"],
                                 mode="unhandled")
        self.debugger.step("over")  # the scripted adapter's output reaches the state at the next stop
        request = sent(self.debugger.connection.snapshot()["output"], "setExceptionBreakpoints")
        self.assertEqual(request["filters"], ["uncaught"])
        self.assertEqual(request["filterOptions"], [{"condition": "x is None", "filterId": "raised"}])
        self.assertEqual(request["exceptionOptions"],
                         [{"breakMode": "unhandled", "path": [{"names": ["Python Exceptions"]}, {"names": ["KeyError"]}]}])
        with self.assertRaises(DebugError) as caught:
            self.debugger.exceptions(enable=[{"id": "uncaught", "condition": "x"}])
        self.assertIn("filter uncaught takes no condition", caught.exception.message)


class ModulesAndCode(HarnessTest):
    def test_modules_sources_and_activity(self):
        _, result = self.approved()
        self.assertIn("thread 2 started", result["activity"])
        self.assertIn("module geometry loaded (Symbols loaded.)", result["activity"])
        self.assertIn("debugger: Loading symbols (geometry)", result["activity"])
        self.assertNotIn("activity", self.debugger.step("over"), "activity is shown once")
        modules = self.debugger.modules()
        self.assertEqual(modules["total"], 2)
        libm = self.debugger.modules(filter="libm")["modules"]
        self.assertEqual(libm, [{"name": "libm.so.6", "path": "/usr/lib/libm.so.6", "version": "2.39",
                                 "symbols": "Symbols not found.", "optimized": True}])
        sources = self.debugger.modules(sources=True)["sources"]
        self.assertIn({"name": "<generated>", "path": None, "source_reference": 77}, sources)

    def test_machine_code_and_memory(self):
        self.approved()
        rows = self.debugger.disassemble(before=2, after=3)["instructions"]
        self.assertEqual([r["address"] for r in rows], ["0x1008", "0x100c", "0x1010", "0x1014", "0x1018"])
        current = [r for r in rows if r.get("current")]
        self.assertEqual((current[0]["address"], current[0]["symbol"]), ("0x1010", "polygon_area"))
        memory = self.debugger.memory(name="points", count=20)
        self.assertEqual(memory["count"], 20)
        self.assertTrue(memory["rows"][0].startswith("+00000  02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f 10 11"), memory)
        self.assertEqual(self.debugger.memory(name="buffer")["bytes"], "***REDACTED***")
        self.assertEqual(self.debugger.memory(name="settings.api_token")["bytes"], "***REDACTED***")
        self.assertEqual(self.debugger.memory()["unreadable"], 64)


class NoSource(HarnessTest):
    def setUp(self):
        os.environ["HARNESS_NO_SOURCE"] = "1"
        self.addCleanup(os.environ.pop, "HARNESS_NO_SOURCE", None)
        super().setUp()

    def test_code_without_a_file(self):
        _, result = self.approved()
        self.assertEqual(result["location"], "(no file) <generated>:15")
        self.assertEqual(self.debugger.stack()["frames"][0]["location"], "(no source)")
        code = self.debugger.source()
        self.assertEqual(code["line"], 15)
        self.assertIn("   15> // generated line 15", code["code"])
        self.assertTrue(any("***REDACTED***" in line for line in code["code"]), "a token in the code is hidden")
        self.assertFalse(any("ghp_" in line for line in code["code"]))
        self.assertEqual(self.debugger.source(source_reference=77)["total_lines"], 31)


class Stepping(HarnessTest):
    def test_target_single_thread_and_instruction_reach_the_debugger(self):
        self.approved()
        self.debugger.step("into", target="len")
        self.assertEqual(sent(self.debugger.connection.snapshot()["output"], "step"), {"targetId": 2, "threadId": 1})
        self.debugger.step("over", single_thread=True, instruction=True)
        self.assertEqual(sent(self.debugger.connection.snapshot()["output"], "step"),
                         {"granularity": "instruction", "singleThread": True, "threadId": 1})
        with self.assertRaises(DebugError) as caught:
            self.debugger.step("into", target="print")
        self.assertIn("calls here: range, len", caught.exception.message)
        with self.assertRaises(DebugError):
            self.debugger.step("over", target="len")

    def test_backwards(self):
        _, first = self.approved()
        forward = self.debugger.continue_(10)
        self.assertEqual({v["name"]: v["value"] for v in forward["variables"]}["i"], "1")
        back = self.debugger.continue_(10, reverse=True)
        self.assertEqual({v["name"]: v["value"] for v in back["variables"]}["i"], "0")
        stepped = self.debugger.step("back")
        self.assertEqual(stepped["location"], "geometry.py:12")
        self.assertEqual(stepped["steps"], "1 of 100 used")


class ChildSessions(HarnessTest):
    """The program runs in a child debug session that the approved session starts (Node.js, browsers)."""

    def setUp(self):
        os.environ["HARNESS_CHILD"] = "1"
        self.addCleanup(os.environ.pop, "HARNESS_CHILD", None)
        super().setUp()

    def test_the_child_session_is_debugged(self):
        _, result = self.approved()
        self.assertEqual((result["status"], result["location"]), ("paused", "geometry.py:15"))
        self.assertTrue(result["breakpoints"][0]["verified"])
        self.assertIn("debug session started: Debug tests: geometry.py", result["activity"])
        self.assertEqual({v["name"]: v["value"] for v in result["variables"]}["i"], "0")
        self.assertEqual(self.debugger.step("over")["location"], "geometry.py:12")
        self.assertEqual(len(self.debugger.threads()["threads"]), 2, "the child's threads, not the launcher's (none)")
        self.debugger.breakpoints(remove=[{"file": "geometry.py", "line": 15}])
        ended = self.debugger.continue_(15)
        self.assertEqual((ended["status"], ended["exit_code"]), ("ended", 1))
        self.assertEqual(ended["output"][-1], "AssertionError: 2.0 != 1.0")


class OneTest(HarnessTest):
    def test_test_sets_the_arguments(self):
        dialog = self.start(test="test_geometry.GeometryTest.test_area_does_not_change_when_moved")
        self.assertIn("Runs one test only: test_geometry.GeometryTest.test_area_does_not_change_when_moved", dialog["detail"])
        self.assertIn('"Debug tests" (debugpy) unittest test_geometry.GeometryTest.test_area_does_not_change_when_moved',
                      dialog["detail"])

    def test_test_and_args_together_are_refused(self):
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Debug tests", breakpoints=[], goal="x", test="t", args=["-v"])
        self.assertIn("pass test or args, not both", caught.exception.message)
        with self.assertRaises(DebugError) as caught:
            self.debugger.start_session(launch_configuration="Debug report.py", breakpoints=[], goal="x", test="t")
        self.assertIn("pytest, unittest, go test, jest or vitest", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
