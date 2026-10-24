"""Isolated synthetic debugger. Never attaches to an IDE, process or network."""

from __future__ import annotations

import itertools
import threading
import uuid

from autodebug.adapters.base import BaseAdapter, CORE_OPERATIONS, CapabilityReport
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import CapabilityState, SessionRef, StopSnapshot, TargetRef
from autodebug.workflow import BreakpointBindingResult


class SyntheticAdapter(BaseAdapter):
    ide_id = "fake"
    supported_os = ("Windows", "Darwin", "Linux")
    proof_task_id = "synthetic only; not native certification"
    supports_bounded_operations = True

    def __init__(self, *, can_launch_or_attach=True, can_bind_breakpoints=True, paused_on_launch=True):
        self.target = TargetRef("local-synthetic", "fake", None, None)
        self.can_launch_or_attach = can_launch_or_attach
        self.can_bind_breakpoints = can_bind_breakpoints
        self.paused_on_launch = paused_on_launch
        self.launch_or_attach_calls = 0
        self.disconnect_calls = 0
        self._sessions: dict[str, SessionRef] = {}
        self._stops: dict[str, StopSnapshot] = {}
        self._breakpoints: dict[str, tuple] = {}
        self._ids = itertools.count(1)
        self._stop_ids = itertools.count(1)
        self._lock = threading.RLock()

    def probe_capabilities(self, backend=None, host_os=None):
        if backend is not None:
            return super().probe_capabilities(backend, host_os)
        import platform

        return CapabilityReport(
            ide="fake", host_os=host_os or platform.system(),
            state=CapabilityState.AVAILABLE, ide_version="synthetic-1",
            backend_version="synthetic-1", reason="isolated in-memory simulation, not a native debugger",
            operations={op: CapabilityState.AVAILABLE for op in (*CORE_OPERATIONS, "get_stop")},
        )

    def list_sessions(self):
        with self._lock:
            return tuple(self._sessions.values())

    def launch_or_attach(self, target, reviewed_configuration):
        with self._lock:
            self.launch_or_attach_calls += 1
            if not self.can_launch_or_attach:
                raise AutoDebugError(ErrorDetail(code=ErrorCode.CAPABILITY_UNSUPPORTED, message="synthetic launch disabled"))
            number = next(self._ids)
            session = SessionRef(
                target.host_id, target.ide, target.ide_instance_id or "synthetic-window",
                target.debug_session_id or f"synthetic-session-{number}", 1,
                target.pid or 10000 + number, "/synthetic/disposable-app", "running",
                tuple(CORE_OPERATIONS), target.process_start_id or f"synthetic-start-{uuid.uuid4().hex}",
            )
            self._sessions[session.debug_session_id] = session
            return session

    def set_breakpoints(self, session, resolved_locations):
        with self._lock:
            self._breakpoints[session.debug_session_id] = tuple(resolved_locations)
            result = tuple(BreakpointBindingResult(bp.file, bp.line, self.can_bind_breakpoints) for bp in resolved_locations)
            if self.paused_on_launch and self.can_bind_breakpoints:
                self.simulate_stop(session.debug_session_id)
            return result

    def simulate_stop(self, debug_session_id, *, reason="breakpoint"):
        with self._lock:
            session = self._sessions[debug_session_id]
            number = next(self._stop_ids)
            bindings = self._breakpoints.get(debug_session_id, ())
            bp = bindings[0] if bindings else None
            self._stops[debug_session_id] = StopSnapshot(
                session, f"synthetic-stop-{number}", reason, number,
                bp.file if bp else None, bp.line if bp else None,
            )

    def get_stop(self, session):
        with self._lock:
            current = self._sessions.get(session.debug_session_id)
            if current != session:
                raise AutoDebugError(ErrorDetail(code=ErrorCode.SESSION_STALE, message="synthetic session no longer exists"))
            return self._stops.get(session.debug_session_id)

    def is_paused(self, debug_session_id):
        with self._lock:
            return debug_session_id in self._stops

    def get_stack(self, session, frame_limit):
        return tuple({"frame": f"synthetic-frame-{i}", "file": "/synthetic/demo.py", "line": 7 + i}
                     for i in range(min(frame_limit, 3)))

    def get_variables(self, session, frame_id, selected_names):
        values = {"local_var": "42", "password": "synthetic-private-value"}
        return {name: values.get(name, "unavailable in synthetic fixture") for name in selected_names}

    def step(self, session, kind):
        self.simulate_stop(session.debug_session_id, reason="step")

    def continue_execution(self, session):
        with self._lock:
            self._stops.pop(session.debug_session_id, None)

    def disconnect(self, session):
        with self._lock:
            self.disconnect_calls += 1
            self._stops.pop(session.debug_session_id, None)
            self._sessions.pop(session.debug_session_id, None)
            self._breakpoints.pop(session.debug_session_id, None)
