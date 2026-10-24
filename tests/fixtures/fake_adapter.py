"""A deterministic, in-memory adapter double used only by tests (T03+).

Unlike the real IDE adapter stubs (vscode.py, cursor.py, ...), which always
fail closed until their native-debugger proof task lands (T08-T12), this
fake actually performs `launch_or_attach` in memory, so router and
session-registry logic can be exercised end-to-end without a real IDE.
"""

from __future__ import annotations

import itertools

from autodebug.adapters.base import BaseAdapter
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import SessionRef, StopSnapshot
from autodebug.workflow import BreakpointBindingResult


class FakeAdapter(BaseAdapter):
    ide_id = "fake"
    supported_os = ("Windows", "Darwin", "Linux")
    proof_task_id = "N/A (test double, not a real IDE adapter)"
    supports_bounded_operations = True

    def __init__(self, *, can_launch_or_attach: bool = True, can_bind_breakpoints: bool = True) -> None:
        self.can_launch_or_attach = can_launch_or_attach
        #: T07 security-review addition: lets a test force an RP-06
        #: `BREAKPOINT_UNBOUND` failure (every real IDE adapter can fail to
        #: bind a breakpoint — an invalid line, a file not yet loaded, ...)
        #: without needing a real debugger to reproduce it.
        self.can_bind_breakpoints = can_bind_breakpoints
        self.launch_or_attach_calls = 0
        self.disconnect_calls = 0
        self._sessions: dict[str, SessionRef] = {}
        self._ids = itertools.count(1)
        #: debug_session_ids currently "paused" — only ever set by
        #: `simulate_stop`, this fixture's stand-in for "the developer
        #: reproduced the bug in their IDE." No production code calls it.
        self._paused: set[str] = set()
        self._stops: dict[str, StopSnapshot] = {}
        self._stop_ids = itertools.count(1)
        self._bindings = {}

    def list_sessions(self):
        return tuple(self._sessions.values())

    def set_breakpoints(self, session, resolved_locations):
        """T07 fake end-to-end: every requested breakpoint binds unless
        `can_bind_breakpoints` is `False` (this is a test double, not a
        real debugger) — unlike the real adapter stubs, which remain
        `NotImplementedError` until T08-T12."""
        self._bindings[session.debug_session_id] = tuple(resolved_locations)
        return tuple(
            BreakpointBindingResult(
                file=bp.file,
                line=bp.line,
                bound=self.can_bind_breakpoints,
                reason="" if self.can_bind_breakpoints else "fake: line not reachable",
            )
            for bp in resolved_locations
        )

    def simulate_stop(self, debug_session_id: str) -> None:
        """Test-only hook standing in for a real breakpoint hit (T07
        end-to-end exercise). Nothing in `src/autodebug` calls this."""
        self._paused.add(debug_session_id)
        number = next(self._stop_ids)
        bindings = self._bindings.get(debug_session_id, ())
        bp = bindings[0] if bindings else None
        self._stops[debug_session_id] = StopSnapshot(
            self._sessions[debug_session_id], f"fake-stop-{number}", "breakpoint", number,
            bp.file if bp else None, bp.line if bp else None,
        )

    def get_stop(self, session):
        return self._stops.get(session.debug_session_id) if self.is_paused(session.debug_session_id) else None

    def is_paused(self, debug_session_id: str) -> bool:
        """Non-blocking poll used by the T07 facade's own cancellable wait
        loop — this fixture never blocks internally, so the facade decides
        how and how often to poll."""
        return debug_session_id in self._paused

    def get_stack(self, session, frame_limit):
        return tuple(
            {"frame": f"fake_frame_{i}", "file": "/fake/disposable-test-app.py", "line": 10 + i}
            for i in range(min(frame_limit, 3))
        )

    def get_variables(self, session, frame_id, selected_names):
        fake_values = {"local_var": "42", "password": "hunter2"}
        return {name: fake_values.get(name, "undefined") for name in selected_names}

    def step(self, session, kind):
        self.simulate_stop(session.debug_session_id)
        return None

    def continue_execution(self, session):
        self._paused.discard(session.debug_session_id)
        return None

    def launch_or_attach(self, target, reviewed_configuration):
        self.launch_or_attach_calls += 1
        if not self.can_launch_or_attach:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.CAPABILITY_UNSUPPORTED,
                    message=f"{self.ide_id}.launch_or_attach is not supported by this fake backend",
                )
            )
        sequence = next(self._ids)
        debug_session_id = f"fake-session-{sequence}"
        session = SessionRef(
            host_id=target.host_id,
            ide=target.ide,
            ide_instance_id=f"{target.ide}-fake-window",
            debug_session_id=debug_session_id,
            session_generation=1,
            pid=target.pid if target.pid is not None else 10_000 + sequence,
            executable="/fake/disposable-test-app",
            state="running",
            capabilities=("list_sessions", "launch_or_attach"),
            process_start_id=f"fake-process-start-{sequence}",
        )
        self._sessions[debug_session_id] = session
        return session

    def disconnect(self, session):
        self.disconnect_calls += 1
        self._sessions.pop(session.debug_session_id, None)
