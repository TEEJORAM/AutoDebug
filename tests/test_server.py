"""Offline stdio, protocol, synthetic workflow and distribution acceptance tests."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import unittest
import tempfile
import zipfile
from dataclasses import asdict, replace
from pathlib import Path

from autodebug.adapters.base import BaseAdapter, CapabilityReport
from autodebug.models import CapabilityState, CasePlan, IntakeSource, TargetRef
from autodebug.server import (
    DEMO_CASE_ID, MAX_LINE_BYTES, PROTOCOL_VERSION, InvalidParams,
    StdioServer, ToolDispatcher,
)

ROOT = Path(__file__).resolve().parents[1]


class _FakeFacade:
    def __init__(self):
        self.cancelled = threading.Event()
        self.waiting = threading.Event()
        self.seen = None

    def autodebug_health(self):
        return {"ok": True, "case_id": None, "result": {"backend_mode": "fake-only"}}

    def autodebug_create_case(self, **kwargs):
        self.seen = kwargs
        return {"ok": True, "case_id": kwargs["case_id"], "result": {}}

    def autodebug_wait_for_stop(self, **kwargs):
        self.waiting.set()
        self.cancelled.wait(2)
        return {"ok": False, "case_id": kwargs["case_id"], "error": {"code": "CANCELLED"}}

    def autodebug_cancel_case(self, **kwargs):
        self.cancelled.set()
        return {"ok": True, "case_id": kwargs["case_id"], "result": {"state": "cancelled"}}


def _dispatcher(facade=None):
    return ToolDispatcher(
        facade or _FakeFacade(), adapter=BaseAdapter(), capability_report=CapabilityReport(
            ide="fake", host_os="synthetic", state=CapabilityState.AVAILABLE,
            ide_version="synthetic", backend_version="synthetic", reason="synthetic test only",
        ),
    )


def _request(request_id, method, params=None):
    result = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        result["params"] = params
    return result


INITIALIZE = {
    "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
    "clientInfo": {"name": "offline-tests", "version": "1"},
}


class TestBinding(unittest.TestCase):
    def test_exact_tool_surface_schemas_and_no_approval_channel(self):
        tools = _dispatcher().list_tools()
        self.assertEqual(len(tools), 15)
        self.assertEqual(len({t["name"] for t in tools}), 15)
        for tool in tools:
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")
            self.assertIs(schema["additionalProperties"], False)
            self.assertFalse({"adapter", "backend", "approval", "capability_report"} & schema["properties"].keys())
        self.assertFalse(any("approve" in t["name"] or "eval" in t["name"] or "shell" in t["name"] for t in tools))

    def test_strict_dataclass_enum_tuple_decode(self):
        dispatcher = _dispatcher()
        decoded = dispatcher.decode("autodebug_create_case", {
            "case_id": "TEST", "intake_source": "developer_text", "intake_description": "synthetic",
            "target": {"host_id": "synthetic", "ide": "fake", "debug_session_id": None, "pid": None},
        })
        self.assertIs(decoded["intake_source"], IntakeSource.DEVELOPER_TEXT)
        self.assertIsInstance(decoded["target"], TargetRef)
        dispatcher.call("autodebug_create_case", decoded)
        self.assertIsInstance(dispatcher.facade.seen["adapter"], BaseAdapter)
        plan = {
            "schema_version": "0.1-draft", "case_id": "TEST", "source_revision": "synthetic",
            "target": asdict(decoded["target"]), "breakpoints": [{"file": "/synthetic/demo.py", "line": 7}],
            "reproduction": {"mode": "manual", "steps": ["observe synthetic stop"]},
            "policy": {"max_steps": 5, "max_inspection_seconds": 60},
        }
        staged = dispatcher.decode("autodebug_stage_plan", {"case_id": "TEST", "plan": plan})
        self.assertIsInstance(staged["plan"], CasePlan)
        self.assertEqual(staged["plan"].breakpoints[0].line, 7)
        self.assertEqual(staged["plan"].reproduction.steps, ("observe synthetic stop",))

    def test_invalid_arguments_are_rejected_not_coerced(self):
        dispatcher = _dispatcher()
        cases = [
            ("autodebug_health", {"extra": 1}),
            ("autodebug_get_stack", {"case_id": "TEST", "frame_limit": True}),
            ("autodebug_get_stack", {"case_id": "TEST", "frame_limit": 1.0}),
            ("autodebug_get_stack", {"case_id": "TEST", "frame_limit": 51}),
            ("autodebug_wait_for_stop", {"case_id": "TEST", "timeout_seconds": 0}),
            ("autodebug_wait_for_stop", {"case_id": "TEST", "timeout_seconds": 301}),
            ("autodebug_wait_for_stop", {"case_id": "TEST", "timeout_seconds": float("inf")}),
            ("autodebug_wait_for_stop", {"case_id": "TEST", "timeout_seconds": "5"}),
            ("autodebug_get_variables", {"case_id": "TEST", "frame_id": "f", "selected_names": []}),
            ("autodebug_get_variables", {"case_id": "TEST", "frame_id": "f", "selected_names": ["x" * 501]}),
            ("autodebug_step", {"case_id": "TEST", "kind": "over", "approval": {}}),
            ("autodebug_step", {"case_id": "TEST", "kind": "arbitrary"}),
            ("autodebug_create_case", {
                "case_id": "TEST", "intake_source": "unknown", "intake_description": "synthetic", "target": {},
            }),
            ("autodebug_stage_plan", {"case_id": "TEST", "plan": {"unexpected": True}}),
            ("autodebug_get_plan", {"case_id": "x" * 8193}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments), self.assertRaises(InvalidParams):
                dispatcher.decode(name, arguments)

    def test_unapproved_host_never_issues_approval(self):
        result = _dispatcher().call("autodebug_continue", {"case_id": DEMO_CASE_ID})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "NOT_APPROVED")
        self.assertNotIn("token", json.dumps(result))

    def test_complete_64k_script_can_cross_binding_without_short_string_truncation(self):
        from tests.test_plans import make_plan
        content = "# synthetic only\n" + "x = 1\n" * 2000
        plan = json.loads(json.dumps(asdict(make_plan())))
        plan["reproduction"].update(
            mode="api_script", script_content=content,
            script_sha256=hashlib.sha256(content.encode()).hexdigest(),
            risks=["Synthetic assignments only"], sample_document="No document required",
        )
        decoded = _dispatcher().decode("autodebug_stage_plan", {"case_id": plan["case_id"], "plan": plan})
        self.assertEqual(decoded["plan"].reproduction.script_content, content)
        from autodebug.plans import validate_case_plan
        validate_case_plan(decoded["plan"])
        plan["reproduction"]["script_content"] = "x" * 65537
        with self.assertRaises(InvalidParams):
            _dispatcher().decode("autodebug_stage_plan", {"case_id": plan["case_id"], "plan": plan})

    def test_launch_configuration_has_exact_pair_schema_and_decoder(self):
        from tests.test_plans import make_plan
        plan = asdict(replace(make_plan(), launch_configuration=(("profile", "synthetic"),)))
        plan = json.loads(json.dumps(plan))
        dispatcher = _dispatcher()
        decoded = dispatcher.decode("autodebug_stage_plan", {"case_id": plan["case_id"], "plan": plan})
        self.assertEqual(decoded["plan"].launch_configuration, (("profile", "synthetic"),))
        schema = next(t["inputSchema"] for t in dispatcher.list_tools() if t["name"] == "autodebug_stage_plan")
        self.assertEqual(schema["properties"]["plan"]["properties"]["launch_configuration"]["items"]["maxItems"], 2)
        plan["launch_configuration"] = [["profile", "synthetic", "unreviewed"]]
        with self.assertRaises(InvalidParams):
            dispatcher.decode("autodebug_stage_plan", {"case_id": plan["case_id"], "plan": plan})

    def test_parser_bounds_types_duplicates_nonfinite_unicode_and_recovery(self):
        output = io.BytesIO()
        messages = [
            b"{not-json}\n",
            b"\xff\n",
            b'{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":1e999,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":true,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":null,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":1.5,"method":"ping"}\n',
            b"[]\n",
            b'{"jsonrpc":"2.0","id":8,"method":"ping","params":[]}\n',
            b'{"jsonrpc":"2.0","id":9,"method":"ping","unexpected":1}\n',
            b'{"jsonrpc":"2.0","id":10,"method":"ping","params":{"_meta":1}}\n',
            b'{"jsonrpc":"2.0","id":11,"method":"ping"}' + b" " * 256 + b"\n",
            b'{"jsonrpc":"2.0","id":12,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":12,"method":"ping"}\n',
        ]
        StdioServer(_dispatcher(), input_stream=io.BytesIO(b"".join(messages)),
                    output_stream=output, max_line_bytes=256).serve()
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), len(messages))
        self.assertTrue(all("error" in r for r in responses[:-2]))
        self.assertEqual(responses[-2], {"jsonrpc": "2.0", "id": 12, "result": {}})
        self.assertEqual(responses[-1]["error"]["code"], -32600)

    def test_notifications_have_no_responses(self):
        output = io.BytesIO()
        messages = [
            {"jsonrpc": "2.0", "method": "unknown"},
            {"jsonrpc": "2.0", "method": "ping", "params": []},
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": None}},
        ]
        StdioServer(_dispatcher(), input_stream=io.BytesIO(
            b"".join(json.dumps(m).encode() + b"\n" for m in messages)), output_stream=output).serve()
        self.assertEqual(output.getvalue(), b"")

    def test_output_limit_and_encoding_failure_are_valid_bounded_errors(self):
        output = io.BytesIO()
        server = StdioServer(_dispatcher(), input_stream=io.BytesIO(), output_stream=output, max_output_bytes=1024)
        for result in ({"huge": "x" * 2048}, {"not_json": object()}, {"not_finite": float("nan")}):
            server._result(1, result)
        lines = output.getvalue().splitlines(keepends=True)
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertLessEqual(len(line), 1024)
            self.assertEqual(json.loads(line)["error"]["code"], -32603)

    def test_unterminated_line_is_parse_error(self):
        output = io.BytesIO()
        StdioServer(_dispatcher(), input_stream=io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}'),
                    output_stream=output).serve()
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32700)


class _Process:
    def __init__(self, evidence_dir, *, demo=False, script=None):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-u", "-m", "autodebug", "--evidence-dir", str(evidence_dir)]
        if demo:
            command.append("--demo")
        if script is not None:
            command = [sys.executable, "-u", "-c", script]
        self.process = subprocess.Popen(command, cwd=ROOT, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.responses = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.counter = 0

    def _read(self):
        for line in self.process.stdout:
            self.responses.put(line)
        self.responses.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message, allow_nan=False).encode() + b"\n")
        self.process.stdin.flush()

    def receive(self, timeout=5):
        line = self.responses.get(timeout=timeout)
        if line is None:
            raise AssertionError("Server exited unexpectedly: " + self.process.stderr.read().decode())
        return json.loads(line)

    def request(self, method, params=None):
        self.counter += 1
        self.send(_request(self.counter, method, params))
        result = self.receive()
        if result.get("id") != self.counter:
            raise AssertionError(f"Unexpected response {result!r}")
        return result

    def initialize(self, version=PROTOCOL_VERSION):
        result = self.request("initialize", {**INITIALIZE, "protocolVersion": version})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def tool(self, name, arguments=None):
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()


class _WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self._workspace = tempfile.TemporaryDirectory(prefix="autodebug-server-")
        self.workspace = Path(self._workspace.name)
        self.addCleanup(self._workspace.cleanup)

    def start(self, **kwargs):
        process = _Process(self.workspace / "evidence", **kwargs)
        self.addCleanup(process.close)
        return process


class TestSubprocess(_WorkspaceTest):
    def test_help_version_and_required_local_evidence_directory(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        for option, expected in (("--help", "Fake-only"), ("--version", "0.1.0")):
            result = subprocess.run([sys.executable, "-m", "autodebug", option], cwd=ROOT, env=env,
                                    capture_output=True, timeout=5, check=True)
            self.assertIn(expected, result.stdout.decode())
        result = subprocess.run([sys.executable, "-m", "autodebug"], cwd=ROOT, env=env,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"serve", result.stderr)

    def test_handshake_negotiates_pinned_version_and_fake_only_lifecycle(self):
        process = self.start()
        self.assertEqual(process.request("tools/list")["error"]["code"], -32000)
        self.assertEqual(process.request("ping")["result"], {})
        result = process.initialize("2099-01-01")["result"]
        self.assertEqual(result["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(len(process.request("tools/list")["result"]["tools"]), 15)
        self.assertEqual(process.request("initialize", INITIALIZE)["error"]["code"], -32600)
        self.assertEqual(process.request("unknown")["error"]["code"], -32601)
        health = process.tool("autodebug_health")["result"]
        self.assertFalse(health["isError"])
        self.assertEqual(health["structuredContent"]["result"]["backend_mode"], "fake-only")
        self.assertEqual(json.loads(health["content"][0]["text"]), health["structuredContent"])
        self.assertEqual(process.tool("approve", {})["error"]["code"], -32602)
        self.assertEqual(process.tool("autodebug_get_stack", {
            "case_id": "TEST", "frame_limit": True,
        })["error"]["code"], -32602)
        refused = process.tool("autodebug_continue", {"case_id": DEMO_CASE_ID})["result"]
        self.assertTrue(refused["isError"])
        self.assertNotIn("token", json.dumps(refused))
        process.process.stdin.close()
        self.assertEqual(process.process.wait(timeout=5), 0)
        stderr = process.process.stderr.read().decode().splitlines()
        # Only the startup banner and evidence location; no tokens or errors.
        self.assertEqual(len(stderr), 2, stderr)
        self.assertTrue(stderr[0].startswith("autodebug 0.1.0 | MCP stdio"))
        self.assertTrue(stderr[1].startswith("autodebug: evidence: "))
        self.assertNotIn("token", "\n".join(stderr))

    def test_large_invalid_line_recovers_then_ping(self):
        process = self.start()
        process.process.stdin.write(b"x" * (MAX_LINE_BYTES + 1) + b"\n")
        process.process.stdin.flush()
        self.assertEqual(process.receive()["error"]["code"], -32600)
        self.assertEqual(process.request("ping")["result"], {})

    def test_demo_end_to_end_synthetic_evidence_no_token_and_no_arbitrary_approval(self):
        process = self.start(demo=True)
        process.initialize()
        plan = process.tool("autodebug_get_plan", {"case_id": DEMO_CASE_ID})["result"]["structuredContent"]
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["result"]["plan"]["source_revision"], "synthetic-demo-v1")
        armed = process.tool("autodebug_case_status", {"case_id": DEMO_CASE_ID})["result"]["structuredContent"]
        self.assertTrue(armed["ok"], armed)
        waited = process.tool("autodebug_wait_for_stop", {
            "case_id": DEMO_CASE_ID, "timeout_seconds": 1,
        })["result"]["structuredContent"]
        self.assertTrue(waited["ok"], waited)
        stack = process.tool("autodebug_get_stack", {"case_id": DEMO_CASE_ID, "frame_limit": 2})["result"]
        self.assertFalse(stack["isError"], stack)
        frame_id = stack["structuredContent"]["result"]["frames"][0]["frame"]
        stepped = process.tool("autodebug_step", {"case_id": DEMO_CASE_ID, "kind": "step_over"})["result"]
        self.assertFalse(stepped["isError"], stepped)
        waited_after_step = process.tool("autodebug_wait_for_stop", {
            "case_id": DEMO_CASE_ID, "timeout_seconds": 1,
        })["result"]
        self.assertFalse(waited_after_step["isError"], waited_after_step)
        variables = process.tool("autodebug_get_variables", {
            "case_id": DEMO_CASE_ID, "frame_id": frame_id, "selected_names": ["local_var", "password"],
        })["result"]["structuredContent"]
        self.assertTrue(variables["ok"], variables)
        (run_dir,) = (self.workspace / "evidence").glob("run-*")
        events_path = run_dir / DEMO_CASE_ID / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        self.assertTrue(events)
        completed = process.tool("autodebug_complete_case", {
            "case_id": DEMO_CASE_ID, "root_cause_statement": "Synthetic observation only, not a native debugger.",
            "confidence": "inconclusive", "evidence_ids": [event["evidence_id"] for event in events],
            "reproduced": True, "uncertainties": ["No native integration tested"],
        })["result"]["structuredContent"]
        self.assertTrue(completed["ok"], completed)
        self.assertEqual(completed["result"]["state"], "finalized")
        for relative in completed["result"]["artifacts"].values():
            self.assertTrue((run_dir / relative).is_file())
        raw = json.dumps([plan, armed, waited, stack, variables, completed])
        self.assertNotIn('"token"', raw)
        self.assertNotIn("synthetic-private-value", raw)
        refused = process.tool("autodebug_continue", {"case_id": "ARBITRARY"})["result"]
        self.assertTrue(refused["isError"])
        self.assertEqual(refused["structuredContent"]["error"]["code"], "NOT_APPROVED")

    def test_real_synthetic_facade_cancel_interrupts_pending_wait(self):
        process = self.start(demo=True)
        process.initialize()
        resumed = process.tool("autodebug_continue", {"case_id": DEMO_CASE_ID})["result"]
        self.assertFalse(resumed["isError"], resumed)
        process.send(_request(100, "tools/call", {
            "name": "autodebug_wait_for_stop", "arguments": {"case_id": DEMO_CASE_ID, "timeout_seconds": 30},
        }))
        self.assertEqual(process.request("ping")["result"], {})
        start = time.monotonic()
        process.send(_request(101, "tools/call", {
            "name": "autodebug_cancel_case", "arguments": {"case_id": DEMO_CASE_ID},
        }))
        responses = [process.receive(), process.receive()]
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual({r["id"] for r in responses}, {100, 101})
        waiting = next(r for r in responses if r["id"] == 100)["result"]["structuredContent"]
        self.assertFalse(waiting["ok"])
        self.assertEqual(waiting["error"]["code"], "CANCELLED")
        status = process.tool("autodebug_case_status", {"case_id": DEMO_CASE_ID})["result"]["structuredContent"]
        self.assertEqual(status["result"]["state"], "cancelled")
        (run_dir,) = (self.workspace / "evidence").glob("run-*")
        self.assertTrue((run_dir / DEMO_CASE_ID / "case.json").is_file())

    def test_cancel_case_interrupts_wait_without_blocking_ping(self):
        # An injected in-memory host exercises transport concurrency independently
        # of the CLI's predetermined synthetic pause.
        script = """
