"""Router (T03) — GW-04: native session ownership, and GW-06: AI-initiated
launch/attach scenarios.

The router makes exactly one decision per call: reuse an existing session
(GW-06-C), attach to a running process (GW-06-B), launch a new one
(GW-06-A), or decline because the adapter can't do what's asked (GW-06-D /
GW-04-A). It never launches a second debugger behind an existing one's back,
and it never silently defaults to "whichever adapter/session seems closest."
"""

from __future__ import annotations

from collections.abc import Callable

from autodebug.adapters.base import BaseAdapter, CapabilityReport
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import CapabilityState, SessionRef, TargetRef
from autodebug.sessions import SessionRegistry


class Router:
    def __init__(self, registry: SessionRegistry) -> None:
        self._registry = registry

    def arm_target(
        self,
        adapter: BaseAdapter,
        capability_report: CapabilityReport,
        target: TargetRef,
        reviewed_configuration: object,
        *,
        process_running: bool,
        launch: Callable[[TargetRef, object], SessionRef] | None = None,
    ) -> SessionRef:
        """Resolve `target` to a live session, per GW-06's four scenarios.

        `process_running` reflects whether the target process is already
        running (information the caller — eventually the case workflow —
        must supply; the router does not itself detect running processes).
        """
        if adapter.ide_id != target.ide:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.TARGET_MISMATCH,
                    message=f"adapter '{adapter.ide_id}' does not match target IDE '{target.ide}'",
                )
            )

        # GW-06-C / GW-04: an existing session always wins — never launch a
        # second, duplicate debugger just because one was requested again.
        existing = self._registry.resolve(target)
        if existing is not None:
            return existing

        # GW-06-A / GW-06-B / GW-06-D (and GW-04-A's "only headless DAP
        # available" case): no session yet, so launching or attaching
        # requires the adapter to actually support it.
        if capability_report.operations.get("launch_or_attach") is not CapabilityState.AVAILABLE:
            action = "attach to the running process" if process_running else "launch the application"
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.CAPABILITY_UNSUPPORTED,
                    message=(
                        f"{adapter.ide_id} cannot {action} through its native integration; "
                        "the developer must perform this step manually in the IDE"
                    ),
                )
            )

        session = (launch or adapter.launch_or_attach)(target, reviewed_configuration)
        self._registry.register(session)
        return session
