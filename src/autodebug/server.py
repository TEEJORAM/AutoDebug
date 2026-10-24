"""Dependency-free MCP stdio binding, pinned to the 2025-11-25 specification.

Only newline-delimited JSON-RPC is supported. The binding never discovers a
real debugger, issues approvals, evaluates expressions, or opens a socket.

Protocol references:
https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation
https://modelcontextprotocol.io/specification/2025-11-25/server/tools
"""

from __future__ import annotations

import json
import logging
import math
import secrets
import sys
import threading
import time
import types
from collections.abc import Callable
from dataclasses import MISSING, dataclass, field, fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Union, get_args, get_origin, get_type_hints

from autodebug import __version__
from autodebug.adapters.base import BaseAdapter, CapabilityReport
from autodebug.approvals import ApprovalBroker
from autodebug.bridge.approval import issue_bridge_approval
from autodebug.errors import AutoDebugError
from autodebug.facade import (
    MAX_APPROVAL_WAIT, MAX_SELECTION, SCOPE_ARM, SCOPE_CONTINUE, SCOPE_STACK, SCOPE_STEP, SCOPE_VARIABLES, SCOPE_WAIT, STEP_KINDS,
    AutoDebugFacade, target_identity_for,
)
from autodebug.models import (
    ApprovalRecord, Breakpoint, CasePlan, CasePolicy, IntakeSource,
    ReproductionPlan, RootCauseConfidence, SCHEMA_VERSION, TargetRef,
)
from autodebug.sessions import SessionRegistry

PROTOCOL_VERSION = "2025-11-25"
SERVER_VERSION = __version__
MAX_LINE_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_IN_FLIGHT = 8
MAX_REQUESTS = 10_000
DEMO_CASE_ID = "AUTODEBUG-DEMO"
#: Lifetime of the synthetic demo approval and inspection budget. Long enough
#: for an MCP client that starts the server at launch to use the demo later.
DEMO_SECONDS = 1800
_LOG = logging.getLogger(__name__)


class InvalidParams(ValueError):
    """A parameter failed the published JSON schema."""


def _schema(annotation: object) -> dict:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        return {"anyOf": [_schema(item) for item in args]}
    if annotation is type(None):
        return {"type": "null"}
    if annotation in (str, int, float, bool):
        result = {"type": {str: "string", int: "integer", float: "number", bool: "boolean"}[annotation]}
        if annotation is str:
            result["maxLength"] = 8192
        return result
    if origin is tuple:
        if args[-1] is Ellipsis:
            return {"type": "array", "items": _schema(args[0]), "maxItems": 256}
        return {"type": "array", "prefixItems": [_schema(arg) for arg in args],
                "minItems": len(args), "maxItems": len(args), "items": False}
    if origin is dict:
        return {"type": "object", "additionalProperties": _schema(args[1]), "maxProperties": 256}
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {"type": "string", "enum": [item.value for item in annotation]}
    if isinstance(annotation, type) and is_dataclass(annotation):
        hints = get_type_hints(annotation)
        properties = {f.name: _schema(hints[f.name]) for f in fields(annotation)}
        if annotation is ReproductionPlan:
            properties["script_content"] = {"anyOf": [{"type": "string", "maxLength": 65536}, {"type": "null"}]}
        return _object_schema(
            properties,
            [f.name for f in fields(annotation) if f.default is MISSING and f.default_factory is MISSING],
        )
    raise TypeError("Unsupported binding annotation")


