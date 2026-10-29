"""Hit counts, log points, paging, scopes, hex, exception types, modules and stepping into a chosen call, with the
real Python debugger (debugpy) through the real relay. Skipped without Node.js and debugpy."""

import json
import sys
import unittest

from autodebug.connection import DebugError
from tests.test_debugpy import HAS_DEBUGPY
from tests.test_extension import NODE, HarnessTest

PROGRAM = '''\
LIMIT = 5


def twice(n):
    return n * 2


def helper(n):
    return n + 1


def main():
    items = [i * i for i in range(10000)]
    total = 0
    for i in range(LIMIT):
        total += helper(twice(i))
    try:
        {}["missing"]
    except KeyError:
        pass
    try:
        int("x")
    except ValueError:
        pass
    print("done", total, len(items))


main()
'''
LOOP = 16  # total += helper(twice(i))
KEY_ERROR = 18
PRINT = 25


@unittest.skipIf(NODE is None or not HAS_DEBUGPY, "needs Node.js and debugpy")
class RealDebugpyInspection(HarnessTest):
    debugpy = sys.executable
    start_defaults = {"launch_configuration": "Debug loop", "breakpoints": [{"file": "loop.py", "line": LOOP}]}

    def setUp(self):
        super().setUp()
        (self.workspace / "loop.py").write_text(PROGRAM, encoding="utf-8")
        launch = json.loads((self.workspace / ".vscode" / "launch.json").read_text(encoding="utf-8"))
        launch["configurations"].append({"name": "Debug loop", "type": "debugpy", "request": "launch",
                                         "program": "${workspaceFolder}/loop.py", "cwd": "${workspaceFolder}",
                                         "console": "internalConsole", "justMyCode": True})
        (self.workspace / ".vscode" / "launch.json").write_text(json.dumps(launch), encoding="utf-8")

    def values(self, result):
        return {v["name"]: v["value"] for v in result["variables"]}

    def test_log_point(self):
        _, result = self.approved(breakpoints=[{"file": "loop.py", "line": LOOP, "log_message": "pass {i}: total={total}"},
                                               {"file": "loop.py", "line": PRINT}])
        self.assertEqual(result["location"], f"loop.py:{PRINT}", result)
        output = self.debugger.connection.snapshot()["output"]
        self.assertTrue(any("pass 0: total=0" in line for line in output), output)
        self.assertTrue(any("pass 4: total=" in line for line in output), output)

    def test_hit_count(self):
        _, result = self.approved(breakpoints=[{"file": "loop.py", "line": LOOP, "hit_condition": "3"}])
        self.assertEqual(result["location"], f"loop.py:{LOOP}", result)
        self.assertEqual(self.values(result)["i"], "2", "stops at the 3rd pass")

    def test_paging_scopes_and_hex(self):
        _, result = self.approved()
        items = self.debugger.inspect(names=["items"], start=5000, count=3)["variables"][0]
        self.assertEqual([c["value"] for c in items.get("children", [])], ["25000000", "25010001", "25020004"], items)
        self.assertEqual(items["page"]["total"], 10000)
        self.assertEqual(self.debugger.inspect(names=["items[9999]"])["variables"][0]["value"], str(9999 * 9999))
        scopes = self.debugger.inspect()["scopes"]
        self.assertIn("Globals", scopes)
        globals_ = {v["name"]: v["value"] for v in self.debugger.inspect(scope="Globals")["variables"]}
        self.assertEqual(globals_["LIMIT"], "5")
        self.debugger.continue_(10)
        self.debugger.continue_(10)
        hexed = {v["name"]: v["value"] for v in self.debugger.inspect(names=["total", "i"], hex=True)["variables"]}
        self.assertEqual(hexed["i"], "0x2")
        self.assertEqual(hexed["total"], "0x4", "1 + 3 after two passes")

    def test_step_into_a_chosen_call(self):
        self.approved()
        stepped = self.debugger.step("into", target="helper")
        self.assertEqual(stepped["location"], "loop.py:9", stepped)
        self.assertEqual(self.debugger.stack()["frames"][0]["function"], "helper")

    def test_stop_only_for_one_exception_type(self):
        _, result = self.approved()
        self.debugger.breakpoints(remove=[{"file": "loop.py", "line": LOOP}])
        self.debugger.exceptions(enable=["raised"], types=["KeyError"])
        stopped = self.debugger.continue_(15)
        self.assertEqual((stopped["status"], stopped["location"]), ("paused", f"loop.py:{KEY_ERROR}"), stopped)
        self.assertEqual(stopped["exception"]["id"], "KeyError")
        ended = self.debugger.continue_(15)
        self.assertEqual(ended["status"], "ended", "the ValueError is not a KeyError: no stop")

    def test_modules_and_watch_refused(self):
        self.approved()
        listed = self.debugger.modules(filter="loop")
        self.assertTrue(any(m.get("name") == "__main__" or "loop" in str(m.get("path")) for m in listed["modules"]), listed)
        with self.assertRaises(DebugError) as caught:
            self.debugger.watch(add=[{"name": "total"}])
        self.assertEqual(caught.exception.code, "NOT_SUPPORTED")


if __name__ == "__main__":
    unittest.main()
