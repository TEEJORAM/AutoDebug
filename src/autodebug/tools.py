"""The agent-facing debugging tools (docs/design.md, "Agent tools").

`Debugger` keeps one connection to the chosen IDE window, the session's
timeline for the report, and applies redaction to everything it returns.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from autodebug import report
from autodebug.build import describe
from autodebug.connection import (
    IDE_NAMES,
    DebugError,
    Window,
    choose,
    discover,
    matching,
    outdated_extension,
    preferred_ide,
    same_folder,
)
from autodebug.redact import REDACTED, clean_text, clean_value, is_secret_name
from autodebug.session import Session, connect

SHORT_VALUE = 200
MAX_CAPTURES = 5
_NO_ANSWER = ("Nobody answered the Approve dialog in {ide} within 2 minutes, so nothing ran; it was probably "
              "behind another window. This was not a Deny. Ask the developer whether to try again.")
STOPPED = ("paused", "ended", "denied", "build_failed")

_NEXT = {
    "awaiting_approval": ("Tell the developer the Approve dialog is open in {ide} (switch to {ide} if it is hidden) "
                          "and that it closes unanswered after 2 minutes; then call wait."),
    "denied": "The developer did not approve; nothing ran. Ask before trying again.",
    "building": "The build task is running; call wait.",
    "build_failed": "The build failed (output is in the IDE terminal). Fix it or ask the developer.",
    "starting": "The debugger is starting. Large programs can take minutes to load symbols, so keep calling wait.",
    "running": "The program is running; call wait for the next stop, or pause.",
    "paused": "Paused. Use inspect, stack, step, continue, trace, breakpoints or watch.",
    "ended": "The debug session ended. Call write_report with your findings.",
}


_ERROR_LINE = re.compile(r"error|exception|fail|traceback|assert|panic|fatal", re.IGNORECASE)


def _telling_lines(output: list[str], count: int = 3) -> list[str]:
    """The output lines that explain an exit: errors and failures first, else the last lines."""
    lines = [line.strip() for line in output if line.strip() and set(line.strip()) - set("-=_*")]
    errors = [line for line in lines if _ERROR_LINE.search(line)]
    return (errors or lines)[-count:]


def _breakpoint(b: dict) -> dict:
    """A breakpoint as the agent sees it: where, who set it, whether it is bound, and its options."""
    at = f"function {b['function']}" if b.get("function") else (
        f"{b.get('file')}:{b.get('line')}" + (f":{b['column']}" if b.get("column") else ""))
    shown = {"at": clean_text(at, 300), "source": b.get("source", "session"), "verified": b.get("verified", False)}
    for key, name, limit in (("condition", "when", 200), ("hit_condition", "hits", 20), ("log_message", "logs", 300),
                             ("message", "note", 200)):
        if b.get(key):
            shown[name] = clean_text(b[key], limit)
    return shown


@dataclass
class Event:
    kind: str
    where: str
    detail: str
    at: float = field(default_factory=time.time)


class Debugger:
    def __init__(self, find_windows: Callable[[], list[Window]] = discover, connect: Callable[[Window], Session] = connect) -> None:
        self._find_windows = find_windows
        self._connect = connect
        self.connection: Session | None = None
        self.folder: str | None = None
        self.version = 0
        self.timeline: list[Event] = []
        self.plan: dict = {}
        self.sessions = 0
        self._last_status: str | None = None
        self._last_build: dict | None = None
        self._last_exception: str | None = None
        self._activity_seen = 0
        self.ticket: str | None = None
        self.reproducing: dict | None = None  # the current session, when it only reproduces the bug
        self.reproductions: list[dict] = []  # reproduction runs since the last report
        self.evidence: list[dict] = []  # captured stops since the last report
        self.usage = {"calls": 0, "characters": 0}  # tool traffic since the last report

    # -- helpers ------------------------------------------------------------

    def _log(self, kind: str, where: str = "", detail: str = "") -> None:
        self.timeline.append(Event(kind, clean_text(where, 300), clean_text(detail, 1000)))

    def _window(self, folder: str | None, ide: str | None = None) -> Window:
        return choose(self._find_windows(), folder, ide)

    def _window_for(self, folder: str | None, ide: str | None, launch: str) -> Window:
        """The window to start `launch` in. When the developer did not name an IDE and several windows match
        (say Cursor, where they chat, and Visual Studio, where they debug): their `--debug-in` choice, else the
        only window that has a launch configuration with that name."""
        try:
            return self._window(folder, ide)
        except DebugError as exc:
            if exc.code != "AMBIGUOUS_WINDOW":
                raise
        windows = matching(self._find_windows(), folder, ide)
        preferred = None if ide else preferred_ide()
        if preferred and [w for w in windows if w.ide == preferred]:
            windows = [w for w in windows if w.ide == preferred]
            if len(windows) == 1:
                return windows[0]
        having = [w for w in windows if launch in self._launch_names(w, folder)]
        if len(having) == 1:
            return having[0]
        listed = "; ".join(f"{IDE_NAMES.get(w.ide, w.ide)}: {', '.join(w.folders)}" for w in (having or windows))
        raise DebugError("AMBIGUOUS_WINDOW", f'"{launch}" can run in several windows ({listed}). Pass ide '
                         "(cursor, vscode or visualstudio) and, for two windows of one IDE, workspace_folder. The "
                         "developer can set the IDE they debug in once: autodebug setup --debug-in <ide>.")

    def _launch_names(self, window: Window, folder: str | None) -> set[str]:
        try:
            connection = self._connect(window)
        except DebugError:
            return set()
        try:
            names = set()
            for f in [folder] if folder else list(window.folders):
                names |= {c.get("name") for c in connection.call("targets", {"folder": f}).get("launch", [])}
            return names
        except DebugError:
            return set()
        finally:
            connection.close()

    def _session(self) -> Session:
        if self.connection is None:
            raise DebugError("NOT_FOUND", "no debug session; call start_session first")
        return self.connection

    def _call(self, op: str, args: dict | None = None) -> dict:
        return self._session().call(op, args)

    def _state(self, raw: dict, quiet: bool = False) -> dict:
        """The session state as the agent sees it, logging changes on the timeline.
        `quiet`: the caller (step, trace) already logged this stop."""
        self.version = max(self.version, int(raw.get("version") or 0))
        status = raw.get("status", "none")
        location = raw.get("location") or None
        where = f"{location['file']}:{location['line']}" if location else ""
        result = self._facts(raw, status, where)
        self._log_changes(raw, status, where, quiet, result.get("output") or [])
        ide = self.connection.window.ide if self.connection else "IDE"
        next_step = _NEXT.get(status, "")
        if status == "denied" and "no answer" in str(raw.get("reason") or ""):
            next_step = _NO_ANSWER
        if status == "ended" and self.reproducing is not None:
            next_step = self._reproduced(result, ide)
        result["next"] = next_step.format(ide=IDE_NAMES.get(ide, "IDE"))
        if status == "paused":
            result["variables"] = self._short_variables()
        return result

    def _facts(self, raw: dict, status: str, where: str) -> dict:
        """What the state says, redacted: where, why, steps, breakpoints, watches, new activity, output, exception."""
        result: dict = {"status": status}
        if where:
            result["location"] = clean_text(where, 300)
        for key in ("reason", "exit_code", "message"):
            if raw.get(key) not in (None, ""):
                result[key] = clean_text(raw[key], 500) if isinstance(raw[key], str) else raw[key]
        if "steps_used" in raw:
            result["steps"] = (f"{raw['steps_used']} of {raw['max_steps']} used" if raw.get("max_steps")
                               else f"{raw['steps_used']} used")
        if raw.get("breakpoints"):
            result["breakpoints"] = [_breakpoint(b) for b in raw["breakpoints"]]
        if raw.get("watches"):
            result["watches"] = raw["watches"]
        fresh = [a for a in raw.get("activity") or [] if a.get("seq", 0) > self._activity_seen]
        if fresh:
            self._activity_seen = fresh[-1]["seq"]
            result["activity"] = [clean_text(a["text"], 300) for a in fresh]
        output = [clean_text(line, 500) for line in raw.get("output") or []]
        if output and status == "ended":
            result["output"] = output
        for key in ("output_note", "thread"):
            if raw.get(key):
                result[key] = raw[key]
        if raw.get("exception"):
            result["exception"] = {"id": clean_text(raw["exception"].get("id"), 200),
                                   "description": clean_text(raw["exception"].get("description"), 500)}
            if result["exception"]["id"] != self._last_exception:
                self._last_exception = result["exception"]["id"]
                self._log("exception", result["exception"]["id"], result["exception"]["description"])
        return result

    def _log_changes(self, raw: dict, status: str, where: str, quiet: bool, output: list[str]) -> None:
        """The timeline: the Approve click, the build, and each new stop or end (once)."""
        key = (status, where, raw.get("reason"))
        changed, previous = key != self._last_status, self._last_status
        if changed and previous and previous[0] == "awaiting_approval" and status not in ("denied", "awaiting_approval"):
            self._log("approved", "", "the developer clicked Approve")
        build = raw.get("build")
        if build and build.get("status") != "running" and build != self._last_build:
            self._last_build = build
            self._log("build", str(build.get("task")), f"{build.get('status')}, exit code {build.get('exit_code')}")
        if not changed:
            return
        self._last_status = key
        if status == "paused" and not quiet:
            self._log("stopped", where, str(raw.get("reason") or ""))
        elif status == "ended":
            code = raw.get("exit_code")
            last = _telling_lines(output)
            self._log("ended", "", f"{raw.get('reason') or ''}" + (f", exit code {code}" if code is not None else "")
                      + (f"; output: {' / '.join(last)}" if last else ""))
        elif status in ("denied", "build_failed", "running"):
            self._log(status, "", str(raw.get("reason") or raw.get("message") or ""))

    def _reproduced(self, result: dict, ide: str) -> str:
        """A reproduction run ended: record what it showed and tell the agent to compare it with the ticket."""
        run = self.reproducing
        if not run["recorded"]:
            run["recorded"] = True
            self.reproductions.append({"launch": run["launch"], "args": run["args"], "symptom": run["symptom"],
                                       "exit_code": result.get("exit_code"),
                                       "output": _telling_lines(result.get("output") or [], 5)})
        text = (f"The reproduction run ended (exit code {result.get('exit_code')}). Compare the output and exit code "
                f"with the reported symptom: {run['symptom']!r}. If the bug showed, call start_session with the same "
                "args and ticket and breakpoints where the wrong value appears. If it did not, refine the reproduction "
                "or ask the developer; do not debug a bug you have not seen. Record it in write_report "
                "(reproduction, reproduced).")
        if ide == "visualstudio" and not result.get("output"):
            text += (" Visual Studio does not capture a console program's own output, so make the reproduction "
                     "exit with a non-zero code when the bug shows.")
        return text.replace("{", "{{").replace("}", "}}")

    def _wait(self, seconds: float, until: tuple[str, ...] = STOPPED) -> dict:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = deadline - time.monotonic()
            wait_ms = int(max(0.0, min(remaining, 25.0)) * 1000)
            raw = self._call("state", {"since": self.version, "wait_ms": wait_ms})["state"]
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
        if variable.get("size"):
            cleaned["size"] = variable["size"]
        if variable.get("page"):
            cleaned["page"] = variable["page"]
        if variable.get("children"):
            cleaned["children"] = [self._clean_variable(child, limit, secret) for child in variable["children"]]
        return cleaned

    def _values(self) -> dict[str, str]:
        return {v["name"]: clean_value(v["name"], v.get("value")) for v in self._raw_variables()}

    # -- tools ---------------------------------------------------------------

    def list_targets(self, workspace_folder: str | None = None, ide: str | None = None) -> dict:
        found = self._find_windows()
        windows = [w for w in found if w.current and (ide is None or w.ide == ide)]
        if workspace_folder:
            windows = [choose(found, workspace_folder, ide)]
        if not windows:
            choose(found, None, ide)  # raises the setup or version hint
        found = []
        for window in windows:
            connection = self._connect(window)
            try:
                folders = [workspace_folder] if workspace_folder else list(window.folders)
                targets = [connection.call("targets", {"folder": f}) for f in folders]
            finally:
                connection.close()
            entry = {"ide": window.ide, "folders": targets}
            if outdated_extension(window):
                entry["extension_note"] = outdated_extension(window)
            found.append(entry)
        several = len(windows) > 1
        for entry, window in zip(found, windows, strict=True):
            for folder in entry["folders"]:
                for config in folder.get("launch", []):
                    config["start_with"] = {"launch_configuration": config.get("name"), "ide": window.ide,
                                            **({"workspace_folder": folder.get("folder")} if several else {})}
        result = {"windows": found,
                  "next": "Pick a launch configuration and pass its start_with values to start_session (with the "
                          "breakpoints and your goal). Tell the developer which IDE and which build you will debug; "
                          "each configuration's build says whether it is optimized and has debug symbols."}
        preferred = preferred_ide()
        if preferred and not ide and len({w["ide"] for w in found}) > 1:
            result["debug_in"] = preferred
            result["next"] += (f" The developer debugs in {IDE_NAMES[preferred]}: start the session there "
                               f"(ide={preferred}).")
        return result

    def open_ide(self, ide: str, path: str, wait_seconds: float = 45) -> dict:
        """Open the solution or folder in the IDE once and wait until its Autodebug extension answers."""
        from autodebug import ide_launch

        opened, folder = ide_launch.target(ide, path)
        name = IDE_NAMES[ide]

        def window():
            return next((w for w in self._find_windows()
                         if w.current and w.ide == ide and any(same_folder(f, str(folder)) for f in w.folders)), None)

        found = window()
        if found:
            return {"status": "open", "ide": ide, "folder": str(folder), "started": False,
                    "next": f"{name} already has {folder} open. Call list_targets with ide={ide}."}
        age = ide_launch.recently_started(ide, opened)
        if age is None:
            ide_launch.start(ide_launch.command(ide, opened))
            ide_launch.remember_start(ide, opened)
            self._log("opened the IDE", str(opened), f"started {name}")
        deadline = time.monotonic() + min(max(wait_seconds, 0), 55)
        while time.monotonic() < deadline:
            found = window()
            if found:
                return {"status": "open", "ide": ide, "folder": str(folder), "started": age is None,
                        "next": f"{name} is open with {folder}. Tell the developer you opened {opened}. "
                                f"Call list_targets with ide={ide}."}
            time.sleep(1)
        return {"status": "opening", "ide": ide, "folder": str(folder), "started": age is None,
                "next": f"{name} is still loading {opened}. Call open_ide again with the same path to keep waiting; "
                        f"it never starts a second copy while the first one loads. Do not start {name} yourself. "
                        "If nothing appears after 3 minutes, ask the developer to check the IDE window."}

    def start_session(self, launch_configuration: str, breakpoints: list[dict], goal: str,
                      workspace_folder: str | None = None, build_task: str | None = None,
                      max_steps: int | None = None, max_minutes: int | None = None, wait_seconds: float = 30,
                      build_minutes: int = 30, process_id: int | None = None,
                      source_folders: list[str] | None = None,
                      function_breakpoints: list[str] | None = None, ide: str | None = None,
                      args: list[str] | None = None, ticket: str | None = None,
                      screenshots: bool | None = None, test: str | None = None) -> dict:
        return self._begin(launch_configuration, breakpoints, goal, workspace_folder=workspace_folder,
                           build_task=build_task, max_steps=max_steps, max_minutes=max_minutes,
                           wait_seconds=wait_seconds, build_minutes=build_minutes, process_id=process_id,
                           source_folders=source_folders, function_breakpoints=function_breakpoints, ide=ide,
                           args=args, ticket=ticket, reproduce=False, screenshots=screenshots, test=test)

    def reproduce(self, launch_configuration: str, symptom: str, args: list[str] | None = None,
                  ticket: str | None = None, workspace_folder: str | None = None, build_task: str | None = None,
                  max_minutes: int | None = None, wait_seconds: float = 30, build_minutes: int = 30,
                  ide: str | None = None, test: str | None = None) -> dict:
        """Run the program once without breakpoints (after Approve) to see whether the reported bug shows."""
        return self._begin(launch_configuration, [], f"Reproduce: {symptom}", workspace_folder=workspace_folder,
                           build_task=build_task, max_steps=1, max_minutes=max_minutes, wait_seconds=wait_seconds,
                           build_minutes=build_minutes, process_id=None, source_folders=None,
                           function_breakpoints=None, ide=ide, args=args, ticket=ticket, reproduce=True,
                           symptom=symptom, test=test)

    def _begin(self, launch_configuration: str, breakpoints: list[dict], goal: str, *, workspace_folder, build_task,
               max_steps, max_minutes, wait_seconds, build_minutes, process_id, source_folders, function_breakpoints,
               ide, args, ticket, reproduce: bool, symptom: str | None = None,
               screenshots: bool | None = None, test: str | None = None) -> dict:
        window = self._window_for(workspace_folder, ide, launch_configuration)
        if self.connection is not None:
            self.connection.close()
        self.connection = self._connect(window)
        # Screenshots of the IDE window: Visual Studio only (VS Code and Cursor cannot take them), on unless the
        # agent turns them off. The Approve dialog says so; the relay refuses them otherwise.
        screenshots = window.ide == "visualstudio" and not reproduce and screenshots is not False
        request = {"folder": workspace_folder, "launch": launch_configuration, "task": build_task,
                   "breakpoints": breakpoints, "goal": goal, "max_steps": max_steps, "max_minutes": max_minutes,
                   "build_minutes": build_minutes, "process_id": process_id, "source_folders": source_folders or [],
                   "function_breakpoints": function_breakpoints or [], "args": args, "ticket": ticket,
                   "reproduce": reproduce, "screenshots": screenshots}
        if test is not None:
            request["test"] = test
        try:
            answer = self._call("start", request)
        except DebugError:
            self.connection.close()
            self.connection = None
            raise
        # The timeline runs until the next report, so it covers every session behind it.
        self.version, self._last_status, self._last_build, self._activity_seen = 0, None, None, 0
        self.sessions += 1
        raw = answer["state"]
        self.folder = answer.get("folder") or workspace_folder or (window.folders[0] if len(window.folders) == 1 else None)
        build = answer.get("build")
        debugging = {"ide": IDE_NAMES.get(window.ide, window.ide), "folder": self.folder,
                     "launch_configuration": launch_configuration, "build": describe(build) if build else "attach: "
                     "the running program's build"}
        if test is not None:
            debugging["test"] = clean_text(test, 300)
        if ticket:
            self.ticket = clean_text(" ".join(str(ticket).split()), 300)
        self.plan = {"goal": goal, "launch": launch_configuration, "task": build_task,
                     "breakpoints": [f"{b.get('file')}:{b.get('line')}" for b in breakpoints], "ide": window.ide,
                     "args": None if args is None else [clean_text(a, 300) for a in args],
                     "build": debugging["build"], "screenshots": screenshots}
        self.reproducing = {"launch": launch_configuration, "args": self.plan["args"],
                            "symptom": clean_text(symptom or "", 500), "recorded": False} if reproduce else None
        shown = "" if args is None else f" with arguments {self.plan['args']}"
        self._log(f"reproduce {self.sessions}" if reproduce else f"session {self.sessions}", "",
                  f"asked the developer to approve running {launch_configuration!r}{shown}"
                  + (f" after building {build_task!r}" if build_task else "")
                  + (" with no breakpoints, to see whether the bug shows" if reproduce else ""))
        self._state(raw)
        result = self._state(self._wait(min(max(wait_seconds, 0), 55)))
        # Say once, plainly, where and what is being debugged, so the agent can tell the developer.
        result["debugging"] = debugging
        if outdated_extension(window):
            result["extension_note"] = outdated_extension(window)
        if build and build.get("note"):
            result["build_note"] = build["note"]
        return result

    def wait(self, timeout_seconds: float = 30, ask_developer: str | None = None) -> dict:
        if ask_developer is not None and len(ask_developer) > 300:
            raise DebugError("BAD_REQUEST", "ask_developer is at most 300 characters")
        if ask_developer:
            self._log("asked the developer", "", clean_text(ask_developer, 300))
            wait_ms = int(min(max(timeout_seconds, 0), 55) * 1000)
            raw = self._call("state", {"since": self.version, "wait_ms": wait_ms, "ask_developer": ask_developer})["state"]
            return self._state(raw)
        return self._state(self._wait(min(max(timeout_seconds, 0), 55)))

    def step(self, kind: str = "over", count: int = 1, wait_ms: int = 15000, target: str | None = None,
             single_thread: bool = False, instruction: bool = False) -> dict:
        if kind not in ("over", "into", "out", "back"):
            raise DebugError("BAD_REQUEST", "kind must be over, into, out or back")
        count = max(1, min(int(count), 20))
        wait_ms = max(0, min(int(wait_ms), 60000))
        before = self._values()
        path = []
        raw = {}
        request = {"kind": kind, "wait_ms": wait_ms, "single_thread": bool(single_thread), "instruction": bool(instruction)}
        for n in range(count):
            if target and n == 0:
                request["target"] = target
            else:
                request.pop("target", None)
            raw = self._call("step", request)["state"]
            location = raw.get("location")
            if location:
                path.append(f"{location['file']}:{location['line']}")
            if raw.get("status") != "paused":
                break
        after = self._values() if raw.get("status") == "paused" else {}
        changed = [{"name": n, "before": before.get(n, "(new)"), "after": v}
                   for n, v in after.items() if before.get(n) != v]
        self._log(f"step {kind}" + (f" to {target}" if target else "") + (" (instruction)" if instruction else "")
                  + (f" ×{len(path)}" if len(path) > 1 else ""), " → ".join(path[-5:]),
                  ", ".join(f"{c['name']}: {c['before']} → {c['after']}" for c in changed[:8]))
        result = self._state(raw, quiet=True)
        result["changed"] = changed
        if len(path) > 1:
            result["path"] = path
        if raw.get("status") == "running":
            result["next"] = "It's a slow function: call wait or pause."
        return result

    def continue_(self, timeout_seconds: float = 30, until: dict | None = None, reverse: bool = False,
                  single_thread: bool = False) -> dict:
        """Run to the next stop, or with `until` run past other breakpoints to that line. `reverse` runs backwards
        to the previous stop (recording debuggers only)."""
        timeout = min(max(timeout_seconds, 0), 55)
        if until is None or reverse:
            if until is not None:
                raise DebugError("BAD_REQUEST", "until and reverse cannot be combined")
            self._call("continue", {"reverse": bool(reverse), "single_thread": bool(single_thread)})
            if reverse:
                self._log("ran backwards", "", "to the previous stop")
            return self._state(self._wait(timeout))
        target = f"{until['file']}:{until['line']}"
        existing = {b["file"] + ":" + str(b["line"]) for b in self._call("breakpoints", {})["state"].get("breakpoints", [])}
        if target not in existing:
            self._call("breakpoints", {"add": [{"file": until["file"], "line": until["line"]}]})
        skipped: list[str] = []
        deadline = time.monotonic() + timeout
        try:
            while True:
                self._call("continue", {"single_thread": bool(single_thread)})
                raw = self._wait(max(deadline - time.monotonic(), 0), until=("paused", "ended"))
                location = raw.get("location")
                where = f"{location['file']}:{location['line']}" if location else ""
                if raw.get("status") != "paused" or where == target or len(skipped) >= 50 or time.monotonic() >= deadline:
                    break
                skipped.append(where)
        finally:
            if target not in existing and self.connection is not None:
                with contextlib.suppress(DebugError):
                    self._call("breakpoints", {"remove": [{"file": until["file"], "line": until["line"]}]})
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

    def exceptions(self, enable: list | None = None, types: list[str] | None = None, mode: str = "always") -> dict:
        args: dict = {} if enable is None else {"enable": enable}
        if types:
            args.update({"types": types, "mode": mode})
        result = self._call("exceptions", args)
        if enable is not None or types:
            chosen = ", ".join(e if isinstance(e, str) else f"{e.get('id')} if {e.get('condition')}" for e in enable or [])
            self._log("exceptions", "", (f"stop on {chosen}" if chosen else "no filters")
                      + (f"; only {', '.join(types)} ({mode})" if types else ""))
        return result

    def _frame(self, frame_index: int) -> int | None:
        if not frame_index:
            return None
        frames = self._call("stack", {"levels": frame_index + 1}).get("frames", [])
        if frame_index >= len(frames):
            raise DebugError("BAD_REQUEST", f"the stack has {len(frames)} frames")
        return frames[frame_index]["id"]

    def inspect(self, names: list[str] | None = None, frame_index: int = 0, depth: int = 0, scope: str | None = None,
                start: int | None = None, count: int | None = None, hex: bool = False) -> dict:
        frame = self._frame(frame_index)
        args: dict = {"names": names, "depth": max(0, min(int(depth), 3))}
        for key, value in (("frame", frame), ("scope", scope), ("start", start), ("count", count)):
            if value is not None:
                args[key] = value
        if hex:
            args["hex"] = True
        raw = self._call("variables", args)
        limit = 2000 if names else SHORT_VALUE
        variables = [self._clean_variable(v, limit) for v in raw.get("variables", [])]
        self._log("inspected", f"frame {frame_index}" + (f", {scope}" if scope else ""),
                  ", ".join(f"{v['name']}={v['value']}" for v in variables[:12]))
        result = {"frame_index": frame_index, "variables": variables,
                  "scopes": [s["name"] + (" (slow)" if s.get("expensive") else "") for s in raw.get("scopes", [])]}
        if names:
            result["not_found"] = [n for n in names if n not in {v["name"] for v in variables}]
        return result

    def capture(self, names: list[str], note: str, wrong: list[str] | None = None, frame_index: int = 0,
                stack_levels: int = 8) -> dict:
        """At the stop that shows the bug: a screenshot of the IDE (code, Locals or Autos, Call Stack) for the report,
        with the agent's one-sentence note. The values are returned to the agent, not written into the report."""
        if len(self.evidence) >= MAX_CAPTURES:
            raise DebugError("LIMIT", f"the report keeps at most {MAX_CAPTURES} captures; keep only the stops that "
                                      "show the bug")
        raw = self._call("stack", {"levels": max(frame_index + 1, min(int(stack_levels), 20))}).get("frames", [])
        if frame_index >= len(raw):
            raise DebugError("BAD_REQUEST", f"the stack has {len(raw)} frames")
        top = raw[frame_index]
        location = "(no source)" if top.get("file") in (None, "(no source)") else clean_text(f"{top.get('file')}:{top.get('line')}", 300)
        found = [self._clean_variable(v, 500) for v in self._raw_variables(top.get("id"), names, 1)]
        item = {"location": location, "function": clean_text(top.get("name"), 200), "note": clean_text(note, 300),
                "wrong": [n for n in (wrong or []) if n in names], "session": self.sessions}
        window = self.connection.window if self.connection else None
        if self.plan.get("screenshots"):
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-stop-{len(self.evidence) + 1}"
            try:
                shot = self._call("screenshot", {"name": name})
                item["screenshot"] = f"screenshots/{name}.png"
                item["variables_window"] = shot.get("variables_window")
            except DebugError as exc:
                item["screenshot_note"] = (outdated_extension(window) if window and outdated_extension(window)
                                           else f"the screenshot failed: {exc.message}")
        else:
            item["screenshot_note"] = ("screenshots were turned off for this session" if window and window.ide ==
                                       "visualstudio" else f"{IDE_NAMES.get(window.ide if window else '', 'this IDE')} "
                                       "cannot take screenshots; only Visual Studio can")
        self.evidence.append(item)
        self._log("captured", location, f"{clean_text(note, 200)}; "
                  + ", ".join(f"{v['name']}={v['value']}" for v in found[:8]))
        result = {"captured": len(self.evidence), "location": location, "function": item["function"],
                  "variables": found}
        if item.get("screenshot"):
            result["screenshot"] = item["screenshot"]
            result["next"] = (f"Saved a screenshot of {IDE_NAMES.get(window.ide, 'the IDE')} at this stop for the "
                              "report. Capture only the stops that show the bug (one or two).")
        else:
            result["screenshot_note"] = item["screenshot_note"]
            result["next"] = f"No screenshot: {item['screenshot_note']} Tell the developer."
        missing = [n for n in names if n not in {v["name"] for v in found}]
        if missing:
            result["not_found"] = missing
        return result

    def watch(self, add: list[dict] | None = None, remove: list[str] | None = None, frame_index: int = 0) -> dict:
        """Stop when a variable's value changes (a data breakpoint, also called a watchpoint)."""
        args: dict = {"add": add or [], "remove": remove or []}
        frame = self._frame(frame_index)
        if frame is not None:
            args["frame"] = frame
        result = self._call("watch", args)
        if add or remove:
            self._log("watch", "", "; ".join(part for part in (
                ("watching " + ", ".join(f"{w.get('name')} ({w.get('access') or 'write'})" for w in add or [])) if add else "",
                ("stopped watching " + ", ".join(remove or [])) if remove else "") if part))
        return {"watches": [{**w, "what": clean_text(w.get("what"), 200)} for w in result.get("watches", [])],
                "next": "continue runs until a watched value changes; the stop's reason says which." if add else ""}

    def modules(self, filter: str | None = None, sources: bool = False) -> dict:
        result = self._call("modules", {"filter": filter, "sources": bool(sources)})
        result["modules"] = [{k: clean_text(v, 500) if isinstance(v, str) else v for k, v in m.items()}
                             for m in result.get("modules", [])]
        return result

    def source(self, frame_index: int = 0, source_reference: int | None = None) -> dict:
        args: dict = {"frame_index": frame_index}
        if source_reference is not None:
            args["source_reference"] = source_reference
        result = self._call("source", args)
        if result.get("code"):
            self._log("read code without a file", f"frame {frame_index}", f"{len(result['code'])} lines")
        return result

    def disassemble(self, frame_index: int = 0, before: int = 8, after: int = 16) -> dict:
        result = self._call("disassemble", {"frame_index": frame_index, "before": before, "after": after})
        current = next((r for r in result.get("instructions", []) if r.get("current")), None)
        self._log("disassembled", f"frame {frame_index}", f"{current['address']}: {current['instruction']}" if current else "")
        return result

    def memory(self, name: str | None = None, count: int = 64, offset: int = 0, frame_index: int = 0) -> dict:
        args: dict = {"count": count, "offset": offset, "frame_index": frame_index}
        if name:
            args["name"] = name
            frame = self._frame(frame_index)
            if frame is not None:
                args["frame"] = frame
        result = self._call("memory", args)
        self._log("read memory", name or f"frame {frame_index} instruction", f"{result.get('count', 0)} bytes")
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
                    add_functions: list[str] | None = None, remove_functions: list[str] | None = None,
                    check: dict | None = None) -> dict:
        if check is not None:
            found = self._call("locations", check)
            if not (add or remove or add_functions or remove_functions):
                return {"valid_lines": found}
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
        result = {"breakpoints": self._state(raw).get("breakpoints", [])}
        if check is not None:
            result["valid_lines"] = found
        return result

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
                    state = self._call("step", {"kind": "over"})["state"]
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
                with contextlib.suppress(DebugError):
                    raw = self._call("breakpoints", {"remove": [{"file": file, "line": line}]})["state"]
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

    def write_report(self, title: str, problem: str, what_went_wrong: str, why: str, solution: str, confidence: str,
                     model: str, how_confirmed: str | None = None, verification: str | None = None,
                     workspace_folder: str | None = None, ticket: str | None = None,
                     steps_to_reproduce: list[str] | None = None, reproduced: str | None = None,
                     debug_findings: str | None = None, pattern: str | None = None,
                     token_usage: str | None = None, fix_verified: bool = False) -> dict:
        folder = workspace_folder or self.folder
        if not folder:
            raise DebugError("BAD_REQUEST", "pass workspace_folder: there is no session to take it from")
        if confidence not in ("confirmed", "likely", "unconfirmed"):
            raise DebugError("BAD_REQUEST", "confidence is confirmed, likely or unconfirmed")
        if confidence == "confirmed" and not how_confirmed:
            raise DebugError("BAD_REQUEST", "confirmed needs how_confirmed (for example: the fix makes the failing test pass)")
        if reproduced is not None and reproduced not in ("yes", "no", "not_tried"):
            raise DebugError("BAD_REQUEST", "reproduced is yes, no or not_tried")
        if confidence == "confirmed" and reproduced in ("no", "not_tried"):
            raise DebugError("BAD_REQUEST", "a root cause cannot be confirmed for a bug that was not reproduced; "
                                            "use likely or unconfirmed")
        if reproduced == "yes" and not steps_to_reproduce:
            raise DebugError("BAD_REQUEST", "reproduced=yes needs steps_to_reproduce (one short step per item)")
        if fix_verified and not verification:
            raise DebugError("BAD_REQUEST", "fix_verified needs verification: how you applied the fix and what showed "
                                            "the bug gone")
        if not str(model).strip():
            raise DebugError("BAD_REQUEST", "model names the AI model you are (as your app shows it); write unknown "
                                            "if you do not know")
        path = report.write(folder, report.Report(
            title=title, problem=problem, what_went_wrong=what_went_wrong, why=why, solution=solution,
            confidence=confidence, model=model, how_confirmed=how_confirmed, verification=verification,
            fix_verified=bool(fix_verified),
            plan=self.plan, ticket=ticket or self.ticket, steps_to_reproduce=list(steps_to_reproduce or []),
            reproduced=reproduced, runs=list(self.reproductions), debug_findings=debug_findings,
            captures=list(self.evidence), pattern=pattern, token_usage=token_usage,
            tool_calls=self.usage["calls"], tool_characters=self.usage["characters"],
        ))
        self.timeline, self.sessions, self.reproductions, self.ticket, self.evidence = [], 0, [], None, []
        self.usage = {"calls": 0, "characters": 0}
        return {"report_file": str(path), "next": "Tell the developer where the report is and summarize it in two or "
                                                  "three plain sentences."}

    def count(self, arguments: dict, result: dict) -> None:
        """Tool traffic since the last report, for the report's AI usage section."""
        self.usage["calls"] += 1
        self.usage["characters"] += len(json.dumps(arguments, ensure_ascii=False)) + len(json.dumps(result, ensure_ascii=False))

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
