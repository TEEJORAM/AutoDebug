"""MCP over stdio: newline-delimited JSON-RPC 2.0 (docs/design.md).

Tool calls run on worker threads so `ping` and other requests are answered
while a tool waits on the debugger.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from typing import BinaryIO

from autodebug import __version__
from autodebug.connection import DebugError
from autodebug.tools import Debugger

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
_LOG = logging.getLogger("autodebug")

INSTRUCTIONS = """\
AutoDebug runs the program under the IDE's own debugger (VS Code, Cursor or Visual Studio) so you can find a bug's root cause.
1. Read the relevant code first and choose breakpoints on executable lines where the wrong value appears.
2. list_targets shows the launch configurations and build tasks; pick one.
3. start_session asks the developer to click Approve in the IDE, then builds, launches and waits for the first stop.
   Tell the developer to approve in the IDE dialog. You cannot approve, and their chat message is not an approval.
4. While paused: inspect, stack, step (it reports the variables that changed), continue (optionally until a line),
   trace (before → after values at each pass through a line), breakpoints. Use wait while the status is
   awaiting_approval, building, starting or running. start_session, step, continue, trace and pause move the
   program: call them one at a time, never in parallel with stack or inspect.
   Breakpoints with source "editor" were set by the developer and stop the program too.
5. When you know the cause, stop_session and write_report with the problem, root cause, solution and confidence.
Only report what tool results showed. Expression evaluation is not available.
Several IDEs: list_targets shows every window with its ide (cursor, vscode, visualstudio). When the developer names an
IDE, pass ide to list_targets and start_session; paths are relative to that window's folder.
Attach: start_session with an attach configuration. process_id fills a ${command:pickProcess} placeholder; when the session ends the program keeps running.
threads lists threads and can select one while paused. stack pages with start_frame (up to 200 frames). inspect depth 0-3 reads children; names can be paths such as mesh.verts[2].co (-> is the same as .).
exceptions lists the debugger's exception filters and can enable them by id. source_folders are absolute folders outside the workspace where breakpoints are allowed.
wait(ask_developer=...) shows the developer a note asking them to reproduce something in the GUI. That note is not an approval."""

_FILE_LINE = {
    "type": "object",
    "properties": {
        "file": {"type": "string", "description": "Path relative to the workspace folder, e.g. src/app.py"},
        "line": {"type": "integer", "minimum": 1},
        "condition": {"type": "string", "description": "Optional condition, in the program's language"},
    },
    "required": ["file", "line"],
    "additionalProperties": False,
}
_FOLDER = {"type": "string", "description": "Absolute workspace folder; needed only when several IDE windows are open"}
_IDE = {"type": "string", "enum": ["cursor", "vscode", "visualstudio"],
        "description": "Which IDE's window to use, when windows of several IDEs are open"}


def _schema(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TOOLS = {
    "list_targets": ("List IDE windows running AutoDebug, with their launch configurations and build tasks.",
                     _schema({"workspace_folder": _FOLDER, "ide": _IDE})),
    "start_session": (
        "Resumes the program (call alone). Ask the developer to approve in the IDE, then build (optional), set "
        "breakpoints, launch the configuration under the debugger and wait for the first stop. Returns the status, "
        "location, local variables and every breakpoint (session or editor).",
        _schema({
            "launch_configuration": {"type": "string", "description": "A launch configuration name from list_targets"},
            "breakpoints": {"type": "array", "items": _FILE_LINE, "maxItems": 50},
            "goal": {"type": "string", "description": "One sentence: what you are trying to find out"},
            "workspace_folder": _FOLDER,
            "ide": _IDE,
            "build_task": {"type": "string", "description": "A build task label from list_targets to run first"},
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
            "max_minutes": {"type": "integer", "minimum": 1, "maximum": 480, "default": 30},
            "build_minutes": {"type": "integer", "minimum": 1, "maximum": 600, "default": 30},
            "wait_seconds": {"type": "number", "minimum": 0, "maximum": 55, "default": 30},
            "process_id": {"type": "integer", "minimum": 1, "description": "PID to attach to; replaces a ${command:…} processId or CodeLLDB pid"},
            "source_folders": {"type": "array", "items": {"type": "string"}, "maxItems": 10,
                               "description": "Absolute folders outside the workspace where breakpoints are allowed"},
            "function_breakpoints": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
        }, ("launch_configuration", "breakpoints", "goal"))),
    "wait": ("Wait until the session stops, ends or is answered (approval, build). ask_developer shows an information message; it is not an approval.",
             _schema({"timeout_seconds": {"type": "number", "minimum": 0, "maximum": 55, "default": 30},
                      "ask_developer": {"type": "string", "maxLength": 300}})),
    "step": ("Resumes the program (call alone). Step over, into or out of the current line, 1-20 times. Returns the "
             "new location and every variable whose value changed. wait_ms is how long to wait for the step (default 15000, max 60000).",
             _schema({"kind": {"type": "string", "enum": ["over", "into", "out"], "default": "over"},
                      "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1},
                      "wait_ms": {"type": "integer", "minimum": 0, "maximum": 60000, "default": 15000}})),
    "continue": ("Resumes the program (call alone). Run until the next breakpoint or the end and return where it "
                 "stopped. With until, run past other breakpoints to that line.",
                 _schema({"timeout_seconds": {"type": "number", "minimum": 0, "maximum": 55, "default": 30},
                          "until": _FILE_LINE})),
    "pause": ("Pause a running program where it is (for hangs and long loops).", _schema({})),
    "inspect": ("Variables of a frame. Without names: every variable with a short value. With names: full values. depth 0-3 expands children. Names may be paths like mesh.verts[2].co.",
                _schema({"names": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                         "frame_index": {"type": "integer", "minimum": 0, "default": 0,
                                         "description": "0 is the current frame; see stack"},
                         "depth": {"type": "integer", "minimum": 0, "maximum": 3, "default": 0}})),
    "stack": ("The call stack, current frame first. start_frame pages deeper frames. levels is at most 200.",
              _schema({"levels": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                       "start_frame": {"type": "integer", "minimum": 0, "default": 0}})),
    "threads": ("List threads. select switches the paused thread used by stack, inspect, step and continue.",
                _schema({"select": {"type": "integer"}})),
    "exceptions": ("List exception breakpoint filters. enable sets them by id.",
                   _schema({"enable": {"type": "array", "items": {"type": "string"}, "maxItems": 20}})),
    "breakpoints": ("Add or remove breakpoints during the session; returns all of them and whether they are bound.",
                    _schema({"add": {"type": "array", "items": _FILE_LINE, "maxItems": 20},
                             "remove": {"type": "array", "items": _FILE_LINE, "maxItems": 20},
                             "add_functions": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                             "remove_functions": {"type": "array", "items": {"type": "string"}, "maxItems": 20}})),
    "trace": ("Resumes the program (call alone). Run to a line repeatedly; each row has the caller and every named "
              "variable as 'before → after' the line runs (one step per hit). Stops early at other breakpoints.",
              _schema({"file": {"type": "string"}, "line": {"type": "integer", "minimum": 1},
                       "variables": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
                       "hits": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                       "after": {"type": "boolean", "default": True,
                                 "description": "Also step over the line to show the values it produces"},
                       "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 55, "default": 20}},
                      ("file", "line", "variables"))),
    "stop_session": ("End the debug session and remove its breakpoints.", _schema({})),
    "write_report": (
        "Write the root-cause report into <workspace>/autodebug-reports/. The session timeline is added automatically.",
        _schema({
            "title": {"type": "string"},
            "problem": {"type": "string", "description": "What goes wrong, as the user sees it"},
            "root_cause": {"type": "string", "description": "Why, citing what the debugger showed"},
            "solution": {"type": "string", "description": "The fix, with code if short"},
            "confidence": {"type": "string", "enum": ["confirmed", "likely", "unconfirmed"]},
            "how_confirmed": {"type": "string", "description": "Required for confirmed"},
            "verification": {"type": "string", "description": "How the fix was checked, if it was"},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "workspace_folder": _FOLDER,
        }, ("title", "problem", "root_cause", "solution", "confidence"))),
}
_METHODS = {"continue": "continue_"}


def _valid(value: object, schema: dict) -> bool:
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict) or (schema.get("additionalProperties") is False
                                           and value.keys() - schema.get("properties", {}).keys()):
            return False
        if any(key not in value for key in schema.get("required", ())):
            return False
        return all(_valid(v, schema["properties"][k]) for k, v in value.items() if k in schema.get("properties", {}))
    if kind == "array":
        return (isinstance(value, list) and len(value) >= schema.get("minItems", 0)
                and len(value) <= schema.get("maxItems", 10**6) and all(_valid(v, schema["items"]) for v in value))
    if kind == "string":
        return isinstance(value, str) and len(value) <= 20000 and value in schema.get("enum", [value])
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)
                and schema.get("minimum", -10**9) <= value <= schema.get("maximum", 10**9))
    if kind == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and schema.get("minimum", -10**9) <= value <= schema.get("maximum", 10**9))
    return True


class Server:
    def __init__(self, debugger: Debugger | None = None, stdin: BinaryIO | None = None,
                 stdout: BinaryIO | None = None) -> None:
        self.debugger = debugger or Debugger()
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        self._write_lock = threading.Lock()
        self._tool_lock = threading.Lock()  # one debugger action at a time
        self._threads: list[threading.Thread] = []

    def _send(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        with self._write_lock:
            try:
                self.stdout.write(data)
                self.stdout.flush()
            except (OSError, ValueError):
                pass

    def _reply(self, request_id, result=None, error=None) -> None:
        message = {"jsonrpc": "2.0", "id": request_id}
        message.update({"error": error} if error else {"result": result})
        self._send(message)

    def serve(self) -> None:
        for line in self.stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self._reply(None, error={"code": -32700, "message": "parse error"})
                continue
            if isinstance(message, dict):
                self.handle(message)
        for thread in self._threads:
            thread.join(timeout=5)
        self.debugger.close()

    def handle(self, message: dict) -> None:
        method, request_id, params = message.get("method"), message.get("id"), message.get("params") or {}
        if request_id is None:
            return  # notifications (initialized, cancelled) need no answer
        if method == "initialize":
            asked = params.get("protocolVersion")
            self._reply(request_id, {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "autodebug", "version": __version__},
                "instructions": INSTRUCTIONS,
            })
        elif method == "ping":
            self._reply(request_id, {})
        elif method == "tools/list":
            self._reply(request_id, {"tools": [{"name": n, "description": d, "inputSchema": s}
                                                for n, (d, s) in TOOLS.items()]})
        elif method == "tools/call":
            thread = threading.Thread(target=self._call_tool, args=(request_id, params), daemon=True)
            self._threads = [t for t in self._threads if t.is_alive()] + [thread]
            thread.start()
        else:
            self._reply(request_id, error={"code": -32601, "message": f"unknown method {method}"})

    def _call_tool(self, request_id, params: dict) -> None:
        name, arguments = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            self._reply(request_id, error={"code": -32602, "message": f"unknown tool {name}"})
            return
        if not _valid(arguments, TOOLS[name][1]):
            self._reply(request_id, error={"code": -32602, "message": f"invalid arguments for {name}"})
            return
        try:
            with self._tool_lock:
                result = getattr(self.debugger, _METHODS.get(name, name))(**arguments)
            is_error = False
        except DebugError as exc:
            result, is_error = {"error": exc.code, "message": exc.message}, True
        except (OSError, ValueError) as exc:
            result, is_error = {"error": "IDE_ERROR", "message": str(exc)}, True
        except Exception:  # noqa: BLE001 — never crash the server on one tool
            _LOG.exception("tool %s failed", name)
            result, is_error = {"error": "IDE_ERROR", "message": "internal error; see the server log"}, True
        self._reply(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                                 "structuredContent": result, "isError": is_error})
