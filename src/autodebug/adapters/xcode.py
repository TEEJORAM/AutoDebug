"""Xcode adapter (T11) — GW-06, IDE-02, IDE-04.

**Tested and implemented independently from VS Code, Cursor, and CLion —
Apple's `xcrun mcpbridge` facility is never assumed to match any other
IDE's MCP tool inventory or capability set** (`docs/ide-integrations.md`
section E: *"Do not claim all Xcode versions expose the debugger tools;
enumerate advertised MCP tools and probe a disposable example project.
LLDB outside Xcode is not the same thing as controlling Xcode's active
native debug session."*). `XcodeAdapter` reuses the exact same `BaseAdapter`
contract `VSCodeAdapter` (T08), `CursorAdapter` (T09), and `CLionAdapter`
(T10) implement, but depends on its own, separately-named `XcodeDebugClient`
injected abstraction — not any of the other three — so nothing here implies
Xcode shares a remote protocol, tool inventory, or capability set with any
other adapter. `RemoteSessionInfo` (the generic remote-session shape) is
shared from `adapters.base`, since it is AutoDebug's own adapter-agnostic
abstraction, not a borrowed concept from any other adapter.

**Environment finding (read-only, no process spawned beyond `xcode-select`/
`xcodebuild -version`/`xcrun -f`, no network contact, this session):**
Xcode **is installed** on this machine — `xcode-select -p` resolves to
`/Applications/Xcode.app/Contents/Developer`, and `xcodebuild -version`
reports `Xcode 26.0.1 (Build 17A400)`. However, `xcrun mcpbridge` **is not
found** — `xcrun -f mcpbridge` fails with "unable to find utility
'mcpbridge', not a developer tool or in PATH," and a recursive filesystem
search of the entire `/Applications/Xcode.app` bundle for `mcpbridge`
returns zero matches. **The Xcode application is present; the specific
`mcpbridge` MCP facility this adapter depends on is not** — closer to T08's
VS Code finding (IDE installed, specific named tool/extension absent) than
T10's CLion finding (the IDE application itself absent). Per `IDE-04-A`
("the installed Xcode MCP bridge exposes no native debugger control ->
PARTIAL or UNSUPPORTED, with a tool-inventory evidence note, not PASS"),
and since the tool is not merely limited but entirely absent, this is
recorded as `UNSUPPORTED`, not `PASS` or `PARTIAL` — see
`docs/compatibility-ledger.md` and `tasks.md` T11 for the full writeup.
**This reflects this Xcode installation/version on this machine only — it
is not a claim that Xcode/`xcrun mcpbridge` can never expose native
debugger control in any version.**

With no client attached (the default), every operation fails closed with
`BACKEND_UNAVAILABLE` (`IDE-03-A`), identical to the other three real
adapters' convention — this is a real implementation reporting "backend
not reachable," not a stub declaring "not implemented."

**Real-backend authorization remains fully gated.** Nothing in this file
touches `approvals.py`. `ApprovalBroker.verify_approval` still
unconditionally refuses any `backend_kind != "fake"`
(`approvals.FAKE_BACKEND_KIND`), so arming a case against this adapter
through the facade's `authorize_and_arm` path still fails regardless of
this implementation — see `tests/test_xcode_adapter.py`'s
`TestAuthorizationGateStillBlocksXcode`.
"""

from __future__ import annotations

import itertools
import time
from typing import Protocol

from autodebug.adapters.base import BaseAdapter, RemoteSessionInfo
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import Breakpoint, SessionRef, TargetRef
from autodebug.workflow import BreakpointBindingResult

__all__ = ["XcodeAdapter", "XcodeDebugClient", "RemoteSessionInfo"]


class XcodeDebugClient(Protocol):
    """The minimal operations `XcodeAdapter` needs from a connected
    `xcrun mcpbridge` debugger session. This is AutoDebug's own
    abstraction, deliberately separate from `vscode.DebugMCPClient`,
    `cursor.CursorDebugClient`, and `clion.CLionDebugClient` — Apple's real
    remote tool/schema names (whatever `mcpbridge` actually advertises, if
    and when it exists on an Xcode installation) are unverified on this
    machine, since `mcpbridge` itself was not found here. A real
    implementation of this `Protocol`, built once `mcpbridge` is present,
    its advertised debugger tools are runtime-discovered, and
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


class XcodeAdapter(BaseAdapter):
    ide_id = "xcode"
    supported_os = ("Darwin",)
    proof_task_id = "T11"

    def __init__(self, client: XcodeDebugClient | None = None, *, host_id: str = "local-mac") -> None:
        """`client` is `None` by default (no `mcpbridge` connection) —
        every operation then fails closed with `BACKEND_UNAVAILABLE`,
        exactly like `cls()` with no arguments must still work for
        `test_adapters.py`'s enumeration tests."""
        self._client = client
        self._host_id = host_id
        self._sessions: dict[str, SessionRef] = {}
        self._generations: dict[str, int] = {}
        self._generation_counter = itertools.count(1)

    def _require_client(self) -> XcodeDebugClient:
        if self._client is None:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.BACKEND_UNAVAILABLE,
                    message="no Xcode mcpbridge client is attached; mcpbridge is not connected (IDE-03-A)",
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
        `VSCodeAdapter`/`CursorAdapter`/`CLionAdapter`. Redaction (`DE-07`)
        happens exactly once, in `evidence.sanitize_observation`, called
        from `facade.autodebug_get_variables`."""
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
