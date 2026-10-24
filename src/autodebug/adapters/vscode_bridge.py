"""Real VS Code / Cursor debugging through the AutoDebug Bridge extension
(ide-debug-bridge BR-02, BR-03, BR-06, BR-07, BR-08).

One adapter instance serves one case: it is bound to that case's schema 0.3
plan, finds the IDE window that has the plan's workspace open, and carries
the approval ID the bridge issued when the developer clicked Approve. The
bridge enforces that approval on its side too; AutoDebug's own checks
(digest, scopes, budgets, redaction) still run in the facade.
"""

from __future__ import annotations

import base64
import binascii
import itertools
from collections.abc import Callable
from pathlib import Path

from autodebug.adapters.base import CORE_OPERATIONS, BaseAdapter, CapabilityReport
from autodebug.approvals import BRIDGE_BACKEND_KIND
from autodebug.bridge.client import BRIDGE_IDES, BridgeConnection, ConnectionInfo, discover, select
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import BRIDGE_SCHEMA_VERSION, CapabilityState, CasePlan, SessionRef, StopSnapshot, TargetRef
from autodebug.plans import resolve_inputs
from autodebug.workflow import BreakpointBindingResult

BACKEND_KIND = BRIDGE_BACKEND_KIND
#: Extra operation the facade's stop verification needs.
_OPERATIONS = (*CORE_OPERATIONS, "get_stop")
_STEP_OPS = {"step_over": "next", "step_in": "stepIn", "step_out": "stepOut"}
_MAX_FILE_BYTES = 5 * 1024 * 1024


def _fail(code: ErrorCode, message: str) -> AutoDebugError:
    return AutoDebugError(ErrorDetail(code=code, message=message, recoverable=True))