from tests.test_server import _dispatcher
from autodebug.server import StdioServer
StdioServer(_dispatcher(), max_in_flight=1).serve()
"""
        process = self.start(script=script)
        process.initialize()
        process.send(_request(100, "tools/call", {"name": "autodebug_wait_for_stop",
                                                "arguments": {"case_id": "TEST", "timeout_seconds": 30}}))
        self.assertEqual(process.request("ping")["result"], {})
        busy = process.tool("autodebug_health")
        self.assertEqual(busy["error"]["code"], -32001)
        start = time.monotonic()
        process.send(_request(101, "tools/call", {"name": "autodebug_cancel_case", "arguments": {"case_id": "TEST"}}))
        responses = [process.receive(), process.receive()]
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual({r["id"] for r in responses}, {100, 101})
        self.assertTrue(next(r for r in responses if r["id"] == 100)["result"]["isError"])

    def test_cancellation_notification_suppresses_response_and_retains_lifecycle(self):
        script = """
from tests.test_server import _dispatcher
from autodebug.server import StdioServer
StdioServer(_dispatcher()).serve()
"""
        process = self.start(script=script)
        process.initialize()
        process.send(_request(100, "tools/call", {"name": "autodebug_wait_for_stop",
                                                "arguments": {"case_id": "TEST", "timeout_seconds": 30}}))
        self.assertEqual(process.request("ping")["result"], {})
        process.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 100}})
        process.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "unknown"}})
        self.assertEqual(process.request("ping")["result"], {})
        with self.assertRaises(queue.Empty):
            process.responses.get(timeout=0.1)


@unittest.skipIf(sys.version_info < (3, 11), "build_backend uses tomllib; AutoDebug requires Python 3.11+")
class TestOfflinePackaging(_WorkspaceTest):
    def test_stdlib_wheel_records_metadata_entrypoint_and_isolated_import(self):
        import build_backend

        self.assertEqual(build_backend.get_requires_for_build_wheel(), [])
        wheel_path = self.workspace / build_backend.build_wheel(str(self.workspace))
        extracted = self.workspace / "unpacked"
        extracted.mkdir()
        with zipfile.ZipFile(wheel_path) as wheel:
            self.assertIn("autodebug/server.py", wheel.namelist())
            self.assertIn("autodebug/__main__.py", wheel.namelist())
            self.assertFalse(any(name.startswith("tests/") or "__pycache__" in name for name in wheel.namelist()))
            dist_info = "autodebug-0.1.0.dist-info"
            self.assertIn(b"autodebug = autodebug.cli:main", wheel.read(f"{dist_info}/entry_points.txt"))
            self.assertIn(b"Requires-Python: >=3.11", wheel.read(f"{dist_info}/METADATA"))
            self.assertNotIn(b"Requires-Dist:", wheel.read(f"{dist_info}/METADATA"))
            records = csv.reader(io.StringIO(wheel.read(f"{dist_info}/RECORD").decode()))
            for name, digest, size in records:
                if digest:
                    data = wheel.read(name)
                    actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                    self.assertEqual(digest, "sha256=" + actual)
                    self.assertEqual(int(size), len(data))
            wheel.extractall(extracted)
        script = f"""
