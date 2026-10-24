"""CLion adapter (T10) — GW-06, IDE-04.

**Tested and implemented independently from VS Code and Cursor — JetBrains'
built-in MCP server and its advertised debugger tools are never assumed to
match DebugMCP's or any generic IDE-extension's capability set**
(`docs/ide-integrations.md` section C: *"Use JetBrains' supported built-in
MCP server and its advertised debugger tools. Do not hardcode `xdebug_*`
names until runtime discovery confirms them... do not assume a generic DAP
socket exposes CLion's active session."*). `CLionAdapter` reuses the exact
same `BaseAdapter` contract `VSCodeAdapter` (T08) and `CursorAdapter` (T09)
implement, but depends on its own, separately-named `CLionDebugClient`
injected abstraction — not `vscode.DebugMCPClient`, not
`cursor.CursorDebugClient` — so nothing here implies CLion shares a remote
protocol, tool inventory, or capability set with either. `RemoteSessionInfo`
(the generic remote-session shape) is shared from `adapters.base`, since it
is AutoDebug's own adapter-agnostic abstraction, not a borrowed concept
from any other adapter.

**Environment finding (read-only, no process spawned, no network contact,
this session):** a comprehensive local search (`/Applications`,
`~/Applications`, JetBrains Toolbox's apps directory, and a Spotlight
`mdfind` query for `CLion.app`) found **no installed CLion application
anywhere on this machine**, despite three residual JetBrains configuration
directories under `~/Library/Application Support/JetBrains/`
(`CLion2024.2`, `CLion2024.3`, `CLion2025.1`) left over from a prior
install. `bundled_plugins.txt` and the installed-plugins directory inside
the most recent config folder (`CLion2025.1`) contain no MCP-related plugin
— only theme/VCS/Copilot plugins. **CLion itself is not currently
installed, so there is no JetBrains MCP server or debugger tool to
enumerate at all** — a more fundamental absence than T08's VS Code finding
(a specific, named extension missing) or T09's Cursor finding (the IDE
installed, zero MCP servers registered): here the IDE application itself
is absent. Per `tasks.md` T10's own acceptance criterion ("`UNSUPPORTED` if
missing"), this is recorded as `UNSUPPORTED`, not `BLOCKED` — see
`docs/compatibility-ledger.md` and `tasks.md` T10 for the full writeup.

With no client attached (the default), every operation fails closed with
`BACKEND_UNAVAILABLE` (`IDE-03-A`), identical to `VSCodeAdapter`'s and
`CursorAdapter`'s convention — this is a real implementation reporting
"backend not reachable," not a stub declaring "not implemented."

**Real-backend authorization remains fully gated.** Nothing in this file
touches `approvals.py`. `ApprovalBroker.verify_approval` still
unconditionally refuses any `backend_kind != "fake"`
(`approvals.FAKE_BACKEND_KIND`), so arming a case against this adapter
through the facade's `authorize_and_arm` path still fails regardless of
this implementation — see `tests/test_clion_adapter.py`'s
`TestAuthorizationGateStillBlocksCLion`.
"""

from __future__ import annotations

import itertools
import time
from typing import Protocol

from autodebug.adapters.base import BaseAdapter, RemoteSessionInfo
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import Breakpoint, SessionRef, TargetRef
from autodebug.workflow import BreakpointBindingResult

__all__ = ["CLionAdapter", "CLionDebugClient", "RemoteSessionInfo"]


class CLionDebugClient(Protocol):
    """The minimal operations `CLionAdapter` needs from a connected
    JetBrains MCP debugger session. This is AutoDebug's own abstraction,
    deliberately separate from `vscode.DebugMCPClient` and
    `cursor.CursorDebugClient` — JetBrains' real remote tool/schema names
    (e.g. whatever its MCP server actually advertises, never hardcoded as
    `xdebug_*` per `docs/ide-integrations.md`) are unverified on this
    machine, since CLion itself is not installed here. A real
    implementation of this `Protocol`, built once CLion is installed, its
    MCP server's advertised debugger tools are runtime-discovered, and
    Autodesk-approved, owns that real translation; this adapter only
    depends on the shape declared here.
    """

    def list_sessions(self) -> tuple[RemoteSessionInfo, ...]: ...

    def start_or_attach(self, target: TargetRef, reviewed_configuration: object) -> RemoteSessionInfo: ...

    def set_breakpoints(
        self, remote_session_id: str, breakpoints: tuple[Breakpoint, ...]
    ) -> tuple[BreakpointBindingResult, ...]: ...

    def is_paused(self, remote_session_id: str) -> bool: ...

    def get_stack(self, remote_session_id: str, frame_limit: int) -> tuple[dict, ...]: ...

    def get_variables(self, remote_session_id: str, frame_id: str, selected_names: tuple[str, ...]) -> dict: ...

    def step(self, remote_session_id: str, kind: str) -> None: ...

    def continue_execution(self, remote_session_id: str) -> None: ...

    def disconnect(self, remote_session_id: str) -> None: ...