def _object_schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _decode(value: object, annotation: object) -> object:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for item in args:
            try:
                return _decode(value, item)
            except InvalidParams:
                pass
        raise InvalidParams("Invalid union value")
    if annotation is type(None) and value is None:
        return None
    if annotation is str and type(value) is str and len(value) <= 8192:
        return value
    if annotation is bool and type(value) is bool:
        return value
    if annotation is int and type(value) is int:
        return value
    if annotation is float and type(value) in (int, float):
        try:
            if math.isfinite(value):
                return float(value)
        except OverflowError:
            pass
    if origin is tuple and type(value) is list and len(value) <= 256:
        if args[-1] is Ellipsis:
            return tuple(_decode(item, args[0]) for item in value)
        if len(value) == len(args):
            return tuple(_decode(item, arg) for item, arg in zip(value, args, strict=True))
        raise InvalidParams("Invalid tuple arity")
    if origin is dict and type(value) is dict and len(value) <= 256:
        return {_decode(k, args[0]): _decode(v, args[1]) for k, v in value.items()}
    if isinstance(annotation, type) and issubclass(annotation, Enum) and type(value) is str:
        try:
            return annotation(value)
        except ValueError:
            pass
    if isinstance(annotation, type) and is_dataclass(annotation) and type(value) is dict:
        known = {f.name: f for f in fields(annotation)}
        if value.keys() - known.keys():
            raise InvalidParams("Unknown dataclass field")
        hints = get_type_hints(annotation)
        kwargs = {}
        for name, f in known.items():
            if name in value:
                if annotation is ReproductionPlan and name == "script_content":
                    content = value[name]
                    if content is not None and (type(content) is not str or len(content.encode("utf-8")) > 65536):
                        raise InvalidParams("Script content exceeds 64 KiB UTF-8")
                    kwargs[name] = content
                else:
                    kwargs[name] = _decode(value[name], hints[name])
            elif f.default is MISSING and f.default_factory is MISSING:
                raise InvalidParams("Missing dataclass field")
        return annotation(**kwargs)
    raise InvalidParams("Invalid parameter type or bound")


@dataclass(frozen=True)
class _Tool:
    parameters: dict[str, object]
    optional: frozenset[str] = frozenset()
    #: Extra JSON-schema bounds per parameter; published and enforced.
    limits: dict[str, dict] = field(default_factory=dict)


def _check_limits(value: object, limits: dict) -> None:
    """Enforce the subset of JSON-schema keywords used in `TOOLS`."""
    checks = {
        "enum": lambda bound: value in bound,
        "minimum": lambda bound: value >= bound,
        "exclusiveMinimum": lambda bound: value > bound,
        "maximum": lambda bound: value <= bound,
        "minItems": lambda bound: len(value) >= bound,
        "maxItems": lambda bound: len(value) <= bound,
        "items": lambda bound: all(
            bound.get("minLength", 0) <= len(item) <= bound.get("maxLength", len(item)) for item in value
        ),
    }
    if not all(check(limits[key]) for key, check in checks.items() if key in limits):
        raise InvalidParams("Value out of bounds")


_CASE = {"case_id": str}
TOOLS = {
    "autodebug_health": _Tool({}),
    "autodebug_probe_adapters": _Tool({}),
    "autodebug_list_sessions": _Tool({}),
    "autodebug_create_case": _Tool({
        "case_id": str, "intake_source": IntakeSource, "intake_description": str, "target": TargetRef,
    }),
    "autodebug_stage_plan": _Tool({**_CASE, "plan": CasePlan}),
    "autodebug_get_plan": _Tool(_CASE),
    "autodebug_arm_case": _Tool({
        **_CASE, "reviewed_configuration": dict[str, str], "process_running": bool,
    }),
    "autodebug_case_status": _Tool(_CASE),
    "autodebug_wait_for_stop": _Tool(
        {**_CASE, "timeout_seconds": float},
        limits={"timeout_seconds": {"exclusiveMinimum": 0, "maximum": 300}},
    ),
    "autodebug_get_stack": _Tool(
        {**_CASE, "frame_limit": int}, limits={"frame_limit": {"minimum": 1, "maximum": MAX_SELECTION}},
    ),
    "autodebug_get_variables": _Tool(
        {**_CASE, "frame_id": str, "selected_names": tuple[str, ...]},
        limits={"selected_names": {
            "minItems": 1, "maxItems": MAX_SELECTION, "items": {"type": "string", "minLength": 1, "maxLength": 500},
        }},
    ),
    "autodebug_step": _Tool({**_CASE, "kind": str}, limits={"kind": {"enum": list(STEP_KINDS)}}),
    "autodebug_continue": _Tool(_CASE),
    "autodebug_complete_case": _Tool({
        **_CASE, "root_cause_statement": str, "confidence": RootCauseConfidence,
        "evidence_ids": tuple[str, ...], "reproduced": bool,
        "uncertainties": tuple[str, ...], "next_steps": tuple[str, ...], "causal_validation": str | None,
    }, frozenset({"uncertainties", "next_steps", "causal_validation"})),
    "autodebug_cancel_case": _Tool(_CASE),
    "autodebug_request_approval": _Tool(_CASE),
    "autodebug_wait_for_approval": _Tool(
        {**_CASE, "timeout_seconds": float},
        limits={"timeout_seconds": {"exclusiveMinimum": 0, "maximum": MAX_APPROVAL_WAIT}},
    ),
}


