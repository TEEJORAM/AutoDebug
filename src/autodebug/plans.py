"""Case plan validation and canonical digest (T04) — RP-03, RP-06 support.

Immutability itself is structural: `CasePlan` and its nested types are all
`@dataclass(frozen=True)` (T01). This module adds the two things T01
deliberately deferred: validating a plan's *content* is well-formed, and
computing a canonical digest over it so a later field change is detectable.
That detectability is what RP-05's "a modified field SHALL invalidate
approval" depends on — the trust decision over *who* approved a digest is
T05's job (approvals.py), not this one.

Malformed-input validation raises `ValueError` (a caller/construction-time
contract violation, no dedicated spec error code exists for it). Operational,
spec-named rejections (`PLAN_CHANGED`, `BREAKPOINT_UNBOUND`, ...) are raised
as `AutoDebugError` from `workflow.py` instead, not from here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, replace

from autodebug.models import CasePlan, ReproductionPlan, SCHEMA_VERSION


def validate_reproduction_plan(reproduction: ReproductionPlan) -> None:
    """RP-03 — exactly one of `api_script` or `manual`, never a hybrid and
    never a fabricated claim of automation."""
    if reproduction.mode not in ("api_script", "manual"):
        raise ValueError(f"reproduction.mode must be 'api_script' or 'manual', got {reproduction.mode!r}")
    if (
        not isinstance(reproduction.steps, tuple) or not 1 <= len(reproduction.steps) <= 100
        or any(not isinstance(step, str) or not step.strip() or len(step) > 10000 for step in reproduction.steps)
    ):
        raise ValueError("reproduction.steps must contain 1-100 bounded nonempty strings")
    if reproduction.mode == "api_script" and not reproduction.script_sha256:
        raise ValueError("an api_script reproduction plan requires a script_sha256 digest")
    if reproduction.mode == "api_script":
        content = reproduction.script_content
        if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 65536:
            raise ValueError("api_script requires complete reviewed script content, at most 64 KiB UTF-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if reproduction.script_sha256 != digest:
            raise ValueError("script_sha256 does not match complete UTF-8 script content")
    if reproduction.mode == "manual" and (reproduction.script_sha256 is not None or reproduction.script_content is not None):
        raise ValueError("a manual reproduction plan must not carry a script or script_sha256")
    if not isinstance(reproduction.risks, tuple) or len(reproduction.risks) > 100 or any(not isinstance(r, str) or not r.strip() or len(r) > 2000 for r in reproduction.risks):
        raise ValueError("reproduction risks must be bounded nonempty strings")
    if reproduction.sample_document is not None and (
        not isinstance(reproduction.sample_document, str) or not reproduction.sample_document.strip()
        or len(reproduction.sample_document) > 2000
    ):
        raise ValueError("sample_document must be a bounded description, never an embedded document")
    if reproduction.mode == "api_script" and (not reproduction.risks or reproduction.sample_document is None):
        raise ValueError("api_script requires explicit reviewed side effects/risks and a sample-document description")


def validate_case_plan(plan: CasePlan) -> None:
    """Structural checks on an immutable staged plan (RP-03, RP-06)."""
    if not plan.case_id:
        raise ValueError("case_id is required")
    if plan.schema_version not in ("0.1-draft", SCHEMA_VERSION):
        raise ValueError("unsupported plan schema version")
    if not plan.source_revision:
        raise ValueError("source_revision is required")
    if not isinstance(plan.breakpoints, tuple) or not 1 <= len(plan.breakpoints) <= 100:
        raise ValueError("at least one breakpoint is required — RP-06 has nothing to bind otherwise")
    if (
        not isinstance(plan.process_running, bool) or not isinstance(plan.launch_configuration, tuple)
        or len(plan.launch_configuration) > 100
        or any(not isinstance(pair, tuple) or len(pair) != 2 or any(not isinstance(v, str) or len(v) > 2000 for v in pair)
               for pair in plan.launch_configuration)
        or len(dict(plan.launch_configuration)) != len(plan.launch_configuration)
    ):
        raise ValueError("launch/attach configuration must be an immutable bounded mapping and reviewed process state")
    if not isinstance(plan.source_revision, str) or len(plan.source_revision) > 500:
        raise ValueError("source_revision must be a bounded string")
    for bp in plan.breakpoints:
        if (
            not isinstance(bp.file, str) or not bp.file or len(bp.file) > 2000
            or not isinstance(bp.line, int) or isinstance(bp.line, bool) or bp.line < 1
        ):
            raise ValueError("breakpoint requires a bounded file and positive integer line")
        if bp.condition is not None:
            raise ValueError("conditional breakpoints require a separately reviewed evaluation policy")
    for name, maximum in (("max_steps", 10000), ("max_inspection_seconds", 86400), ("max_evidence_records", 10000)):
        value = getattr(plan.policy, name)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
            raise ValueError(f"policy.{name} must be an integer in [1, {maximum}]")
    duration = plan.policy.max_operation_seconds
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 < duration <= 30:
        raise ValueError("policy.max_operation_seconds must be finite and in (0, 30]")
    validate_reproduction_plan(plan.reproduction)


def compute_plan_digest(plan: CasePlan) -> str:
    """Canonical SHA-256 digest over `plan`, excluding the digest field
    itself. Sorted-key, separator-stripped JSON — never a whitespace-
    dependent ad-hoc format (see docs/mcp-contract.md "Approval binding").
    """
    payload = asdict(plan)
    payload.pop("digest_sha256", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stage_plan(plan: CasePlan) -> CasePlan:
    """Validate `plan` and return an equivalent plan with `digest_sha256`
    populated. `CasePlan` is frozen, so this returns a new instance rather
    than mutating the one passed in; raises `ValueError` on malformed input.
    """
    validate_case_plan(plan)
    digest = compute_plan_digest(plan)
    return replace(plan, digest_sha256=digest)