class CLionAdapter(BaseAdapter):
    ide_id = "clion"
    supported_os = ("Windows", "Darwin", "Linux")
    proof_task_id = "T10"

    def __init__(self, client: CLionDebugClient | None = None, *, host_id: str = "local-mac") -> None:
        """`client` is `None` by default (no JetBrains MCP connection) —
        every operation then fails closed with `BACKEND_UNAVAILABLE`,
        exactly like `cls()` with no arguments must still work for
        `test_adapters.py`'s enumeration tests."""
        self._client = client
        self._host_id = host_id
        self._sessions: dict[str, SessionRef] = {}
        self._generations: dict[str, int] = {}
        self._generation_counter = itertools.count(1)

    def _require_client(self) -> CLionDebugClient:
        if self._client is None:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.BACKEND_UNAVAILABLE,
                    message="no CLion MCP debug client is attached; no JetBrains MCP server is connected (IDE-03-A)",
                )
            )
        return self._client

    def _generation_for(self, remote_session_id: str, reported: int | None) -> int:
        if reported is not None:
            return reported
        if remote_session_id not in self._generations:
            self._generations[remote_session_id] = next(self._generation_counter)
        return self._generations[remote_session_id]

    def _to_session_ref(self, info: RemoteSessionInfo) -> SessionRef:
        session = SessionRef(
            host_id=self._host_id,
            ide=self.ide_id,
            ide_instance_id=info.ide_instance_id,
            debug_session_id=info.remote_session_id,
            session_generation=self._generation_for(info.remote_session_id, info.generation),
            pid=info.pid,
            executable=info.executable,
            state=info.state,
            capabilities=(),
        )
        self._sessions[session.debug_session_id] = session
        return session

    def list_sessions(self) -> tuple[SessionRef, ...]:
        client = self._require_client()
        return tuple(self._to_session_ref(info) for info in client.list_sessions())

    def launch_or_attach(self, target: TargetRef, reviewed_configuration: object) -> SessionRef:
        client = self._require_client()
        info = client.start_or_attach(target, reviewed_configuration)
        return self._to_session_ref(info)

    def set_breakpoints(
        self, session: SessionRef, resolved_locations: tuple[Breakpoint, ...]
    ) -> tuple[BreakpointBindingResult, ...]:
        client = self._require_client()
        return client.set_breakpoints(session.debug_session_id, resolved_locations)

    def is_paused(self, debug_session_id: str) -> bool:
        client = self._require_client()
        return client.is_paused(debug_session_id)

    def wait_for_stop(self, session: SessionRef, timeout: float) -> None:
        """The single-call, non-cancellable operation named in
        `CORE_OPERATIONS`/`GW-06`. `facade.AutoDebugFacade` does not call
        this directly — it polls `is_paused` itself in a short, cancellable
        loop (`DE-09`) — but this remains available for any other caller
        that wants one blocking call with a bounded timeout."""
        client = self._require_client()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if client.is_paused(session.debug_session_id):
                return
            time.sleep(0.05)
        raise AutoDebugError(
            ErrorDetail(code=ErrorCode.TIMEOUT, message="timed out waiting for a real pause event (DE-01)")
        )

    def get_stack(self, session: SessionRef, frame_limit: int) -> tuple[dict, ...]:
        client = self._require_client()
        return client.get_stack(session.debug_session_id, frame_limit)

    def get_variables(self, session: SessionRef, frame_id: str, selected_names: tuple[str, ...]) -> dict:
        """Returns raw, unredacted values — exactly like `FakeAdapter`/
        `VSCodeAdapter`/`CursorAdapter`. Redaction (`DE-07`) happens
        exactly once, in `evidence.sanitize_observation`, called from
        `facade.autodebug_get_variables`."""
        client = self._require_client()
        return client.get_variables(session.debug_session_id, frame_id, selected_names)

    def step(self, session: SessionRef, kind: str) -> None:
        client = self._require_client()
        client.step(session.debug_session_id, kind)

    def continue_execution(self, session: SessionRef) -> None:
        client = self._require_client()
        client.continue_execution(session.debug_session_id)

    def disconnect(self, session: SessionRef) -> None:
        client = self._require_client()
        client.disconnect(session.debug_session_id)
        self._sessions.pop(session.debug_session_id, None)
