"""The AutoDebug service: the command line and the MCP server share one session through it."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from autodebug import hub
from autodebug.cli import main, parse_tool_arguments
from autodebug.connection import discover
from autodebug.tools import Debugger
from tests.fake_extension import FakeExtension

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class ServiceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.state = self.root / "state"
        self.workspace = self.root / "AutoDebugDemo"
        self.workspace.mkdir()
        (self.workspace / "geometry.py").write_text("# scripted\n", encoding="utf-8")
        self.fake = FakeExtension(self.state / "bridges", str(self.workspace))
        self.addCleanup(self.fake.close)
        self.env = dict(os.environ, AUTODEBUG_HOME=str(self.state))
        old = os.environ.get("AUTODEBUG_HOME")
        os.environ["AUTODEBUG_HOME"] = str(self.state)
        self.addCleanup(lambda: os.environ.__setitem__("AUTODEBUG_HOME", old) if old is not None
                        else os.environ.pop("AUTODEBUG_HOME", None))
        self.addCleanup(self.stop_service)

    def stop_service(self):
        info = hub._read_info()
        if info:
            try:
                hub._request(info, {"op": "shutdown", "force": True}, 3)
            except (OSError, ValueError):
                pass
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and hub.hub_file().exists():
                time.sleep(0.05)
        # On Windows the exiting service still holds hub.log open for a moment; wait until it lets go.
        log = self.state / "hub.log"
        deadline = time.monotonic() + 15
        while log.exists() and time.monotonic() < deadline:
            try:
                log.unlink()
            except PermissionError:
                time.sleep(0.1)

    def cli(self, *args: str) -> tuple[int, dict]:
        """`python src/autodebug run ...` exactly as an agent's terminal runs it: no install, no PYTHONPATH."""
        env = {k: v for k, v in self.env.items() if k != "PYTHONPATH"}
        done = subprocess.run([sys.executable, str(SRC / "autodebug"), "run", *args], capture_output=True,
                              text=True, encoding="utf-8", env=env, timeout=120, cwd=self.root)
        self.assertEqual(done.stderr.strip(), "")
        return done.returncode, json.loads(done.stdout)


class CommandLineAndMcpShareOneSession(ServiceTest):
    def test_session_started_from_the_terminal_continues_over_mcp(self):
        code, targets = self.cli("list_targets")
        self.assertEqual(code, 0)
        self.assertEqual(targets["windows"][0]["ide"], "cursor")
        running = hub.status()
        self.assertEqual(running["version"], __import__("autodebug").__version__)

        code, started = self.cli("start_session", "launch_configuration=Debug tests", "breakpoints=geometry.py:15",
                                 "goal=find why the area changes", "wait_seconds=0")
        self.assertEqual((code, started["status"]), (0, "awaiting_approval"))
        self.assertTrue(hub.status()["busy"])
        self.fake.approve()

        # A separate MCP server process (what Cursor starts) sees the same session and stops it.
        server = subprocess.Popen([sys.executable, "-m", "autodebug", "serve"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, env=dict(self.env, PYTHONPATH=str(SRC)))
        self.addCleanup(server.kill)

        def ask(request_id, name, arguments):
            message = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}
            server.stdin.write(json.dumps(message).encode() + b"\n")
            server.stdin.flush()
            return json.loads(server.stdout.readline())["result"]["structuredContent"]

        paused = ask(1, "wait", {"timeout_seconds": 5})
        self.assertEqual((paused["status"], paused["location"]), ("paused", "geometry.py:15"))
        self.assertEqual(ask(2, "stop_session", {})["status"], "ended")
        server.stdin.close()
        server.wait(10)
        server.stdout.close()

        # Back on the terminal: the report has the whole timeline, including the MCP part.
        code, report = self.cli("write_report", "title=Area", "problem=p", "root_cause=r", "solution=s",
                                "confidence=unconfirmed")
        self.assertEqual(code, 0)
        text = Path(report["report_file"]).read_text(encoding="utf-8")
        self.assertIn("| approved |", text)
        self.assertIn("| stopped | geometry.py:15 |", text)

    def test_tool_errors_and_bad_arguments(self):
        code, result = self.cli("stack")
        self.assertEqual((code, result["error"]), (1, "NOT_FOUND"))
        done = subprocess.run([sys.executable, str(SRC / "autodebug"), "run", "stack", "depth=2"],
                              capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 2)
        self.assertIn("stack has no argument 'depth'", done.stderr)


