"""Approval broker prototype (RP-04, RP-05, DE-09).

Binds approvals to a plan digest, target identity, scope and expiry, with
revocation and one-time tokens. Tested only against the fake backend.

SECURITY GATE: `verify_approval` accepts only the backend kinds in
`APPROVED_BACKEND_KINDS`. `"fake"` is the synthetic demo. `"vscode-bridge"`
was approved by the developer on 2026-10-24 (ide-debug-bridge, decision 1):
its approvals are issued only after the AutoDebug Bridge reports a click on
Approve in the IDE's modal dialog, and the bridge enforces them again. No MCP
tool, argument or environment variable can approve or extend this set.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from autodebug.adapters.base import BaseAdapter, CapabilityReport
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import ApprovalRecord, CasePlan, SessionRef, TargetRef
from autodebug.plans import compute_plan_digest, validate_case_plan
from autodebug.router import Router

#: The only backend kind a fake/simulated approval is ever valid for
#: (RP-05, tasks.md T05 security gate). Any other value is refused by
#: `verify_approval` regardless of how well-formed the approval otherwise is.
FAKE_BACKEND_KIND = "fake"
#: The AutoDebug Bridge in VS Code or Cursor (ide-debug-bridge BR-04).
BRIDGE_BACKEND_KIND = "vscode-bridge"
#: Hardcoded on purpose: one reviewed line per approved backend, nothing
#: configurable (security-gate-closure-proposal.md section 4).
APPROVED_BACKEND_KINDS = frozenset({FAKE_BACKEND_KIND, BRIDGE_BACKEND_KIND})


def reject_prohibited_target(host_id: str) -> None:
    """DE-07: deny remote/production-looking hosts before any debugger call.

    A naming heuristic, not verified machine identity: `host_id` must start with
    "local" and must not contain "prod" or "remote"."""
    lowered = host_id.lower()
    if "prod" in lowered or "remote" in lowered:
        raise AutoDebugError(
            ErrorDetail(
                code=ErrorCode.PERMISSION_DENIED,
                message=f"target host '{host_id}' looks like a remote/production target; denied by default (DE-07)",
            )
        )
    if not lowered.startswith("local"):
        raise AutoDebugError(
            ErrorDetail(
                code=ErrorCode.PERMISSION_DENIED,
                message=f"target host '{host_id}' is not recognized as local; remote targets are denied by default (DE-07)",
            )
        )


@dataclass
class ApprovalBroker:
    """A trusted local approval broker prototype.

    `now` and `make_token` are injected on purpose: this keeps tests fully
    deterministic, and it forces every construction site to make an explicit
    choice about token generation rather than silently defaulting to
    something that looks secure but isn't reviewed.
    """

    now: Callable[[], float]
    make_token: Callable[[], str]
    _issued: dict[str, ApprovalRecord] = field(default_factory=dict)
    _revoked_tokens: set[str] = field(default_factory=set)
    _closed_cases: set[str] = field(default_factory=set)
    _deadlines: dict[str, float] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def issue_approval(
        self,
        plan: CasePlan,
        *,
        reviewer: str,
        backend_kind: str,
        target_identity: str,
        scope: tuple[str, ...],
        ttl_seconds: float,
        human_presence_confirmed: bool,
    ) -> ApprovalRecord:
        """Issue an approval bound to `plan`'s digest, a target identity, a
        scope and an expiry. The caller must assert `human_presence_confirmed`;
        this prototype cannot verify that assertion (see module docstring)."""
        reject_prohibited_target(plan.target.host_id)
        validate_case_plan(plan)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (float, int)) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("approval lifetime must be positive and finite")
        if not human_presence_confirmed:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.NOT_APPROVED,
                    message="no human-presence confirmation asserted; cannot issue an approval",
                )
            )
        if plan.digest_sha256 is None:
            raise AutoDebugError(
                ErrorDetail(code=ErrorCode.NOT_APPROVED, message="plan has no digest; stage it first")
            )
        if plan.digest_sha256 != compute_plan_digest(plan):
            raise AutoDebugError(ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="staged plan digest is stale"))
        issued_at = self.now()
        if not math.isfinite(issued_at) or not math.isfinite(issued_at + ttl_seconds):
            raise ValueError("approval clock and expiration must be finite")
        token = self.make_token()
        record = ApprovalRecord(
            case_id=plan.case_id,
            plan_digest=plan.digest_sha256,
            reviewer=reviewer,
            expiration=str(issued_at + ttl_seconds),
            scope=(f"backend:{backend_kind}", f"target:{target_identity}") + tuple(scope),
            token=token,
            revoked=False,
        )
        with self._lock:
            if not isinstance(token, str) or not token or token in self._issued:
                raise ValueError("approval token must be nonempty and unique")
            if plan.case_id in self._closed_cases:
                raise AutoDebugError(ErrorDetail(code=ErrorCode.CANCELLED, message="case approvals are closed"))
            self._issued[token] = record
            self._deadlines[token] = time.monotonic() + ttl_seconds
        return record

    def revoke(self, token: str) -> None:
        """DE-09 (authorization scope only): revoke a single approval so it
        can never be used again, regardless of expiry. Idempotent — revoking
        an already-revoked or unknown token is not an error."""
        with self._lock:
            self._revoked_tokens.add(token)
            if token in self._issued:
                self._issued[token] = replace(self._issued[token], revoked=True)

    def revoke_for_case(self, case_id: str) -> None:
        """DE-09: cancellation revokes the case's approval/permission
        record (authorization only; evidence and in-flight calls are handled
        by the facade)."""
        with self._lock:
            self._closed_cases.add(case_id)
            for token, record in list(self._issued.items()):
                if record.case_id == case_id:
                    self.revoke(token)

    def verify_approval(
        self,
        record: ApprovalRecord,
        *,
        plan: CasePlan,
        backend_kind: str,
        target_identity: str,
        required_scope: str,
    ) -> None:
        """RP-04/RP-05 enforcement. `record` is untrusted caller-supplied
        input (it may be entirely forged) — every check is against this
        broker's own issuance ledger, never against fields on `record`
        itself, so a self-constructed `ApprovalRecord` with plausible-looking
        fields cannot pass."""
        reject_prohibited_target(plan.target.host_id)
        with self._lock:
            issued = self._issued.get(record.token)
            revoked = record.token in self._revoked_tokens
        if issued is None:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.NOT_APPROVED,
                    message="no matching approval record was issued by this broker",
                )
            )
        if issued.revoked or revoked:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.CANCELLED, message="approval has been revoked"))
        if issued.case_id != plan.case_id:
            raise AutoDebugError(
                ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="approval belongs to another case")
            )
        if (
            issued.case_id != record.case_id
            or issued.plan_digest != record.plan_digest
            or issued.scope != record.scope
            or issued.reviewer != record.reviewer
            or issued.expiration != record.expiration
            or issued.revoked != record.revoked
        ):
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.NOT_APPROVED,
                    message="presented approval does not match the issued record",
                )
            )
        if self.now() >= float(issued.expiration) or time.monotonic() >= self._deadlines[record.token]:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.APPROVAL_EXPIRED, message="approval has expired"))
        if plan.digest_sha256 != issued.plan_digest or compute_plan_digest(plan) != issued.plan_digest:
            raise AutoDebugError(
                ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="plan digest does not match the approved digest")
            )
        if f"backend:{backend_kind}" not in issued.scope or f"target:{target_identity}" not in issued.scope:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.TARGET_MISMATCH,
                    message="approval is not bound to this backend/target (RP-05-C)",
                )
            )
        if backend_kind not in APPROVED_BACKEND_KINDS:
            # Defense in depth: even a perfectly scope-matched approval can
            # never authorize a backend outside the reviewed allowlist. This
            # check is independent of the scope check above.
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=(
                        "real-backend authorization is disabled pending a dedicated security "
                        "review of the trusted human-presence mechanism (see tasks.md T05 security gate)"
                    ),
                )
            )
        if required_scope not in issued.scope:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"approval scope does not include '{required_scope}'",
                )
            )


def authorize_and_arm(
    broker: ApprovalBroker,
    approval: ApprovalRecord,
    *,
    plan: CasePlan,
    target_identity: str,
    required_scope: str,
    router: Router,
    adapter: BaseAdapter,
    capability_report: CapabilityReport,
    target: TargetRef,
    reviewed_configuration: object,
    process_running: bool,
    launch: Callable[[TargetRef, object], SessionRef] | None = None,
) -> SessionRef:
    """The only approval-gated path to `Router.arm_target`.

    Verifies the approval first, then that the launch configuration and
    running/launch scenario match the reviewed plan. Backend identity comes
    from `adapter.backend_kind`, so the approval check and the armed adapter cannot
    diverge. Agent-reachable code must never call `Router.arm_target` directly."""
    if target != plan.target:
        raise AutoDebugError(ErrorDetail(code=ErrorCode.TARGET_MISMATCH, message="routed target differs from plan"))
    broker.verify_approval(
        approval,
        plan=plan,
        backend_kind=adapter.backend_kind,
        target_identity=target_identity,
        required_scope=required_scope,
    )
    if reviewed_configuration not in (None, {}) and reviewed_configuration != dict(plan.launch_configuration):
        raise AutoDebugError(ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="launch configuration differs from the reviewed plan"))
    if (reviewed_configuration is None or reviewed_configuration == {}) and plan.launch_configuration:
        raise AutoDebugError(ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="reviewed launch configuration is missing"))
    if process_running != plan.process_running:
        raise AutoDebugError(ErrorDetail(code=ErrorCode.PLAN_CHANGED, message="launch/attach scenario differs from the reviewed plan"))
    return router.arm_target(
        adapter, capability_report, target, reviewed_configuration, process_running=process_running, launch=launch
    )