import sys
sys.path.insert(0, {str(extracted)!r})
import autodebug.server
assert autodebug.server.PROTOCOL_VERSION == {PROTOCOL_VERSION!r}
assert autodebug.server.main(["--version"]) == 0
"""
        result = subprocess.run([sys.executable, "-I", "-c", script], cwd=self.workspace,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b"autodebug 0.1.0", result.stdout)

    def test_sdist_can_rebuild_wheel_offline(self):
        import build_backend
        import tarfile

        archive_path = self.workspace / build_backend.build_sdist(str(self.workspace))
        extracted = self.workspace / "sdist"
        extracted.mkdir()
        with tarfile.open(archive_path) as archive:
            self.assertTrue(all(not name.startswith("/") and ".." not in Path(name).parts for name in archive.getnames()))
            self.assertIn("autodebug-0.1.0/PKG-INFO", archive.getnames())
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                destination = extracted / member.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source_file, destination.open("wb") as output:
                    shutil.copyfileobj(source_file, output)
        source = extracted / "autodebug-0.1.0"
        result = subprocess.run([sys.executable, "-I", "-c", (
            "import sys;sys.path.insert(0,'.');import build_backend;"
            "print(build_backend.build_wheel('dist'))"
        )], cwd=source, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue((source / "dist" / "autodebug-0.1.0-py3-none-any.whl").is_file())


if __name__ == "__main__":
    unittest.main()
