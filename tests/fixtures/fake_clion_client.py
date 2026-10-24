"""A deterministic mock standing in for a real JetBrains CLion MCP
debugger connection (T10).

This fixture implements `autodebug.adapters.clion.CLionDebugClient` — it
proves `CLionAdapter`'s own translation/wrapping logic is correct. It does
**not** prove anything about CLion's real MCP debugger protocol: CLion is
not installed on this development machine at all (confirmed by a
comprehensive local search this session — see `tasks.md` T10), so there is
no real protocol to even describe yet. This fixture is only ever used in
tests, and nothing in `src/autodebug` imports it.
"""

from __future__ import annotations

import itertools

from autodebug.adapters.base import RemoteSessionInfo
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.workflow import BreakpointBindingResult


class FakeCLionDebugClient:
    def __init__(self, *, can_start_or_attach: bool = True, can_bind_breakpoints: bool = True) -> None:
        self.can_start_or_attach = can_start_or_attach
        self.can_bind_breakpoints = can_bind_breakpoints
        self.start_or_attach_calls = 0
        self.disconnect_calls = 0
        self._sessions: dict[str, RemoteSessionInfo] = {}
        self._paused: set[str] = set()
        self._ids = itertools.count(1)

    def list_sessions(self) -> tuple[RemoteSessionInfo, ...]:
        return tuple(self._sessions.values())

    def start_or_attach(self, target, reviewed_configuration) -> RemoteSessionInfo:
        self.start_or_attach_calls += 1
        if not self.can_start_or_attach:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.CAPABILITY_UNSUPPORTED,
                    message="clion.launch_or_attach is not supported by this fake CLion client",
                )
            )
        sequence = next(self._ids)
        remote_session_id = f"clion-session-{sequence}"
        info = RemoteSessionInfo(
            remote_session_id=remote_session_id,
            pid=target.pid if target.pid is not None else 40_000 + sequence,
            ide_instance_id=f"clion-window-{sequence}",
            executable="/fake/disposable-test-app",
            state="running",
            generation=None,
        )
        self._sessions[remote_session_id] = info
        return info

    def set_breakpoints(self, remote_session_id, breakpoints) -> tuple[BreakpointBindingResult, ...]:
        return tuple(
            BreakpointBindingResult(
                file=bp.file,
                line=bp.line,
                bound=self.can_bind_breakpoints,
                reason="" if self.can_bind_breakpoints else "fake: line not reachable",
            )
            for bp in breakpoints
        )

    def simulate_stop(self, remote_session_id: str) -> None:
        """Test-only hook standing in for a real breakpoint hit. Nothing in
        `src/autodebug` calls this."""
        self._paused.add(remote_session_id)

    def is_paused(self, remote_session_id: str) -> bool:
        return remote_session_id in self._paused

    def get_stack(self, remote_session_id, frame_limit):
        return tuple(
            {"frame": f"clion_frame_{i}", "file": "/fake/disposable-test-app.cpp", "line": 10 + i}
            for i in range(min(frame_limit, 3))
        )

    def get_variables(self, remote_session_id, frame_id, selected_names):
        fake_values = {"local_var": "42", "password": "hunter2"}
        return {name: fake_values.get(name, "undefined") for name in selected_names}

    def step(self, remote_session_id, kind) -> None:
        return None

    def continue_execution(self, remote_session_id) -> None:
        self._paused.discard(remote_session_id)

    def disconnect(self, remote_session_id) -> None:
        self.disconnect_calls += 1
        self._sessions.pop(remote_session_id, None)