class ToolDispatcher:
    """Inject a facade and trusted adapter/report; never decode backend objects.

    ``local_approvals`` only contains records supplied by the trusted local host;
    no tool can populate it or receive its tokens. The CLI uses it exclusively
    for the fixed demo. The facade still verifies every supplied record.
    """

    def __init__(
        self, facade: AutoDebugFacade, *, adapter: BaseAdapter,
        capability_report: CapabilityReport, adapter_probes: tuple = (),
        local_approvals: dict[str, ApprovalRecord] | None = None,
        adapter_factory: Callable[[TargetRef], BaseAdapter] | None = None,
        bridge_broker: ApprovalBroker | None = None,
    ) -> None:
        self.facade = facade
        self.adapter = adapter
        self._adapter_factory = adapter_factory
        self._bridge_broker = bridge_broker
        self.capability_report = capability_report
        self.adapter_probes = adapter_probes
        self._local_approvals = dict(local_approvals or {})

    def list_tools(self) -> list[dict]:
        result = []
        for name, tool in TOOLS.items():
            properties = {key: _schema(value) | tool.limits.get(key, {}) for key, value in tool.parameters.items()}
            result.append({
                "name": name,
                "description": name.removeprefix("autodebug_").replace("_", " ") + " (fake-only gateway)",
                "inputSchema": _object_schema(properties, [k for k in tool.parameters if k not in tool.optional]),
            })
        return result

    def decode(self, name: str, arguments: dict) -> dict:
        if name not in TOOLS:
            raise InvalidParams("Unknown tool")
        tool = TOOLS[name]
        if arguments.keys() - tool.parameters.keys():
            raise InvalidParams("Unknown tool argument")
        if tool.parameters.keys() - tool.optional - arguments.keys():
            raise InvalidParams("Missing tool argument")
        decoded = {k: _decode(v, tool.parameters[k]) for k, v in arguments.items()}
        for key, limits in tool.limits.items():
            _check_limits(decoded[key], limits)
        return decoded

    def call(self, name: str, arguments: dict) -> dict:
        kwargs = dict(arguments)
        if name == "autodebug_probe_adapters":
            kwargs["adapters"] = self.adapter_probes
        if name == "autodebug_create_case":
            if self._adapter_factory is not None:
                try:
                    kwargs["adapter"] = self._adapter_factory(kwargs["target"])
                except ValueError as exc:
                    return {"ok": False, "case_id": kwargs["case_id"], "error": {
                        "code": "CAPABILITY_UNSUPPORTED", "message": str(exc), "recoverable": True,
                    }}
            else:
                kwargs["adapter"] = self.adapter
        if name in ("autodebug_arm_case", "autodebug_step", "autodebug_continue"):
            approval = self._local_approvals.get(kwargs["case_id"])
            if approval is None:
                return {"ok": False, "case_id": kwargs["case_id"], "error": {
                    "code": "NOT_APPROVED", "message": "Independent local approval required", "recoverable": True,
                }}
            kwargs["approval"] = approval
        if name == "autodebug_arm_case":
            kwargs["capability_report"] = self.capability_report
        result = getattr(self.facade, name)(**kwargs)
        if name == "autodebug_wait_for_approval" and result.get("ok") and result["result"].get("status") == "approved":
            self._issue_bridge_approval(kwargs["case_id"], result)
        return result

    def _issue_bridge_approval(self, case_id: str, result: dict) -> None:
        """Trusted host step (BR-04): the bridge reported the developer's
        click, so issue the local approval that arm/step/continue need."""
        if self._bridge_broker is None or case_id in self._local_approvals:
            return
        approved = self.facade._approved_bridge_case(case_id)
        if approved is None:
            return
        plan, adapter, target = approved
        try:
            self._local_approvals[case_id] = issue_bridge_approval(
                self._bridge_broker, plan=plan, adapter=adapter, target=target,
                target_identity=target_identity_for(target),
            )
        except AutoDebugError as exc:
            result.update(ok=False, error={"code": exc.detail.code.value, "message": exc.detail.message,
                                           "recoverable": True})
            result.pop("result", None)


