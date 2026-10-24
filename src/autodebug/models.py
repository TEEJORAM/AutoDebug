"""Versioned, typed data contracts for AutoDebug (GW-01).

Shape definitions only. Validation and digests live in plans.py, approval
issuance in approvals.py, and persistence in evidence.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

SCHEMA_VERSION = "0.2-draft"
#: Plan schema for the IDE bridge backend (ide-debug-bridge BR-03).
BRIDGE_SCHEMA_VERSION = "0.3"


class CapabilityState(str, Enum):
    """Distinct adapter-capability states (GW-02).

    UNKNOWN (not yet probed) is never conflated with UNSUPPORTED (probed, the
    backend lacks the capability) or UNAVAILABLE (backend unreachable).
    """

    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
    AVAILABLE = "available"


class CaseState(str, Enum):
    """Case workflow states (see design.md "Case workflow states").

    Enumerated here as a stable contract; workflow.py enforces the
    actual transitions and invalidation rules.
    """

    NEW = "new"
    PLAN_STAGED = "plan_staged"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    STARTING_OR_ATTACHING = "starting_or_attaching"
    SESSION_VERIFIED = "session_verified"
    BREAKPOINTS_BOUND = "breakpoints_bound"
    AWAITING_DEVELOPER_REPRODUCTION = "awaiting_developer_reproduction"
    PAUSED = "paused"
    INSPECTING = "inspecting"
    FINALIZED = "finalized"
    CANCELLED = "cancelled"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INCOMPLETE = "incomplete"


class RootCauseConfidence(str, Enum):
    """DE-06 confidence bar — CONFIRMED requires causal validation, never a
    single observation alone."""

    CONFIRMED = "confirmed"
    LIKELY = "likely"
    INCONCLUSIVE = "inconclusive"


class ExecutionConfidence(str, Enum):
    """RP-08 — how sure AutoDebug is that an approved script actually executed
    unchanged. Defaults to DEVELOPER_REPORTED absent real instrumentation."""

    NOT_APPLICABLE = "not_applicable"
    DEVELOPER_REPORTED = "developer_reported"
    INDEPENDENTLY_VERIFIED = "independently_verified"


class IntakeSource(str, Enum):
    """RP-01 — where a case's bug report came from. There is deliberately no
    credential field anywhere in this module: AutoDebug never stores Jira
    access credentials as part of debugger routing."""

    JIRA = "jira"
    DEVELOPER_TEXT = "developer_text"


@dataclass(frozen=True)
class SessionRef:
    """GW-03 — a native debugger session's full identity. Every field is
    required before a mutating operation; never key on process name alone."""

    host_id: str
    ide: str
    ide_instance_id: str
    debug_session_id: str
    session_generation: int
    pid: int
    executable: str
    state: str
    capabilities: tuple[str, ...] = ()
    process_start_id: str | None = None


@dataclass(frozen=True)
class TargetRef:
    """The reduced target identity recorded on a CasePlan before a live
    session exists.

    `ide_instance_id` (GW-03) is optional because it is frequently unknown
    before a session exists at all — e.g. the launch scenario (`GW-06-A`)
    has no IDE window yet. Once a session exists, `SessionRef.ide_instance_id`
    is always known and required.
    """

    host_id: str
    ide: str
    debug_session_id: str | None
    pid: int | None
    ide_instance_id: str | None = None
    process_start_id: str | None = None


@dataclass(frozen=True)
class StopSnapshot:
    session: SessionRef
    stop_id: str
    reason: str
    frame_generation: int
    breakpoint_file: str | None = None
    breakpoint_line: int | None = None


@dataclass(frozen=True)
class Breakpoint:
    file: str
    line: int
    condition: str | None = None


@dataclass(frozen=True)
class ReproductionPlan:
    """RP-03 — exactly one of api_script or manual; `mode` names which."""

    mode: str  # "api_script" | "manual"
    steps: tuple[str, ...]
    script_sha256: str | None = None
    script_content: str | None = None
    risks: tuple[str, ...] = ()
    sample_document: str | None = None


@dataclass(frozen=True)
class CasePolicy:
    max_steps: int
    max_inspection_seconds: int
    max_operation_seconds: float = 5.0
    max_evidence_records: int = 200
    #: Schema 0.3 only: limit for the plan's build task (BR-05).
    max_build_seconds: int = 300


@dataclass(frozen=True)
class CasePlan:
    """RP-04/RP-05 — the complete, hashable plan a developer approves. Digest
    computation lives in plans.py."""

    schema_version: str
    case_id: str
    source_revision: str
    target: TargetRef
    breakpoints: tuple[Breakpoint, ...]
    reproduction: ReproductionPlan
    policy: CasePolicy
    digest_sha256: str | None = None
    launch_configuration: tuple[tuple[str, str], ...] = ()
    process_running: bool = False
    # Schema 0.3 (BR-03). Paths in `breakpoints` are relative to the workspace.
    workspace_folder: str | None = None
    launch_configuration_name: str | None = None
    build_task: str | None = None
    report_to_workspace: bool = True
    #: (name, sha256) of what the bridge resolved: "launch", "task" and
    #: "file:<path>" per breakpoint file. Set by the bridge, never the caller.
    resolved_inputs: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ApprovalRecord:
    """RP-05 — proof of developer approval, bound to a plan digest and target
    identity. Issuance and verification live in approvals.py."""

    case_id: str
    plan_digest: str
    reviewer: str
    expiration: str
    scope: tuple[str, ...]
    token: str
    revoked: bool = False


@dataclass(frozen=True)
class EvidenceRecord:
    """DE-05/RP-08 — one sanitized observation. Persistence belongs to
    evidence.py."""

    schema_version: str
    case_id: str
    evidence_id: str
    event_type: str
    session_id: str
    source_revision: str
    frame: str
    observation: str
    expected: str
    sanitization: str
    confidence: str
    execution_confidence: ExecutionConfidence = ExecutionConfidence.NOT_APPLICABLE
    stop_id: str | None = None
    frame_generation: int | None = None
    process_start_id: str | None = None
    plan_digest: str | None = None


@dataclass(frozen=True)
class InvestigationReport:
    """DE-06 — the final root-cause statement. Never CONFIRMED without causal
    validation."""

    case_id: str
    root_cause_statement: str
    confidence: RootCauseConfidence
    evidence_ids: tuple[str, ...]
    reproduced: bool
    uncertainties: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    execution_confidence: ExecutionConfidence = ExecutionConfidence.NOT_APPLICABLE
    causal_validation: str | None = None
