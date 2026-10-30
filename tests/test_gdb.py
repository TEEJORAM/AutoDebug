"""A real gdb DAP session against the C++ sample. Skipped unless gdb 14+ and g++ exist."""

import os
import re
import shutil
import subprocess
import sys
import unittest

from autodebug.connection import DebugError
from tests.test_extension import HarnessTest


def _gdb_major() -> int:
    gdb = shutil.which("gdb")
    if not gdb:
        return 0
    try:
        text = subprocess.check_output([gdb, "--version"], text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return 0
    match = re.search(r"(\d+)\.", text)
    return int(match.group(1)) if match else 0


@unittest.skipUnless(_gdb_major() >= 14 and shutil.which("g++"), "needs gdb 14 or later and g++")
@unittest.skipIf(
    sys.platform == "win32",
    "Windows gdb rejects the launch and cannot find sources under the runner temp path; run this test on Linux or macOS",
)
class RealCpp(HarnessTest):
    debuggers = "cppdbg"

    def setUp(self):
        os.environ["HARNESS_GDB"] = "1"
        self.addCleanup(os.environ.pop, "HARNESS_GDB", None)
        super().setUp()
        workspace = self.workspace.resolve()
        source = (workspace / "cpp" / "geometry.cpp").resolve()
        binary = (workspace / "build" / "cpp" / "geometry").resolve()
        binary.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            ["g++", "-g", "-O0", "-o", str(binary), str(source)],
            cwd=str(workspace), timeout=60,
        )
        program = binary if binary.exists() else binary.with_suffix(".exe")
        launch = {
            "version": "0.2.0",
            "configurations": [{
                "name": "Debug C++ direct",
                "type": "cppdbg",
                "request": "launch",
                "program": str(program.resolve()),
                "cwd": str(workspace),
            }],
        }
        (self.workspace / ".vscode" / "launch.json").write_text(__import__("json").dumps(launch), encoding="utf-8")

    def test_cpp_stop_variables_trace_and_threads(self):
        self.approved(launch_configuration="Debug C++ direct", breakpoints=[{"file": "cpp/geometry.cpp", "line": 16}],
                      goal="See the C++ area loop")
        stopped = self.debugger.wait(20)
        self.assertEqual(stopped["status"], "paused", stopped)
        self.assertEqual(stopped["location"], "cpp/geometry.cpp:16")
        points = self.debugger.inspect(names=["points"], depth=1)["variables"][0]
        self.assertTrue(points.get("children"), points)
        self.assertGreaterEqual(len(points["children"]), 1)
        traced = self.debugger.trace("cpp/geometry.cpp", 16, ["total"], hits=3, timeout_seconds=20)
        self.assertGreaterEqual(len(traced["rows"]), 1)
        self.assertTrue(all("total" in row and row["total"] not in ("", "(not defined)") for row in traced["rows"]), traced["rows"])
        threads = self.debugger.threads()
        self.assertGreaterEqual(len(threads["threads"]), 1)


@unittest.skipUnless(_gdb_major() >= 14 and shutil.which("g++"), "needs gdb 14 or later and g++")
@unittest.skipIf(sys.platform == "win32", "see RealCpp")
class RealCppInspection(RealCpp):
    """Hit counts, log points, registers, machine code, memory, instruction and single-thread stepping, valid
    lines and modules with gdb's own Debug Adapter Protocol."""

    def start_loop(self, **breakpoint):
        _, result = self.approved(launch_configuration="Debug C++ direct",
                                  breakpoints=[{"file": "cpp/geometry.cpp", "line": 16, **breakpoint}], goal="C++ loop")
        if result["status"] != "paused":
            result = self.debugger.wait(20)
        return result

    def test_hit_count_and_log_point(self):
        # gdb's own adapter reads a hit condition as how many hits to skip: 2 stops at the third pass.
        result = self.start_loop(hit_condition="2")
        self.assertEqual((result["status"], result["location"]), ("paused", "cpp/geometry.cpp:16"), result)
        i = self.debugger.inspect(names=["i"])["variables"][0]["value"]
        self.assertEqual(i, "2", "the third pass")
        self.debugger.breakpoints(remove=[{"file": "cpp/geometry.cpp", "line": 16}],
                                  add=[{"file": "cpp/geometry.cpp", "line": 16, "log_message": "edge {i}"}])
        self.debugger.breakpoints(add=[{"file": "cpp/geometry.cpp", "line": 18}])
        stopped = self.debugger.continue_(20)
        self.assertEqual(stopped["location"], "cpp/geometry.cpp:18", stopped)

    def test_registers_machine_code_and_memory(self):
        self.start_loop()
        scopes = self.debugger.inspect()["scopes"]
        registers = next(s.split(" (")[0] for s in scopes if s.lower().startswith("register"))
        names = [r["name"] for r in self.debugger.inspect(scope=registers)["variables"]]
        self.assertTrue({"rip", "pc"} & set(names) or any(n.startswith("x") for n in names), names)
        rows = self.debugger.disassemble(before=3, after=5)["instructions"]
        self.assertTrue(any(r.get("current") for r in rows), rows)
        self.assertTrue(all(r["instruction"] for r in rows))
        memory = self.debugger.memory(count=16)
        self.assertEqual(memory.get("count"), 16, memory)
        with self.assertRaises(DebugError) as caught:  # gdb gives memory addresses for pointers only
            self.debugger.memory(name="total", count=8)
        self.assertIn("no memory address for total", caught.exception.message)
        own = [v["name"] for v in self.debugger.inspect()["variables"]]
        self.assertIn("points", own, "Arguments")
        self.assertIn("total", own, "and Locals")

    def test_instruction_and_single_thread_steps(self):
        self.start_loop()
        first = self.debugger.disassemble(before=0, after=1)["instructions"][0]["address"]
        self.debugger.step("over", instruction=True)
        after = self.debugger.disassemble(before=0, after=1)["instructions"][0]["address"]
        self.assertNotEqual(first, after, "one instruction further")
        stepped = self.debugger.step("over", single_thread=True)
        self.assertEqual(stepped["status"], "paused", stepped)

    def test_valid_lines_modules_and_watch(self):
        self.start_loop()
        lines = self.debugger.breakpoints(check={"file": "cpp/geometry.cpp", "line": 11, "end_line": 19})["valid_lines"]["lines"]
        self.assertIn(16, lines)
        self.assertNotIn(10, lines)
        modules = self.debugger.modules()
        self.assertTrue(any("geometry" in str(m.get("path") or m.get("name")) for m in modules["modules"]), modules)
        try:
            self.debugger.watch(add=[{"name": "total"}])
        except DebugError as exc:
            self.assertEqual(exc.code, "NOT_SUPPORTED")