@dataclass
class _Pending:
    case_id: str | None
    cancelled: bool = False


def _request_id(value: object) -> bool:
    return (type(value) is str and len(value) <= 256) or (
        type(value) is int and -(2**53 - 1) <= value <= 2**53 - 1
    )


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite JSON number")
    return result


class StdioServer:
    """Bounded workers keep the reader responsive to cancellation and pings."""

    def __init__(
        self, dispatcher: ToolDispatcher, *, input_stream: BinaryIO | None = None,
        output_stream: BinaryIO | None = None, max_line_bytes: int = MAX_LINE_BYTES,
        max_output_bytes: int = MAX_OUTPUT_BYTES, max_in_flight: int = MAX_IN_FLIGHT,
    ) -> None:
        if max_line_bytes < 128 or max_output_bytes < 1024 or max_in_flight < 1:
            raise ValueError("Invalid transport limits")
        self.dispatcher = dispatcher
        self.input = input_stream if input_stream is not None else sys.stdin.buffer
        self.output = output_stream if output_stream is not None else sys.stdout.buffer
        self.max_line_bytes, self.max_output_bytes = max_line_bytes, max_output_bytes
        self.max_in_flight = max_in_flight
        self._initialized = False
        self._ready = False
        self._closed = False
        self._output_lock = threading.Lock()
        self._pending_lock = threading.RLock()
        self._pending: dict[object, _Pending] = {}
        self._seen_ids: set[object] = set()
        self._threads: set[threading.Thread] = set()
        self._case_ids: set[str] = set(dispatcher._local_approvals)

    def _write(self, message: dict) -> None:
        try:
            data = bytearray()
            for chunk in json.JSONEncoder(ensure_ascii=True, allow_nan=False, separators=(",", ":")).iterencode(message):
                data.extend(chunk.encode("utf-8"))
                if len(data) + 1 > self.max_output_bytes:
                    raise ValueError("Output limit")
            data.append(10)
        except (ValueError, TypeError, RecursionError, OverflowError):
            data = bytearray(json.dumps({
                "jsonrpc": "2.0", "id": message.get("id"),
                "error": {"code": -32603, "message": "Result cannot be encoded within output limit"},
            }, separators=(",", ":")).encode("utf-8") + b"\n")
        with self._output_lock:
            if not self._closed:
                try:
                    self.output.write(data)
                    self.output.flush()
                except (BrokenPipeError, OSError):
                    self._closed = True

    def _error(self, request_id: object, code: int, message: str) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def _result(self, request_id: object, result: dict) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _cancel(self, params: dict) -> None:
        if params.keys() - {"requestId", "reason", "_meta"} or not _request_id(params.get("requestId")):
            return
        if "reason" in params and type(params["reason"]) is not str:
            return
        with self._pending_lock:
            pending = self._pending.get(params["requestId"])
            if pending is not None and not pending.cancelled:
                pending.cancelled = True
                if pending.case_id is not None:
                    def cancel() -> None:
                        try:
                            result = self.dispatcher.facade.autodebug_cancel_case(case_id=pending.case_id)
                            if not result["ok"]:
                                _LOG.error("Request cancellation cleanup refused")
                        finally:
                            with self._pending_lock:
                                self._threads.discard(threading.current_thread())
                    thread = threading.Thread(target=cancel, daemon=True)
                    self._threads.add(thread)
                    thread.start()

    def _worker(self, request_id: object, pending: _Pending, name: str, arguments: dict) -> None:
        try:
            if pending.cancelled:
                return
            result = self.dispatcher.call(name, arguments)
            text = json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
            response = {"content": [{"type": "text", "text": text}], "structuredContent": result,
                        "isError": result.get("ok") is not True}
            with self._pending_lock:
                if not pending.cancelled:
                    self._result(request_id, response)
        except Exception:
            _LOG.error("Tool dispatch failed; request refused")
            with self._pending_lock:
                if not pending.cancelled:
                    self._error(request_id, -32603, "Internal tool failure")
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
                self._threads.discard(threading.current_thread())

    def _handle(self, message: object) -> None:
        if type(message) is not dict:
            self._error(None, -32600, "Invalid JSON-RPC request")
            return
        has_id = "id" in message
        request_id = message.get("id")
        valid_id = not has_id or _request_id(request_id)
        if (message.keys() - {"jsonrpc", "id", "method", "params"}
                or message.get("jsonrpc") != "2.0" or type(message.get("method")) is not str
                or not valid_id):
            self._error(request_id if valid_id and has_id else None, -32600, "Invalid JSON-RPC request")
            return
        method, params = message["method"], message.get("params", {})
        if type(params) is not dict or ("_meta" in params and type(params["_meta"]) is not dict):
            if has_id:
                self._error(request_id, -32602, "Parameters must be an object")
            return
        if not has_id:
            if method == "notifications/initialized" and not params.keys() - {"_meta"} and self._initialized:
                self._ready = True
            elif method == "notifications/cancelled":
                self._cancel(params)
            return
        with self._pending_lock:
            if request_id in self._seen_ids:
                self._error(request_id, -32600, "Request id already used in this session")
                return
            if len(self._seen_ids) >= MAX_REQUESTS:
                self._error(request_id, -32001, "Request budget exhausted; reconnect")
                self._closed = True
                return
            self._seen_ids.add(request_id)
        if method == "initialize":
            if self._initialized:
                self._error(request_id, -32600, "Already initialized")
            elif (params.keys() - {"protocolVersion", "capabilities", "clientInfo", "_meta"}
                  or type(params.get("protocolVersion")) is not str
                  or type(params.get("capabilities")) is not dict
                  or type(params.get("clientInfo")) is not dict
                  or type(params["clientInfo"].get("name")) is not str
                  or type(params["clientInfo"].get("version")) is not str):
                self._error(request_id, -32602, "Invalid initialization parameters")
            else:
                self._initialized = True
                self._result(request_id, {
                    "protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "autodebug", "version": SERVER_VERSION},
                    "instructions": "Fake-only gateway. No tool issues approval or controls a real debugger.",
                })
        elif method == "ping":
            if params.keys() - {"_meta"}:
                self._error(request_id, -32602, "Ping takes no arguments")
            else:
                self._result(request_id, {})
        elif not self._ready:
            self._error(request_id, -32000, "Initialization handshake required")
        elif method == "tools/list":
            if params.keys() - {"_meta"}:
                self._error(request_id, -32602, "Pagination is not supported; omit cursor")
            else:
                self._result(request_id, {"tools": self.dispatcher.list_tools()})
        elif method == "tools/call":
            try:
                if params.keys() - {"name", "arguments", "_meta"} or type(params.get("name")) is not str:
                    raise InvalidParams("Invalid tools/call parameters")
                arguments = params.get("arguments", {})
                if type(arguments) is not dict:
                    raise InvalidParams("Tool arguments must be an object")
                name = params["name"]
                decoded = self.dispatcher.decode(name, arguments)
            except (InvalidParams, RecursionError):
                self._error(request_id, -32602, "Invalid tool name, arguments, types or bounds")
                return
            pending = _Pending(decoded.get("case_id"))
            with self._pending_lock:
                if len(self._pending) >= self.max_in_flight + int(name == "autodebug_cancel_case"):
                    self._error(request_id, -32001, "Too many in-flight requests")
                    return
                if pending.case_id is not None:
                    self._case_ids.add(pending.case_id)
                self._pending[request_id] = pending
                thread = threading.Thread(target=self._worker, args=(request_id, pending, name, decoded), daemon=True)
                self._threads.add(thread)
                thread.start()
        else:
            self._error(request_id, -32601, "Method not found")

    def serve(self) -> None:
        try:
            while not self._closed:
                line = self.input.readline(self.max_line_bytes + 1)
                if not line:
                    break
                if len(line) > self.max_line_bytes:
                    while line and not line.endswith(b"\n"):
                        line = self.input.readline(self.max_line_bytes + 1)
                    self._error(None, -32600, "Input line exceeds size limit")
                    continue
                if not line.endswith(b"\n"):
                    self._error(None, -32700, "Unterminated JSON-RPC message")
                    break
                try:
                    message = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object,
                                         parse_constant=_invalid_constant, parse_float=_finite_float)
                except (UnicodeDecodeError, ValueError, RecursionError):
                    self._error(None, -32700, "Invalid UTF-8 JSON")
                    continue
                self._handle(message)
        finally:
            with self._output_lock:
                self._closed = True
            for case_id in tuple(self._case_ids):
                try:
                    self.dispatcher.facade.autodebug_cancel_case(case_id=case_id)
                except Exception:
                    _LOG.error("Transport shutdown cleanup failed")
            deadline = time.monotonic() + 2
            with self._pending_lock:
                threads = tuple(self._threads)
            for thread in threads:
                thread.join(max(0, deadline - time.monotonic()))


