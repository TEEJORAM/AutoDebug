"""Plan validation and canonical digest (RP-03, RP-05, RP-06, BR-03).

Plans are frozen dataclasses; this module validates their content and
computes the digest that later detects any change. Malformed input raises
`ValueError`; operational refusals are `AutoDebugError`s raised elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, replace
from pathlib import PurePosixPath, PureWindowsPath

from autodebug.models import BRIDGE_SCHEMA_VERSION, CasePlan, CasePolicy, ReproductionPlan, SCHEMA_VERSION

#: IDEs the bridge backend runs in (ide-debug-bridge proposal, phase 1).
BRIDGE_IDES = ("vscode", "cursor")
#: Fields that exist only in schema 0.3, with the default older plans must keep.
_BRIDGE_DEFAULTS = {
    "workspace_folder": None, "launch_configuration_name": None, "build_task": None,
    "report_to_workspace": True, "resolved_inputs": (),
}
_DEFAULT_BUILD_SECONDS = CasePolicy.max_build_seconds
_MAX_RESOLVED_BYTES = 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


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
    if plan.schema_version not in ("0.1-draft", SCHEMA_VERSION, BRIDGE_SCHEMA_VERSION):
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
    if plan.schema_version == BRIDGE_SCHEMA_VERSION:
        _validate_bridge_fields(plan)
    elif any(getattr(plan, name) != default for name, default in _BRIDGE_DEFAULTS.items()) or not (
        type(plan.policy.max_build_seconds) is int and plan.policy.max_build_seconds == _DEFAULT_BUILD_SECONDS
    ):
        raise ValueError(f"workspace, launch-name, build and resolved-input fields need schema {BRIDGE_SCHEMA_VERSION}")


def _bounded_text(value: object, maximum: int) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _is_relative_inside(path: str) -> bool:
    """A breakpoint path relative to the workspace that cannot leave it:
    no root, drive or UNC prefix, and no empty, `.` or `..` segment."""
    if not _bounded_text(path, 2000) or re.match(r"[A-Za-z]:", path):
        return False
    return all(part not in ("", ".", "..") for part in re.split(r"[\\/]", path))


def _expected_input_names(plan: CasePlan) -> set[str]:
    names = {"launch"} | {f"file:{bp.file}" for bp in plan.breakpoints}
    return names | {"task"} if plan.build_task is not None else names


def _validate_bridge_fields(plan: CasePlan) -> None:
    """BR-03 — schema 0.3: launch a named configuration from one absolute
    workspace folder, with breakpoints inside it."""
    if plan.target.ide not in BRIDGE_IDES:
        raise ValueError(f"schema {BRIDGE_SCHEMA_VERSION} plans target one of {', '.join(BRIDGE_IDES)}")
    folder = plan.workspace_folder
    if not _bounded_text(folder, 2000) or not (
        PurePosixPath(folder).is_absolute() or PureWindowsPath(folder).is_absolute()
    ):
        raise ValueError("workspace_folder must be a bounded absolute path")
    if not _bounded_text(plan.launch_configuration_name, 200):
        raise ValueError("launch_configuration_name must name one launch configuration (at most 200 characters)")
    if plan.build_task is not None and not _bounded_text(plan.build_task, 200):
        raise ValueError("build_task must be a task label of at most 200 characters")
    if plan.process_running or plan.launch_configuration:
        raise ValueError("bridge plans launch a named configuration; attach and inline configurations are refused")
    if not all(_is_relative_inside(bp.file) for bp in plan.breakpoints):
        raise ValueError("breakpoint files must be relative paths inside the workspace folder")
    if not isinstance(plan.report_to_workspace, bool):
        raise ValueError("report_to_workspace must be true or false")
    seconds = plan.policy.max_build_seconds
    if type(seconds) is not int or not 1 <= seconds <= 900:
        raise ValueError("policy.max_build_seconds must be an integer in [1, 900]")
    if plan.resolved_inputs:
        _validate_resolved_inputs(plan, plan.resolved_inputs)


def _validate_resolved_inputs(plan: CasePlan, inputs: object) -> None:
    if (
        not isinstance(inputs, tuple)
        or any(not isinstance(p, tuple) or len(p) != 2 or not all(isinstance(v, str) for v in p) for p in inputs)
        or len(dict(inputs)) != len(inputs)
    ):
        raise ValueError("resolved_inputs must be unique (name, sha256) pairs")
    if set(dict(inputs)) != _expected_input_names(plan):
        raise ValueError("resolved_inputs must cover the launch configuration, build task and every breakpoint file")
    if not all(_SHA256.fullmatch(digest) for _, digest in inputs):
        raise ValueError("resolved_inputs digests must be lowercase SHA-256 hex")


def _sha256_json(value: object) -> str:
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("resolved configuration must be plain JSON") from exc
    if len(data) > _MAX_RESOLVED_BYTES:
        raise ValueError("resolved configuration is larger than 1 MiB")
    return hashlib.sha256(data).hexdigest()


def resolve_inputs(
    plan: CasePlan, *, launch: Mapping, task: Mapping | None, files: Mapping[str, bytes]
) -> tuple[tuple[str, str], ...]:
    """BR-03 — hash what the bridge resolved for `plan`: the launch
    configuration, the build task and each breakpoint file's bytes.

    Refuses attach configurations and anything that does not match the plan."""
    if plan.schema_version != BRIDGE_SCHEMA_VERSION:
        raise ValueError(f"only schema {BRIDGE_SCHEMA_VERSION} plans have resolved inputs")
    if not isinstance(launch, Mapping) or launch.get("name") != plan.launch_configuration_name:
        raise ValueError("resolved launch configuration does not match launch_configuration_name")
    if launch.get("request") != "launch":
        raise ValueError("only launch configurations are allowed; attach is refused")
    if plan.build_task is None:
        if task is not None:
            raise ValueError("a build task was resolved but the plan names none")
    elif not isinstance(task, Mapping) or task.get("label") != plan.build_task:
        raise ValueError("resolved build task does not match build_task")
    wanted = {bp.file for bp in plan.breakpoints}
    if not isinstance(files, Mapping) or set(files) != wanted or not all(isinstance(b, bytes) for b in files.values()):
        raise ValueError("file contents must be given for exactly the breakpoint files")
    inputs = {"launch": _sha256_json(dict(launch))}
    if task is not None:
        inputs["task"] = _sha256_json(dict(task))
    inputs.update({f"file:{name}": hashlib.sha256(data).hexdigest() for name, data in files.items()})
    return tuple(sorted(inputs.items()))


def bind_resolved_inputs(plan: CasePlan, inputs: tuple[tuple[str, str], ...]) -> CasePlan:
    """Attach the bridge's resolved-input hashes to a staged schema 0.3 plan
    and return it with a new digest. A plan is bound once."""
    if plan.schema_version != BRIDGE_SCHEMA_VERSION or plan.resolved_inputs:
        raise ValueError("only an unbound schema 0.3 plan can be bound to resolved inputs")
    _validate_resolved_inputs(plan, inputs)
    return stage_plan(replace(plan, resolved_inputs=inputs, digest_sha256=None))


def compute_plan_digest(plan: CasePlan) -> str:
    """Canonical SHA-256 digest over `plan`, excluding the digest field
    itself. Sorted-key, separator-stripped JSON — never a whitespace-
    dependent ad-hoc format (see docs/mcp-contract.md "Approval binding").
    """
    payload = asdict(plan)
    payload.pop("digest_sha256", None)
    if plan.schema_version != BRIDGE_SCHEMA_VERSION:
        # Older plans keep the digest they had before schema 0.3 existed.
        for name in _BRIDGE_DEFAULTS:
            payload.pop(name, None)
        payload["policy"].pop("max_build_seconds", None)
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
