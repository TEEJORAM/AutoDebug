"""The agent-facing debugging tools (docs/design.md, "Agent tools").

`Debugger` keeps one connection to the chosen IDE window, the session's
timeline for the report, and applies redaction to everything it returns.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from autodebug import report
from autodebug.connection import Connection, DebugError, Window, choose, discover
from autodebug.redact import clean_text, clean_value

SHORT_VALUE = 200
STOPPED = ("paused", "ended", "denied", "build_failed")

_NEXT = {
    "awaiting_approval": "Ask the developer to click Approve in the {ide} dialog, then call wait.",
    "denied": "The developer did not approve; nothing ran. Ask before trying again.",
    "building": "The build task is running; call wait.",
    "build_failed": "The build failed (output is in the IDE terminal). Fix it or ask the developer.",
    "starting": "The debugger is starting; call wait.",
    "running": "The program is running; call wait for the next stop, or pause.",
    "paused": "Paused. Use inspect, stack, step, continue, trace or breakpoints.",
    "ended": "The debug session ended. Call write_report with your findings.",
}


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
        self._last_status: str | None = None
        self._last_build: dict | None = None

    # -- helpers ------------------------------------------------------------

    def _log(self, kind: str, where: str = "", detail: str = "") -> None:
        self.timeline.append(Event(kind, clean_text(where, 300), clean_text(detail, 1000)))

    def _window(self, folder: str | None) -> Window:
        return choose(self._find_windows(), folder)

    def _session(self) -> Connection:
        if self.connection is None:
            raise DebugError("NOT_FOUND", "no debug session; call start_session first")
        return self.connection

    def _call(self, op: str, args: dict | None = None, timeout: float = 15.0) -> dict:
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
                {"at": f"{b['file']}:{b['line']}", "verified": b.get("verified", False),
                 **({"note": clean_text(b["message"], 200)} if b.get("message") else {})}
                for b in raw["breakpoints"]
            ]
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
                self._log("ended", "", f"{raw.get('reason') or ''}" + (f", exit code {code}" if code is not None else ""))
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

    def _raw_variables(self, frame: int | None = None, names: list[str] | None = None) -> list[dict]:
        args = {"names": names}
        if frame is not None:
            args["frame"] = frame
        return self._call("variables", args).get("variables", [])

    def _short_variables(self, limit: int = 30) -> list[dict]:
        try:
            raw = self._raw_variables()
        except DebugError:
            return []
        return [{"name": v["name"], "type": v.get("type", ""), "value": clean_value(v["name"], v.get("value"), SHORT_VALUE)}
                for v in raw[:limit]]

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
                      max_steps: int = 50, max_minutes: int = 30, wait_seconds: float = 30) -> dict:
        window = self._window(workspace_folder)
        if self.connection is not None:
            self.connection.close()
        self.connection = self._connect(window)
        args = {"folder": workspace_folder, "launch": launch_configuration, "task": build_task,
                "breakpoints": breakpoints, "goal": goal, "max_steps": max_steps, "max_minutes": max_minutes}
        try:
            raw = self._call("start", args)["state"]
        except DebugError:
            self.connection.close()
            self.connection = None
            raise
        self.version, self.timeline, self._last_status, self._last_build = 0, [], None, None
        self.folder = workspace_folder or (window.folders[0] if len(window.folders) == 1 else None)
        self.plan = {"goal": goal, "launch": launch_configuration, "task": build_task,
                     "breakpoints": [f"{b.get('file')}:{b.get('line')}" for b in breakpoints], "ide": window.ide}
        self._log("asked", "", f"the developer to approve running {launch_configuration!r}"
                  + (f" after building {build_task!r}" if build_task else ""))
        self._state(raw)
        return self._state(self._wait(min(max(wait_seconds, 0), 55)))

    def wait(self, timeout_seconds: float = 30) -> dict:
        return self._state(self._wait(min(max(timeout_seconds, 0), 55)))

    def step(self, kind: str = "over", count: int = 1) -> dict:
        if kind not in ("over", "into", "out"):
            raise DebugError("BAD_REQUEST", "kind must be over, into or out")
        count = max(1, min(int(count), 20))
        before = self._values()
        path = []
        raw = {}
        for _ in range(count):
            raw = self._call("step", {"kind": kind}, timeout=20)["state"]
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
        return result

    def continue_(self, timeout_seconds: float = 30) -> dict:
        raw = self._call("continue")["state"]
        self.version = max(self.version, int(raw.get("version") or 0))
        return self._state(self._wait(min(max(timeout_seconds, 0), 55)))

    def pause(self) -> dict:
        self._call("pause")
        return self._state(self._wait(5, until=("paused", "ended")))

    def inspect(self, names: list[str] | None = None, frame_index: int = 0) -> dict:
        frame = None
        if frame_index:
            frames = self._call("stack", {"levels": frame_index + 1}).get("frames", [])
            if frame_index >= len(frames):
                raise DebugError("BAD_REQUEST", f"the stack has {len(frames)} frames")
            frame = frames[frame_index]["id"]
        raw = self._raw_variables(frame, names)
        limit = 2000 if names else SHORT_VALUE
        variables = [{"name": v["name"], "type": v.get("type", ""), "value": clean_value(v["name"], v.get("value"), limit)}
                     for v in raw]
        self._log("inspected", f"frame {frame_index}", ", ".join(f"{v['name']}={v['value']}" for v in variables[:12]))
        result = {"frame_index": frame_index, "variables": variables}
        if names:
            result["not_found"] = [n for n in names if n not in {v["name"] for v in variables}]
        return result

    def stack(self, levels: int = 20) -> dict:
        frames = self._call("stack", {"levels": max(1, min(int(levels), 50))}).get("frames", [])
        return {"frames": [{"index": i, "function": clean_text(f.get("name"), 200),
                            "location": clean_text(f"{f.get('file')}:{f.get('line')}", 300)}
                           for i, f in enumerate(frames)]}

    def breakpoints(self, add: list[dict] | None = None, remove: list[dict] | None = None) -> dict:
        raw = self._call("breakpoints", {"add": add or [], "remove": remove or []})["state"]
        if add or remove:
            self._log("breakpoints", "", "added " + ", ".join(f"{b.get('file')}:{b.get('line')}" for b in add or [])
                      + ("; removed " + ", ".join(f"{b.get('file')}:{b.get('line')}" for b in remove) if remove else ""))
        return {"breakpoints": self._state(raw).get("breakpoints", [])}

    def trace(self, file: str, line: int, variables: list[str], hits: int = 10, timeout_seconds: float = 20) -> dict:
        """Run to `file:line` up to `hits` times, collecting `variables` each time."""
        hits = max(1, min(int(hits), 50))
        target = f"{file}:{line}"
        existing = self._call("breakpoints", {})["state"].get("breakpoints", [])
        had_breakpoint = any(f"{b['file']}:{b['line']}" == target for b in existing)
        raw = self._call("breakpoints", {"add": [{"file": file, "line": line}]})["state"]

        def here(state: dict) -> bool:
            location = state.get("location")
            return state.get("status") == "paused" and bool(location) and f"{location['file']}:{location['line']}" == target

        rows: list[dict] = []

        def record() -> None:
            values = {v["name"]: clean_value(v["name"], v.get("value"), SHORT_VALUE)
                      for v in self._raw_variables(names=list(variables))}
            rows.append({"hit": len(rows) + 1, **{n: values.get(n, "(not defined)") for n in variables}})

        try:
            if here(raw):
                record()
            for _ in range(hits * 5):  # other breakpoints may stop the program in between
                if len(rows) >= hits:
                    break
                if raw.get("status") == "paused":
                    self._call("continue")
                elif raw.get("status") != "running":
                    break
                raw = self._wait(timeout_seconds, until=("paused", "ended"))
                if raw.get("status") != "paused":
                    break
                if here(raw):
                    record()
        finally:
            if not had_breakpoint and raw.get("status") != "ended":
                try:
                    raw = self._call("breakpoints", {"remove": [{"file": file, "line": line}]})["state"]
                except DebugError:
                    pass
        self._log("trace", target, "; ".join(", ".join(f"{k}={v}" for k, v in row.items()) for row in rows[:10]))
        result = self._state(raw, quiet=True)
        result.update({"trace": target, "rows": rows})
        if len(rows) < hits:
            result["note"] = f"{len(rows)} of {hits} hits: the program ended or did not reach {target} in time"
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
        return {"report_file": str(path), "next": "Tell the developer where the report is and summarize it."}

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
