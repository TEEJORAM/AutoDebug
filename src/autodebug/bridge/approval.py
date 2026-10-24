"""Turn the developer's click on Approve in the IDE into an AutoDebug
approval (ide-debug-bridge BR-04).

This is trusted host code, like the demo's local approval in `server.py`: the
dispatcher calls it, never an MCP tool, and it issues an approval only when
the bridge has reported a click for this case's exact plan.
"""

from __future__ import annotations

from autodebug.approvals import BRIDGE_BACKEND_KIND, ApprovalBroker
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.evidence import sanitize_output
from autodebug.models import ApprovalRecord, CasePlan, TargetRef

#: Every operation of the approved plan; the developer approved the whole plan.
BRIDGE_SCOPES = ("op:arm_case", "op:build", "op:step", "op:continue", "op:wait_for_stop", "op:get_stack",
                 "op:get_variables")
MAX_APPROVAL_SECONDS = 3600


def approval_summary(plan: CasePlan) -> dict:
    """What the developer sees in the approval dialog: everything that will run."""
    return sanitize_output({
        "case_id": plan.case_id,
        "workspace_folder": plan.workspace_folder,
        "build_task": plan.build_task,
        "launch_configuration": plan.launch_configuration_name,
        "breakpoints": [f"{bp.file}:{bp.line}" for bp in plan.breakpoints],
        "max_steps": plan.policy.max_steps,
        "max_minutes": round(plan.policy.max_inspection_seconds / 60, 1),
        "reproduction": list(plan.reproduction.steps),
        "report_to_workspace": plan.report_to_workspace,
    })


def issue_bridge_approval(
    broker: ApprovalBroker, *, plan: CasePlan, adapter: object, target: TargetRef, target_identity: str,
) -> ApprovalRecord:
    """Issue an approval for `plan` after the bridge confirmed the click."""
    if getattr(adapter, "backend_kind", None) != BRIDGE_BACKEND_KIND or not getattr(adapter, "approved", False):
        raise AutoDebugError(ErrorDetail(code=ErrorCode.NOT_APPROVED, message="the developer has not approved this plan in the IDE"))
    if plan.target != target or adapter.approved_digest != plan.digest_sha256:
        raise AutoDebugError(ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="the approved plan differs from the staged plan"))
    return broker.issue_approval(
        plan, reviewer=f"{adapter.ide_id} window {adapter.window_id}: developer clicked Approve",
        backend_kind=BRIDGE_BACKEND_KIND, target_identity=target_identity, scope=BRIDGE_SCOPES,
        ttl_seconds=min(plan.policy.max_inspection_seconds, MAX_APPROVAL_SECONDS),
        human_presence_confirmed=True,
    )