class InProcess(ServiceTest):
    def serve(self, **kwargs) -> hub.Hub:
        service = hub.Hub(Debugger(find_windows=lambda: discover(self.state / "bridges")), **kwargs)
        thread = threading.Thread(target=service.serve, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not hub.status() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.addCleanup(thread.join, 5)
        return service

    def test_wrong_token_is_refused(self):
        service = self.serve()
        info = {**hub._read_info(), "token": "0" * 48}
        self.assertEqual(hub._request(info, {"op": "call", "name": "list_targets"}, 3)["error"], "BAD_TOKEN")
        self.assertEqual(hub.call("list_targets", {})[1], False)
        self.assertEqual(service.port, hub._read_info()["port"])

    def test_idle_service_exits_and_removes_its_file(self):
        self.serve(idle_seconds=0.3)
        self.assertTrue(hub.hub_file().exists())
        deadline = time.monotonic() + 5
        while hub.hub_file().exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(hub.hub_file().exists())

    def test_a_service_running_older_code_is_replaced_when_idle(self):
        self.serve().code = "0" * 16  # a service left running from before an update, in this test process
        self.assertEqual(hub.status()["pid"], os.getpid())
        info = hub.connect_service()
        replacement = hub._ping(info)
        self.assertNotEqual(replacement["pid"], os.getpid())  # a new background service took over
        self.assertEqual(replacement["code"], hub.code_id())

    def test_an_open_session_keeps_the_service(self):
        service = self.serve(idle_seconds=0.3)
        result, _ = hub.call("start_session", {"launch_configuration": "Debug tests", "goal": "x", "wait_seconds": 0,
                                               "breakpoints": [{"file": "geometry.py", "line": 15}]})
        self.assertEqual(result["status"], "awaiting_approval")
        time.sleep(1)
        self.assertTrue(hub.status()["busy"])
        self.assertFalse(hub._request(hub._read_info(), {"op": "shutdown"}, 3)["ok"])
        hub.call("stop_session", {})
        self.assertFalse(service.busy())


class Arguments(unittest.TestCase):
    def test_values_need_no_json(self):
        self.assertEqual(parse_tool_arguments("start_session", [
            "launch_configuration=geometry (Debug|x64)", "breakpoints=geometry.cpp:16,C:\\src\\util.cpp:4",
            "goal=why", "max_steps=50", "ide=visualstudio"]),
            {"launch_configuration": "geometry (Debug|x64)", "goal": "why", "max_steps": 50, "ide": "visualstudio",
             "breakpoints": [{"file": "geometry.cpp", "line": 16}, {"file": "C:\\src\\util.cpp", "line": 4}]})
        self.assertEqual(parse_tool_arguments("trace", ["file=geometry.cpp", "line=16", "variables=total,i",
                                                        "variables=points", "after=false"]),
                         {"file": "geometry.cpp", "line": 16, "variables": ["total", "i", "points"], "after": False})
        self.assertEqual(parse_tool_arguments("continue", ["until=geometry.cpp:20"]),
                         {"until": {"file": "geometry.cpp", "line": 20}})
        self.assertEqual(parse_tool_arguments("breakpoints", ['add=[{"file": "a.py", "line": 3, "condition": "i > 2"}]']),
                         {"add": [{"file": "a.py", "line": 3, "condition": "i > 2"}]})

    def test_mistakes_are_explained(self):
        for pairs, text in ((["until=geometry.cpp"], "file:line"), (["nonsense"], "key=value"),
                            (["timeout_seconds=soon"], "could not convert")):
            with self.assertRaises(ValueError) as caught:
                parse_tool_arguments("continue", pairs)
            self.assertIn(text, str(caught.exception))

    def test_help_lists_every_tool(self):
        from io import StringIO
        from contextlib import redirect_stdout

        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["run", "help"]), 0)
        for name in ("list_targets", "start_session", "trace", "write_report", "Approve"):
            self.assertIn(name, out.getvalue())


if __name__ == "__main__":
    unittest.main()
