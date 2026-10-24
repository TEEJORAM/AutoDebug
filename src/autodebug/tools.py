"""The agent-facing debugging tools (docs/design.md, "Agent tools").

`Debugger` keeps one connection to the chosen IDE window, the session's
timeline for the report, and applies redaction to everything it returns.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from autodebug import report
from autodebug.connection import Connection, DebugError, Window, choose, discover
from autodebug.redact import REDACTED, clean_text, clean_value, is_secret_name

SHORT_VALUE = 200
STOPPED = ("paused", "ended", "denied", "build_failed")

_NEXT = {
    "awaiting_approval": "Ask the developer to click Approve in the {ide} dialog, then call wait.",
    "denied": "The developer did not approve; nothing ran. Ask before trying again.",
    "building": "The build task is running; call wait.",
    "build_failed": "The build failed (output is in the IDE terminal). Fix it or ask the developer.",
    "starting": "The debugger is starting. Large programs can take minutes to load symbols, so keep calling wait.",
    "running": "The program is running; call wait for the next stop, or pause.",
    "paused": "Paused. Use inspect, stack, step, continue, trace or breakpoints.",
    "ended": "The debug session ended. Call write_report with your findings.",
}


_ERROR_LINE = re.compile(r"error|exception|fail|traceback|assert|panic|fatal", re.IGNORECASE)


def _telling_lines(output: list[str], count: int = 3) -> list[str]:
    """The output lines that explain an exit: errors and failures first, else the last lines."""
    lines = [line.strip() for line in output if line.strip() and set(line.strip()) - set("-=_*")]
    errors = [line for line in lines if _ERROR_LINE.search(line)]
    return (errors or lines)[-count:]


@dataclass
class Event:
    kind: str
    where: str
    detail: str
    at: float = field(default_factory=time.time)


class Debugger:
    def __init__(self, find_windows: Callable[[], list[Window]] = discover, connect=Connection) -> None:
        self._find_windows = find_windows
        self._connect = connect
        self.connection: Connection | None = None
        self.folder: str | None = None
        self.version = 0
        self.timeline: list[Event] = []
        self.plan: dict = {}
        self.sessions = 0
        self._last_status: str | None = None
        self._last_build: dict | None = None
        self._last_exception: str | None = None

    # -- helpers ------------------------------------------------------------

    def _log(self, kind: str, where: str = "", detail: str = "") -> None:
        self.timeline.append(Event(kind, clean_text(where, 300), clean_text(detail, 1000)))

    def _window(self, folder: str | None) -> Window:
        return choose(self._find_windows(), folder)

    def _session(self) -> Connection:
        if self.connection is None:
            raise DebugError("NOT_FOUND", "no debug session; call start_session first")
        return self.connection

    def _call(self, op: str, args: dict | None = None, timeout: float = 30.0) -> dict:
        return self._session().call(op, args, timeout=timeout)

    def _state(self, raw: dict, quiet: bool = False) -> dict:
        """The session state as the agent sees it, logging changes on the timeline.
        `quiet`: the caller (step, trace) already logged this stop."""
        self.version = max(self.version, int(raw.get("version") or 0))
        status = raw.get("status", "none")
        location = raw.get("location") or None
        where = f"{location['file']}:{location['line']}" if location else ""
        result = {"status": status}
        if where:
            result["location"] = clean_text(where, 300)
        for key in ("reason", "exit_code", "message"):
            if raw.get(key) not in (None, ""):
                result[key] = clean_text(raw[key], 500) if isinstance(raw[key], str) else raw[key]
        if "steps_used" in raw:
            result["steps"] = f"{raw['steps_used']} of {raw['max_steps']} used"
        if raw.get("breakpoints"):
            result["breakpoints"] = [
                {"at": clean_text(f"function {b['function']}" if b.get("function") else f"{b.get('file')}:{b.get('line')}", 300),
                 "source": b.get("source", "session"), "verified": b.get("verified", False),
                 **({"note": clean_text(b["message"], 200)} if b.get("message") else {})}
                for b in raw["breakpoints"]
            ]
        output = [clean_text(line, 500) for line in raw.get("output") or []]
        if output and status == "ended":
            result["output"] = output
        if raw.get("output_note"):
            result["output_note"] = raw["output_note"]
        if raw.get("thread"):
            result["thread"] = raw["thread"]
        if raw.get("exception"):
            result["exception"] = {"id": clean_text(raw["exception"].get("id"), 200),
                                   "description": clean_text(raw["exception"].get("description"), 500)}
            if result["exception"]["id"] != self._last_exception:
                self._last_exception = result["exception"]["id"]
                self._log("exception", result["exception"]["id"], result["exception"]["description"])
        build = raw.get("build")
        if build and build.get("status") != "running" and build != self._last_build:
            self._last_build = build
            self._log("build", str(build.get("task")), f"{build.get('status')}, exit code {build.get('exit_code')}")
        key = (status, where, raw.get("reason"))
        if key != self._last_status:
            previous, self._last_status = self._last_status, key
            if previous and previous[0] == "awaiting_approval" and status not in ("denied", "awaiting_approval"):
                self._log("approved", "", "the developer clicked Approve")
            if quiet and status == "paused":
                pass
            elif status == "paused":
                self._log("stopped", where, str(raw.get("reason") or ""))
            elif status == "ended":
                code = raw.get("exit_code")
                last = _telling_lines(output)
                self._log("ended", "", f"{raw.get('reason') or ''}" + (f", exit code {code}" if code is not None else "")
                          + (f"; output: {' / '.join(last)}" if last else ""))
            elif status in ("denied", "build_failed", "running"):
                self._log(status, "", str(raw.get("reason") or raw.get("message") or ""))
        ide = self.connection.window.ide if self.connection else "IDE"
        result["next"] = _NEXT.get(status, "").format(ide="Cursor" if ide == "cursor" else "VS Code")
        if status == "paused":
            result["variables"] = self._short_variables()
        return result

    def _wait(self, seconds: float, until: tuple[str, ...] = STOPPED) -> dict:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = deadline - time.monotonic()
            wait_ms = int(max(0.0, min(remaining, 25.0)) * 1000)
            raw = self._call("state", {"since": self.version, "wait_ms": wait_ms}, timeout=wait_ms / 1000 + 10)["state"]
            self.version = max(self.version, int(raw.get("version") or 0))
            if raw.get("status") in until or time.monotonic() >= deadline:
                return raw

    def _raw_variables(self, frame: int | None = None, names: list[str] | None = None, depth: int = 0) -> list[dict]:
        args = {"names": names, "depth": max(0, min(int(depth), 3))}
        if frame is not None:
            args["frame"] = frame
        return self._call("variables", args).get("variables", [])

    def _short_variables(self, limit: int = 30) -> list[dict]:
        try:
            raw = self._raw_variables()
        except DebugError:
            return []
        return [self._clean_variable(v, SHORT_VALUE) for v in raw[:limit]]

    def _clean_variable(self, variable: dict, limit: int, parent_secret: bool = False) -> dict:
        secret = parent_secret or is_secret_name(variable.get("name", ""))
        cleaned = {"name": variable.get("name", ""), "type": variable.get("type", ""),
                   "value": REDACTED if secret else clean_value(variable.get("name", ""), variable.get("value"), limit)}
        if variable.get("expandable"):
            cleaned["expandable"] = True
        if variable.get("more"):
            cleaned["more"] = variable["more"]
        if variable.get("children"):
            cleaned["children"] = [self._clean_variable(child, limit, secret) for child in variable["children"]]
        return cleaned

    def _values(self) -> dict[str, str]:
        return {v["name"]: clean_value(v["name"], v.get("value")) for v in self._raw_variables()}

    # -- tools ---------------------------------------------------------------

    def list_targets(self, workspace_folder: str | None = None) -> dict:
        windows = self._find_windows()
        if workspace_folder:
            windows = [choose(windows, workspace_folder)]
        if not windows:
            choose(windows, None)  # raises the setup hint
        found = []
        for window in windows:
            connection = self._connect(window)
            try:
                folders = [workspace_folder] if workspace_folder else list(window.folders)
                targets = [connection.call("targets", {"folder": f}) for f in folders]
            finally:
                connection.close()
            found.append({"ide": window.ide, "folders": targets})
        return {"windows": found,
                "next": "Call start_session with a launch configuration name, the breakpoints and your goal."}

    def start_session(self, launch_configuration: str, breakpoints: list[dict], goal: str,
                      workspace_folder: str | None = None, build_task: str | None = None,
                      max_steps: int = 100, max_minutes: int = 30, wait_seconds: float = 30,
                      build_minutes: int = 30, process_id: int | None = None,
                      source_folders: list[str] | None = None,
                      function_breakpoints: list[str] | None = None) -> dict:
        window = self._window(workspace_folder)
        if self.connection is not None:
            self.connection.close()
        self.connection = self._connect(window)
        args = {"folder": workspace_folder, "launch": launch_configuration, "task": build_task,
                "breakpoints": breakpoints, "goal": goal, "max_steps": max_steps, "max_minutes": max_minutes,
                "build_minutes": build_minutes, "process_id": process_id, "source_folders": source_folders or [],
                "function_breakpoints": function_breakpoints or []}
        try:
            raw = self._call("start", args)["state"]
        except DebugError:
            self.connection.close()
            self.connection = None
            raise
        # The timeline runs until the next report, so it covers every session behind it.
        self.version, self._last_status, self._last_build = 0, None, None
        self.sessions += 1
        self.folder = workspace_folder or (window.folders[0] if len(window.folders) == 1 else None)
        self.plan = {"goal": goal, "launch": launch_configuration, "task": build_task,
                     "breakpoints": [f"{b.get('file')}:{b.get('line')}" for b in breakpoints], "ide": window.ide}
        self._log(f"session {self.sessions}", "", f"asked the developer to approve running {launch_configuration!r}"
                  + (f" after building {build_task!r}" if build_task else ""))
        self._state(raw)
        return self._state(self._wait(min(max(wait_seconds, 0), 55)))

    def wait(self, timeout_seconds: float = 30, ask_developer: str | None = None) -> dict:
        if ask_developer is not None and len(ask_developer) > 300:
            raise DebugError("BAD_REQUEST", "ask_developer is at most 300 characters")
        if ask_developer:
            self._log("asked the developer", "", clean_text(ask_developer, 300))
            wait_ms = int(min(max(timeout_seconds, 0), 55) * 1000)
            raw = self._call("state", {"since": self.version, "wait_ms": wait_ms, "ask_developer": ask_developer},
                             timeout=wait_ms / 1000 + 10)["state"]
            return self._state(raw)
        return self._state(self._wait(min(max(timeout_seconds, 0), 55)))

    def step(self, kind: str = "over", count: int = 1, wait_ms: int = 15000) -> dict:
        if kind not in ("over", "into", "out"):
            raise DebugError("BAD_REQUEST", "kind must be over, into or out")
        count = max(1, min(int(count), 20))
        wait_ms = max(0, min(int(wait_ms), 60000))
        before = self._values()
        path = []
        raw = {}
        for _ in range(count):
            raw = self._call("step", {"kind": kind, "wait_ms": wait_ms}, timeout=wait_ms / 1000 + 10)["state"]
            location = raw.get("location")
            if location:
                path.append(f"{location['file']}:{location['line']}")
            if raw.get("status") != "paused":
                break
        after = self._values() if raw.get("status") == "paused" else {}
        changed = [{"name": n, "before": before.get(n, "(new)"), "after": v}
                   for n, v in after.items() if before.get(n) != v]
        self._log(f"step {kind}" + (f" ×{len(path)}" if len(path) > 1 else ""), " → ".join(path[-5:]),
                  ", ".join(f"{c['name']}: {c['before']} → {c['after']}" for c in changed[:8]))
        result = self._state(raw, quiet=True)
        result["changed"] = changed
        if len(path) > 1:
            result["path"] = path
        if raw.get("status") == "running":
            result["next"] = "It's a slow function: call wait or pause."
        return result

    def continue_(self, timeout_seconds: float = 30, until: dict | None = None) -> dict:
        """Run to the next stop, or with `until` run past other breakpoints to that line."""
        timeout = min(max(timeout_seconds, 0), 55)
        if until is None:
            self._call("continue")
            return self._state(self._wait(timeout))
        target = f"{until['file']}:{until['line']}"
        existing = {b["file"] + ":" + str(b["line"]) for b in self._call("breakpoints", {})["state"].get("breakpoints", [])}
        if target not in existing:
            self._call("breakpoints", {"add": [{"file": until["file"], "line": until["line"]}]})
        skipped: list[str] = []
        deadline = time.monotonic() + timeout
        try:
            while True:
                self._call("continue")
                raw = self._wait(max(deadline - time.monotonic(), 0), until=("paused", "ended"))
                location = raw.get("location")
                where = f"{location['file']}:{location['line']}" if location else ""
                if raw.get("status") != "paused" or where == target or len(skipped) >= 50 or time.monotonic() >= deadline:
                    break
                skipped.append(where)
        finally:
            if target not in existing and self.connection is not None:
                try:
                    self._call("breakpoints", {"remove": [{"file": until["file"], "line": until["line"]}]})
                except DebugError:
                    pass
        if skipped:
            self._log("continued past", ", ".join(skipped[:5]), f"to reach {target}")
        result = self._state(raw)
        if skipped:
            result["skipped_stops"] = skipped
        return result

    def pause(self) -> dict:
        self._call("pause")
        return self._state(self._wait(5, until=("paused", "ended")))

    def threads(self, select: int | None = None) -> dict:
        args = {} if select is None else {"select": select}
        raw = self._call("threads", args)
        result = {"threads": raw.get("threads", []), "current": raw.get("current")}
        if raw.get("state"):
            seen = self._state(raw["state"])
            if seen.get("status"):
                result["status"] = seen["status"]
            if seen.get("location"):
                result["location"] = seen["location"]
        return result

    def exceptions(self, enable: list[str] | None = None) -> dict:
        return self._call("exceptions", {} if enable is None else {"enable": enable})

    def inspect(self, names: list[str] | None = None, frame_index: int = 0, depth: int = 0) -> dict:
        frame = None
        if frame_index:
            frames = self._call("stack", {"levels": frame_index + 1}).get("frames", [])
            if frame_index >= len(frames):
                raise DebugError("BAD_REQUEST", f"the stack has {len(frames)} frames")
            frame = frames[frame_index]["id"]
        raw = self._raw_variables(frame, names, depth)
        limit = 2000 if names else SHORT_VALUE
        variables = [self._clean_variable(v, limit) for v in raw]
        self._log("inspected", f"frame {frame_index}", ", ".join(f"{v['name']}={v['value']}" for v in variables[:12]))
        result = {"frame_index": frame_index, "variables": variables}
        if names:
            result["not_found"] = [n for n in names if n not in {v["name"] for v in variables}]
        return result

    def stack(self, levels: int = 20, start_frame: int = 0) -> dict:
        body = self._call("stack", {"levels": max(1, min(int(levels), 200)), "start_frame": max(0, int(start_frame))})
        frames = body.get("frames", [])
        return {"total": body.get("total", len(frames)),
                "frames": [{"index": start_frame + i, "function": clean_text(f.get("name"), 200),
                            "location": "(no source)" if f.get("file") in (None, "(no source)")
                            else clean_text(f"{f.get('file')}:{f.get('line')}", 300)}
                           for i, f in enumerate(frames)]}

    def breakpoints(self, add: list[dict] | None = None, remove: list[dict] | None = None,
                    add_functions: list[str] | None = None, remove_functions: list[str] | None = None) -> dict:
        raw = self._call("breakpoints", {"add": add or [], "remove": remove or [],
                                         "add_functions": add_functions or [], "remove_functions": remove_functions or []})["state"]
        changes = [f"{verb} " + ", ".join(f"{b.get('file')}:{b.get('line')}" for b in items)
                   for verb, items in (("added", add), ("removed", remove)) if items]
        if add_functions:
            changes.append("added functions " + ", ".join(add_functions))
        if remove_functions:
            changes.append("removed functions " + ", ".join(remove_functions))
        if changes:
            self._log("breakpoints", "", "; ".join(changes))
        return {"breakpoints": self._state(raw).get("breakpoints", [])}

    def trace(self, file: str, line: int, variables: list[str], hits: int = 10, after: bool = True,
              timeout_seconds: float = 20) -> dict:
        """Run to `file:line` up to `hits` times. Each row has the caller and each variable as
        `before → after` the line runs (one step over per hit when `after`). Stops early,
        and returns the rows so far, when another breakpoint pauses the program."""
        hits = max(1, min(int(hits), 50))
        target = f"{file}:{line}"
        existing = {f"{b['file']}:{b['line']}" for b in self._call("breakpoints", {})["state"].get("breakpoints", [])}
        raw = self._call("breakpoints", {"add": [{"file": file, "line": line}]})["state"]
        rows: list[dict] = []
        notes: list[str] = []

        def where(state: dict) -> str:
            location = state.get("location")
            return f"{location['file']}:{location['line']}" if location else ""

        def values() -> dict[str, str]:
            return {v["name"]: clean_value(v["name"], v.get("value"), SHORT_VALUE)
                    for v in self._raw_variables(names=list(variables))}

        def record() -> dict:
            frames = self._call("stack", {"levels": 2}).get("frames", [])
            caller = clean_text(f"{frames[1]['file']}:{frames[1]['line']}", 300) if len(frames) > 1 else ""
            before, after_values, state = values(), None, raw
            if after:
                try:
                    state = self._call("step", {"kind": "over"}, timeout=20)["state"]
                    after_values = values() if state.get("status") == "paused" else None
                except DebugError as exc:
                    notes.append(f"no after-values: {exc.message}")
            row = {"hit": len(rows) + 1, "caller": caller}
            for name in variables:
                old = before.get(name, "(not defined)")
                new = after_values.get(name, "(not defined)") if after_values is not None else old
                row[name] = old if new == old else f"{old} → {new}"
            rows.append(row)
            return state

        consumed, first = False, True
        try:
            for _ in range(hits * 4 + 4):
                if len(rows) >= hits:
                    break
                status = raw.get("status")
                if status == "paused" and where(raw) == target and not consumed:
                    raw = record()
                    consumed = not after
                    continue
                if status == "paused" and not first and raw.get("reason") == "breakpoint" and where(raw) != target:
                    notes.append(f"stopped at {where(raw)} (another breakpoint); returning the rows so far")
                    break
                if status == "paused":
                    self._call("continue")
                elif status != "running":
                    break
                first, consumed = False, False
                raw = self._wait(timeout_seconds, until=("paused", "ended"))
                if raw.get("status") == "running":
                    notes.append(f"{target} was not reached within {timeout_seconds:g} s")
                    break
        finally:
            if target not in existing and raw.get("status") != "ended":
                try:
                    raw = self._call("breakpoints", {"remove": [{"file": file, "line": line}]})["state"]
                except DebugError:
                    pass
        self._log("trace", target, "; ".join(
            ", ".join(f"{k}={v}" for k, v in row.items() if k not in ("hit", "caller")) for row in rows[:10]))
        result = self._state(raw, quiet=True)
        result.update({"trace": target, "rows": rows})
        if len(rows) < hits and not notes:
            notes.append(f"{len(rows)} of {hits} hits: the program ended first")
        if notes:
            result["note"] = "; ".join(notes)
        return result

    def stop_session(self) -> dict:
        raw = self._call("stop")["state"]
        return self._state(raw)

    def write_report(self, title: str, problem: str, root_cause: str, solution: str, confidence: str,
                     how_confirmed: str | None = None, verification: str | None = None,
                     open_questions: list[str] | None = None, workspace_folder: str | None = None) -> dict:
        folder = workspace_folder or self.folder
        if not folder:
            raise DebugError("BAD_REQUEST", "pass workspace_folder: there is no session to take it from")
        if confidence not in ("confirmed", "likely", "unconfirmed"):
            raise DebugError("BAD_REQUEST", "confidence is confirmed, likely or unconfirmed")
        if confidence == "confirmed" and not how_confirmed:
            raise DebugError("BAD_REQUEST", "confirmed needs how_confirmed (for example: the fix makes the failing test pass)")
        path = report.write(folder, report.Report(
            title=title, problem=problem, root_cause=root_cause, solution=solution, confidence=confidence,
            how_confirmed=how_confirmed, verification=verification, open_questions=list(open_questions or []),
            plan=self.plan, timeline=list(self.timeline),
        ))
        self.timeline, self.sessions = [], 0
        return {"report_file": str(path), "next": "Tell the developer where the report is and summarize it."}

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