class VSCodeBridgeAdapter(BaseAdapter):
    """`ide_id` is the IDE the case targets (`vscode` or `cursor`);
    `backend_kind` is what approvals are bound to."""

    backend_kind = BACKEND_KIND
    supported_os = ("Windows", "Darwin", "Linux")
    proof_task_id = "ide-debug-bridge B9"
    supports_bounded_operations = True

    def __init__(
        self, ide: str, bridges_folder: Path, *,
        connect: Callable[[ConnectionInfo], BridgeConnection] = BridgeConnection,
    ) -> None:
        if ide not in BRIDGE_IDES:
            raise ValueError(f"the bridge supports {', '.join(BRIDGE_IDES)}, not {ide!r}")
        self.ide_id = ide
        self._folder = Path(bridges_folder)
        self._connect = connect
        self._connection: BridgeConnection | None = None
        self._plan: CasePlan | None = None
        self._approval_id: str | None = None
        self._approved_digest: str | None = None
        self._sessions: dict[str, SessionRef] = {}
        self._session_numbers = itertools.count(1)

    # -- capability -------------------------------------------------------

    def probe_capabilities(self, backend=None, host_os=None) -> CapabilityReport:
        if backend is not None:
            return super().probe_capabilities(backend, host_os)
        import platform

        return CapabilityReport(
            ide=self.ide_id, host_os=host_os or platform.system(), state=CapabilityState.AVAILABLE,
            ide_version=None, backend_version=None,
            reason="AutoDebug Bridge; the IDE window is found when the plan is resolved",
            operations={op: CapabilityState.AVAILABLE for op in _OPERATIONS},
        )

    # -- plan and approval (used by the facade's approval tools) ------------

    @property
    def approved(self) -> bool:
        """Whether the bridge reported the developer's Approve click."""
        return self._approval_id is not None

    @property
    def approved_digest(self) -> str | None:
        return self._approved_digest

    @property
    def window_id(self) -> str | None:
        return self._connection.info.window_id if self._connection else None

    def _bridge(self) -> BridgeConnection:
        if self._connection is None:
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "no plan has been resolved with an AutoDebug Bridge yet")
        return self._connection

    def _timeout(self) -> float:
        return self._plan.policy.max_operation_seconds if self._plan else 5.0

    def _request(self, op: str, args: dict | None = None, *, approved: bool = True) -> dict:
        payload = dict(args or {})
        if approved:
            if self._approval_id is None:
                raise _fail(ErrorCode.NOT_APPROVED, "the developer has not approved this plan in the IDE")
            payload["approval_id"] = self._approval_id
        return self._bridge().request(op, payload, timeout=self._timeout())

    def resolve(self, plan: CasePlan) -> tuple[tuple[str, str], ...]:
        """BR-02/BR-03 — find the IDE window for `plan`, read what the plan
        names from it, and return the resolved-input hashes."""
        if plan.schema_version != BRIDGE_SCHEMA_VERSION or plan.target.ide != self.ide_id:
            raise _fail(ErrorCode.TARGET_MISMATCH, f"the bridge needs a schema {BRIDGE_SCHEMA_VERSION} plan for {self.ide_id}")
        info = select(discover(self._folder), plan.workspace_folder, self.ide_id)
        if self._connection is not None:
            self._connection.close()
        self._connection = self._connect(info)
        self._plan = plan
        files = sorted({bp.file for bp in plan.breakpoints})
        result = self._request("resolve_plan", {
            "workspace_folder": plan.workspace_folder, "launch_configuration_name": plan.launch_configuration_name,
            "build_task": plan.build_task, "files": files,
        }, approved=False)
        encoded = result.get("files")
        if type(encoded) is not dict or set(encoded) != set(files) or any(type(v) is not str for v in encoded.values()):
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge did not return every breakpoint file")
        try:
            contents = {name: base64.b64decode(value, validate=True) for name, value in encoded.items()}
        except (binascii.Error, ValueError):
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge returned unreadable file contents") from None
        if any(len(data) > _MAX_FILE_BYTES for data in contents.values()):
            raise _fail(ErrorCode.POLICY_LIMIT, "a breakpoint file is larger than 5 MiB")
        launch, task = result.get("launch"), result.get("task")
        try:
            return resolve_inputs(plan, launch=launch if type(launch) is dict else {},
                                  task=task if type(task) is dict else None, files=contents)
        except ValueError as exc:
            raise _fail(ErrorCode.PLAN_CHANGED, str(exc)) from None

    def bind(self, plan: CasePlan) -> None:
        """Use the bound (digest-final) plan from now on."""
        self._plan = plan

    def request_approval(self, case_id: str, summary: dict) -> str:
        """BR-04 — ask the bridge to show the approval dialog."""
        plan = self._plan
        result = self._request("request_approval", {
            "case_id": case_id, "digest": plan.digest_sha256, "summary": summary,
            "expires_in_seconds": min(plan.policy.max_inspection_seconds, 3600),
            # What the bridge shows in its dialog and then enforces.
            "plan": {
                "workspace_folder": plan.workspace_folder, "launch_configuration_name": plan.launch_configuration_name,
                "build_task": plan.build_task, "files": sorted({bp.file for bp in plan.breakpoints}),
                "breakpoints": [{"file": bp.file, "line": bp.line} for bp in plan.breakpoints],
                "max_steps": plan.policy.max_steps, "report_to_workspace": plan.report_to_workspace,
            },
        }, approved=False)
        request_id = result.get("request_id")
        if type(request_id) is not str or not request_id:
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge did not open an approval request")
        return request_id

    def approval_status(self, request_id: str) -> str:
        """`pending`, `approved`, `denied` or `expired`. Remembers the
        bridge's approval ID once approved."""
        result = self._request("approval_status", {"request_id": request_id}, approved=False)
        status = result.get("status")
        if status not in ("pending", "approved", "denied", "expired"):
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge reported an unknown approval status")
        if status == "approved":
            approval_id = result.get("approval_id")
            if type(approval_id) is not str or not approval_id:
                raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge approved without an approval ID")
            self._approval_id = approval_id
            self._approved_digest = self._plan.digest_sha256
        return status

    # -- build (BR-05) ----------------------------------------------------

    def start_build(self) -> None:
        self._request("build_start")

    def build_status(self) -> tuple[str, int | None, tuple[str, ...]]:
        """(`running` | `succeeded` | `failed`, exit code, last output lines)."""
        result = self._request("build_status")
        status, code, lines = result.get("status"), result.get("exit_code"), result.get("output_tail")
        if status not in ("running", "succeeded", "failed"):
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge reported an unknown build status")
        tail = tuple(str(line)[:500] for line in lines[-50:]) if type(lines) is list else ()
        return status, code if type(code) is int else None, tail

    # -- debugger operations ----------------------------------------------

    def list_sessions(self) -> tuple[SessionRef, ...]:
        return tuple(self._sessions.values())

    def launch_or_attach(self, target: TargetRef, reviewed_configuration: object) -> SessionRef:
        """BR-06 — the bridge adds the plan's breakpoints, then starts the
        named launch configuration. Attaching is never offered."""
        plan = self._plan
        if plan is None or target != plan.target:
            raise _fail(ErrorCode.TARGET_MISMATCH, "launch target differs from the resolved plan")
        result = self._request("launch", {
            "breakpoints": [{"file": bp.file, "line": bp.line} for bp in plan.breakpoints],
        })
        session_id, pid, start_id = result.get("debug_session_id"), result.get("pid"), result.get("process_start_id")
        if type(session_id) is not str or not session_id or type(pid) is not int or type(start_id) is not str or not start_id:
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge did not report the new debug session's identity")
        session = SessionRef(
            host_id=target.host_id, ide=self.ide_id, ide_instance_id=self._bridge().info.window_id,
            debug_session_id=session_id, session_generation=next(self._session_numbers), pid=pid,
            executable=str(result.get("executable") or "")[:200], state="running",
            capabilities=_OPERATIONS, process_start_id=start_id,
        )
        self._sessions[session_id] = session
        return session

    def _check_session(self, session: SessionRef) -> None:
        if self._sessions.get(session.debug_session_id) != session:
            raise _fail(ErrorCode.SESSION_STALE, "this debug session is not the one AutoDebug started")

    def set_breakpoints(self, session: SessionRef, resolved_locations) -> tuple[BreakpointBindingResult, ...]:
        self._check_session(session)
        results = self._request("breakpoints").get("results")
        if type(results) is not list:
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge did not report breakpoint binding")
        reported = {(r.get("file"), r.get("line")): r for r in results if type(r) is dict}
        return tuple(
            BreakpointBindingResult(bp.file, bp.line, reported.get((bp.file, bp.line), {}).get("bound") is True,
                                    str(reported.get((bp.file, bp.line), {}).get("message") or "")[:500])
            for bp in resolved_locations
        )

    def get_stop(self, session: SessionRef) -> StopSnapshot | None:
        self._check_session(session)
        state = self._request("stop_state")
        if state.get("state") == "running":
            return None
        if state.get("state") == "ended":
            raise _fail(ErrorCode.SESSION_STALE, "the program has exited and its debug session ended")
        location, planned = state.get("location"), state.get("planned_breakpoint")
        reason = state.get("reason") if type(state.get("reason")) is str else "unknown"
        if reason == "breakpoint" and type(planned) is not dict:
            reason = "breakpoint not in the plan"
        where = (f"{location.get('file')}:{location.get('line')}" if type(location) is dict else None)
        return StopSnapshot(
            session=session, stop_id=state.get("stop_id"), reason=reason, frame_generation=state.get("generation"),
            breakpoint_file=planned.get("file") if type(planned) is dict else None,
            breakpoint_line=planned.get("line") if type(planned) is dict else None,
            location=where,
        )

    def is_paused(self, debug_session_id: str) -> bool:
        session = self._sessions.get(debug_session_id)
        return session is not None and self.get_stop(session) is not None

    def get_stack(self, session: SessionRef, frame_limit: int) -> tuple[dict, ...]:
        self._check_session(session)
        frames = self._request("stack", {"levels": frame_limit}).get("frames")
        if type(frames) is not list:
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge did not return a stack")
        return tuple(
            {"frame": str(f.get("frame")), "name": str(f.get("name")), "file": str(f.get("file")), "line": f.get("line")}
            for f in frames[:frame_limit] if type(f) is dict
        )

    def get_variables(self, session: SessionRef, frame_id: str, selected_names: tuple[str, ...]) -> dict:
        self._check_session(session)
        values = self._request("variables", {"frame_id": frame_id, "names": list(selected_names)}).get("variables")
        if type(values) is not dict:
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge did not return variables")
        return {name: str(values[name]) for name in selected_names if name in values}

    def list_variables(self, session: SessionRef, frame_id: str) -> tuple[dict, ...]:
        """BR-07 — names and types only, never values."""
        self._check_session(session)
        names = self._request("variables", {"frame_id": frame_id, "names": None}).get("names")
        if type(names) is not list:
            raise _fail(ErrorCode.BACKEND_UNAVAILABLE, "the bridge did not return variable names")
        return tuple({"name": str(n.get("name")), "type": str(n.get("type") or "")}
                     for n in names[:200] if type(n) is dict)

    def step(self, session: SessionRef, kind: str) -> None:
        self._check_session(session)
        if kind not in _STEP_OPS:
            raise _fail(ErrorCode.CAPABILITY_UNSUPPORTED, "unsupported step kind")
        self._request("step", {"kind": _STEP_OPS[kind]})

    def continue_execution(self, session: SessionRef) -> None:
        self._check_session(session)
        self._request("continue")

    def disconnect(self, session: SessionRef) -> None:
        """BR-08 — end the debug session and remove AutoDebug's breakpoints."""
        self._sessions.pop(session.debug_session_id, None)
        self.close()

    def close(self) -> None:
        """End anything still approved in the bridge, then drop the connection.
        Safe to call more than once."""
        try:
            if self._approval_id is not None and self._connection is not None:
                self._request("end")
        except AutoDebugError:
            pass  # The bridge also ends sessions when the approval expires.
        finally:
            self._approval_id = None
            if self._connection is not None:
                self._connection.close()
                self._connection = None
