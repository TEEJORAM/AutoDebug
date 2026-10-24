"""A real gdb DAP session against the C++ sample. Skipped unless gdb 14+ and g++ exist."""

import os
import re
import shutil
import subprocess
import unittest

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
class RealCpp(HarnessTest):
    debuggers = "cppdbg"

    def setUp(self):
        os.environ["HARNESS_GDB"] = "1"
        self.addCleanup(os.environ.pop, "HARNESS_GDB", None)
        super().setUp()
        binary = self.workspace / "build" / "cpp" / "geometry"
        binary.parent.mkdir(parents=True)
        subprocess.check_call(
            ["g++", "-g", "-O0", "-o", str(binary), str(self.workspace / "cpp" / "geometry.cpp")],
            cwd=self.workspace, timeout=60,
        )
        launch = {
            "version": "0.2.0",
            "configurations": [{
                "name": "Debug C++ direct",
                "type": "cppdbg",
                "request": "launch",
                "program": str(binary),
                "cwd": str(self.workspace),
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
        self.assertTrue(points.get("children") or points.get("expandable"))
        traced = self.debugger.trace("cpp/geometry.cpp", 16, ["total"], hits=3, timeout_seconds=20)
        self.assertGreaterEqual(len(traced["rows"]), 1)
        self.assertIn("total", traced["rows"][0])
        threads = self.debugger.threads()
        self.assertGreaterEqual(len(threads["threads"]), 1)