def build_dispatcher(evidence_dir: Path, *, demo: bool, bridges_folder: Path | None = None) -> ToolDispatcher:
    """Wire adapter, broker, registry and facade for the CLI.

    With `demo`, seed and arm the fixed synthetic case locally. Otherwise,
    with `bridges_folder`, each new case gets its own AutoDebug Bridge adapter
    for the IDE it targets (ide-debug-bridge)."""
    from autodebug.synthetic import SyntheticAdapter

    broker = ApprovalBroker(now=time.monotonic, make_token=lambda: secrets.token_urlsafe(32))
    registry = SessionRegistry()
    if not demo and bridges_folder is not None:
        from autodebug.adapters.vscode_bridge import VSCodeBridgeAdapter

        def bridge_adapter(target: TargetRef) -> BaseAdapter:
            return VSCodeBridgeAdapter(target.ide, bridges_folder)

        facade = AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=evidence_dir,
                                 backend_mode="vscode-bridge")
        adapter = VSCodeBridgeAdapter("vscode", bridges_folder)
        return ToolDispatcher(facade, adapter=adapter, capability_report=adapter.probe_capabilities(),
                              adapter_probes=((adapter, None, None),), adapter_factory=bridge_adapter,
                              bridge_broker=broker)
    facade = AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=evidence_dir)
    adapter = SyntheticAdapter()
    report = adapter.probe_capabilities()
    approvals = {}
    if demo:
        target = adapter.target
        plan = CasePlan(
            schema_version=SCHEMA_VERSION, case_id=DEMO_CASE_ID, source_revision="synthetic-demo-v1",
            target=target, breakpoints=(Breakpoint(file="/synthetic/demo.py", line=7),),
            reproduction=ReproductionPlan(mode="manual", steps=("Observe the predetermined synthetic stop.",)),
            policy=CasePolicy(max_steps=5, max_inspection_seconds=DEMO_SECONDS),
        )
        created = facade.autodebug_create_case(
            case_id=DEMO_CASE_ID, intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="Isolated synthetic demonstration; no application or native debugger.", adapter=adapter,
            target=target,
        )
        staged = facade.autodebug_stage_plan(case_id=DEMO_CASE_ID, plan=plan)
        if not created["ok"] or not staged["ok"]:
            raise ValueError("Cannot seed synthetic demonstration")
        plan = replace(plan, digest_sha256=staged["result"]["digest_sha256"])
        approvals[DEMO_CASE_ID] = broker.issue_approval(
            plan, reviewer="local-cli-synthetic-demo", backend_kind="fake",
            target_identity=target_identity_for(target),
            scope=(SCOPE_ARM, SCOPE_STEP, SCOPE_CONTINUE, SCOPE_WAIT, SCOPE_STACK, SCOPE_VARIABLES),
            ttl_seconds=DEMO_SECONDS, human_presence_confirmed=True,
        )
        armed = facade.autodebug_arm_case(
            case_id=DEMO_CASE_ID, approval=approvals[DEMO_CASE_ID],
            capability_report=report, reviewed_configuration={}, process_running=False,
        )
        if not armed["ok"]:
            raise ValueError("Cannot arm the predetermined synthetic demonstration")
        stopped = facade.autodebug_wait_for_stop(case_id=DEMO_CASE_ID, timeout_seconds=1)
        if not stopped["ok"]:
            raise ValueError("Cannot confirm the predetermined synthetic stop")
    return ToolDispatcher(facade, adapter=adapter, capability_report=report,
                          adapter_probes=((adapter, None, None),), local_approvals=approvals)


def main(argv: list[str] | None = None) -> int:
    """Backward-compatible entry point; see `autodebug.cli`."""
    from autodebug.cli import main as cli_main

    return cli_main(argv)
