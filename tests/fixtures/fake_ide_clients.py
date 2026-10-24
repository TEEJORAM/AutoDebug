"""Deterministic in-memory stand-ins for each IDE adapter's injected client.

Each class implements its adapter's client `Protocol` (for example
`autodebug.adapters.cursor.CursorDebugClient`). They prove only AutoDebug's
own translation/wrapping logic; they say nothing about any IDE's real
debugger protocol, none of which has been verified (see
`docs/compatibility-ledger.md`). Used only by tests; nothing in
`src/autodebug` imports this module.
"""

from __future__ import annotations

import itertools

from autodebug.adapters.base import RemoteSessionInfo
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.workflow import BreakpointBindingResult


class FakeIDEClient:
    """Shared fake behaviour; subclasses only set identity details."""

    ide_id = "fake"
    session_prefix = "fake"
    pid_base = 20_000
    executable = "/fake/disposable-test-app"
    source_file = "/fake/disposable-test-app.py"

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
                    message=f"{self.ide_id}.launch_or_attach is not supported by this fake client",
                )
            )
        sequence = next(self._ids)
        remote_session_id = f"{self.session_prefix}-session-{sequence}"
        info = RemoteSessionInfo(
            remote_session_id=remote_session_id,
            pid=target.pid if target.pid is not None else self.pid_base + sequence,
            ide_instance_id=f"{self.session_prefix}-window-{sequence}",
            executable=self.executable,
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
        """Test-only stand-in for a real breakpoint hit."""
        self._paused.add(remote_session_id)

    def is_paused(self, remote_session_id: str) -> bool:
        return remote_session_id in self._paused

    def get_stack(self, remote_session_id, frame_limit):
        return tuple(
            {"frame": f"{self.session_prefix}_frame_{i}", "file": self.source_file, "line": 10 + i}
            for i in range(min(frame_limit, 3))
        )

    def get_variables(self, remote_session_id, frame_id, selected_names):
        fake_values = {"local_var": "42", "password": "hunter2"}
        return {name: fake_values.get(name, "undefined") for name in selected_names}

    def step(self, remote_session_id, kind) -> None:
        pass

    def continue_execution(self, remote_session_id) -> None:
        self._paused.discard(remote_session_id)

    def disconnect(self, remote_session_id) -> None:
        self.disconnect_calls += 1
        self._sessions.pop(remote_session_id, None)


class FakeDebugMCPClient(FakeIDEClient):
    ide_id, session_prefix, pid_base = "vscode", "vscode", 20_000


class FakeCursorDebugClient(FakeIDEClient):
    ide_id, session_prefix, pid_base = "cursor", "cursor", 30_000


class FakeCLionDebugClient(FakeIDEClient):
    ide_id, session_prefix, pid_base = "clion", "clion", 40_000
    source_file = "/fake/disposable-test-app.cpp"


class FakeXcodeDebugClient(FakeIDEClient):
    ide_id, session_prefix, pid_base = "xcode", "xcode", 50_000
    source_file = "/fake/disposable-test-app.swift"


class FakeVisualStudioDebugClient(FakeIDEClient):
    ide_id, session_prefix, pid_base = "visual_studio", "vs", 60_000
    executable = "/fake/disposable-test-app.exe"
    source_file = "/fake/disposable-test-app.cs"
