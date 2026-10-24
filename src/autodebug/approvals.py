"""Human-approval broker — design and prototype (T05) — RP-04, RP-05, DE-09.

**SECURITY GATE — read before touching this module.** This is a prototype of
the *mechanism* (digest/target/expiry/scope binding, revocation, one-time
tokens) tested only against the fake debugger backend. It is explicitly NOT
the OS-enforced, trusted-local-user-presence mechanism `design.md`'s threat
model requires before any real debugger is touched:

    "A boolean approved=true from an agent or a file editable by the same
    unrestricted agent is not a security boundary."

`issue_approval()`'s `human_presence_confirmed` flag is a design placeholder
for where that real OS-level check would plug in — this code has no way to
verify a human actually clicked anything, and `test_approvals.py` includes a
test that proves exactly that, rather than hiding it. `verify_approval()`
additionally refuses any `backend_kind` other than `"fake"`, so even a
perfectly-formed, correctly-issued approval can never authorize a real
adapter operation until a dedicated security review approves real-backend
enablement (tracked as an explicit, unresolved blocker in `tasks.md` T05).

There is no MCP tool anywhere in this codebase that calls `issue_approval()`
— that entrypoint does not exist until T07, and when it does, it must be
reachable only from a separate trusted local process, never from the AI
agent's own tool-calling path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import threading
import time
from typing import Callable

from autodebug.adapters.base import BaseAdapter, CapabilityReport
from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import ApprovalRecord, CasePlan, SessionRef, TargetRef
from autodebug.plans import compute_plan_digest, validate_case_plan
from autodebug.router import Router

#: The only backend kind a fake/simulated approval is ever valid for
#: (RP-05, tasks.md T05 security gate). Any other value is refused by
#: `verify_approval` regardless of how well-formed the approval otherwise is.
FAKE_BACKEND_KIND = "fake"


def reject_prohibited_target(host_id: str) -> None:
    """DE-07 (authorization scope, assigned to T05): deny a prohibited
    (remote/production-looking) target before any debugger call, as a
    defense-in-depth check independent of the `backend_kind` gate above.

    This is a naming-convention heuristic — `host_id` must look like a local
    developer machine (the "local-..." convention used throughout
    docs/architecture.md), and must not contain "prod"/"remote" markers. It
    is NOT a verified machine-identity check. A real implementation needs a
    reviewed local-machine-identity policy (e.g. tied to enterprise device
    enrollment); this exists so DE-07's *mechanism* has a concrete, testable
    home now, not because the heuristic itself is considered sufficient.
    """
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


@dataclass(frozen=True)
class ApprovalRequest:
    """Everything a trusted local broker must show the developer before
    issuing an approval (docs/security.md "Developer approval must cover").
    This is a *display* contract, not a decision — issuance only follows a
    real human-presence check that this prototype cannot perform."""

    case_id: str
    plan_digest: str
    target_summary: str
    script_or_steps_summary: str
    allowed_operations: tuple[str, ...]
    max_steps: int
    max_inspection_seconds: int


@dataclass
class ApprovalBroker:
    """A trusted local approval broker prototype (T05).

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
        """Issue an approval bound to `plan`'s exact digest, a target
        identity, a scope, and an expiration.

        `human_presence_confirmed` must be explicitly `True` — this
        prototype cannot itself perform that check, so it refuses to issue
        anything without the caller asserting it happened. It CANNOT verify
        the assertion is true; that is precisely the unresolved security
        gate (see module docstring and `test_approvals.py`).
        """
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
                issued = self._issued[token]
                self._issued[token] = ApprovalRecord(
                    case_id=issued.case_id,
                    plan_digest=issued.plan_digest,
                    reviewer=issued.reviewer,
                    expiration=issued.expiration,
                    scope=issued.scope,
                    token=issued.token,
                    revoked=True,
                )

    def revoke_for_case(self, case_id: str) -> None:
        """DE-09: cancellation revokes the case's approval/permission
        record. Scoped here to authorization only — evidence retention for a
        cancelled case is T06's job, interrupting any in-flight blocking
        call is T07's."""
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
        if issued.revoked or record.token in self._revoked_tokens:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.CANCELLED, message="approval has been revoked"))
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
        if backend_kind != FAKE_BACKEND_KIND:
            # Defense in depth: even a perfectly scope-matched approval can
            # never authorize a real adapter until the T05 security gate
            # closes. This check is independent of the scope check above.
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
    """Bypass-path fix (security review): `Router.arm_target` has no
    built-in coupling to `ApprovalBroker` — nothing stops calling it
    directly without ever checking an approval. This function is the ONLY
    approval-gated path this codebase provides to `Router.arm_target`;
    `broker.verify_approval` runs first and its exception propagates before
    `router.arm_target` is ever reached, so authorization cannot be skipped
    by using this entrypoint.

    This does not make the bypass structurally impossible — Python has no
    module-private enforcement, and `router.arm_target` remains directly
    callable. The residual requirement (recorded in `tasks.md` T05) is that
    any future MCP facade (T07) must call `authorize_and_arm` exclusively
    and must never expose bare `Router.arm_target` to agent-reachable code.

    **RP-05-C regression fix (second security review pass):** there is
    deliberately no `backend_kind` parameter here. An earlier version took
    one as a free-standing string, which let a caller pass a real adapter
    (e.g. `VSCodeAdapter()`) while separately claiming `backend_kind="fake"`
    — the approval check and the adapter actually armed could silently
    diverge. Backend identity is now derived exclusively from
    `adapter.ide_id`, so there is no second, spoofable channel to disagree
    with it.
    """
    if target != plan.target:
        raise AutoDebugError(ErrorDetail(code=ErrorCode.TARGET_MISMATCH, message="routed target differs from plan"))
    broker.verify_approval(
        approval,
        plan=plan,
        backend_kind=adapter.ide_id,
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
