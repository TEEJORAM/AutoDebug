"""Evidence persistence and redaction (T06) — DE-02, DE-05, DE-06, DE-07, DE-08, DE-09.

Redaction and bounding happen *before* anything is ever written to disk or
handed back to a caller — nothing downstream can "undo" a decision not to
redact. `EvidenceStore` never chooses a default on-disk location inside this
repository; the caller supplies `base_dir`, which per docs/security.md must
be "a private, access-restricted directory outside the Git repo." This
module does not enforce that base-directory policy; it does ensure each
case stays within the supplied directory.

This module does not verify *who* approved a case (T05) or enforce session
identity (T03) — it only records what was observed, sanitizes it, and writes
it down honestly, including when a case ends cancelled or incomplete.
"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import uuid
import hashlib
from contextlib import contextmanager
from dataclasses import asdict
from itertools import islice
from pathlib import Path
from typing import Iterator, TextIO

from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import SCHEMA_VERSION, EvidenceRecord, ExecutionConfidence, InvestigationReport, RootCauseConfidence

REDACTED_PLACEHOLDER = "***REDACTED***"
MAX_VALUE_LENGTH = 500
#: A prudent default cap on total evidence per case, so storage stays
#: bounded even across a long investigation. This is storage hygiene, not an
#: implementation of DE-03's step budget (that remains CasePolicy.max_steps
#: from T01/T04) — the two are independent limits.
DEFAULT_MAX_EVIDENCE_PER_CASE = 200
MAX_OUTPUT_BYTES = 65536
MAX_OUTPUT_NODES = 4096
MAX_EVENT_BYTES = 262144

#: DE-07 — a variable whose *name* matches one of these (case-insensitive,
#: substring) is always redacted, regardless of its value.
_SENSITIVE_NAME_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "api_key",
    "credential",
    "authorization",
    "auth_token",
    "private_key",
    "access_key",
)

#: DE-07 — value-shape patterns that are redacted regardless of variable name.
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id shape
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # common "secret key" prefix shape
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),  # GitHub personal access token shape
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM private key header
)


def redact_value(name: str, value: str) -> tuple[str, bool]:
    """DE-07 — return `(sanitized_value, was_redacted)`. Name-based and
    value-pattern-based detection are independent layers; either alone
    triggers redaction (defense in depth, same pattern used in T05's
    `reject_prohibited_target`)."""
    lowered_name = name.lower()
    if any(marker in lowered_name for marker in _SENSITIVE_NAME_MARKERS):
        return REDACTED_PLACEHOLDER, True
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        if pattern.search(value):
            return REDACTED_PLACEHOLDER, True
    return value, False


def cap_value(value: str, max_length: int = MAX_VALUE_LENGTH) -> tuple[str, bool]:
    """DE-02 — bounded output, never a full memory dump. Returns
    `(possibly-truncated value, was_truncated)`."""
    if len(value) <= max_length:
        return value, False
    omitted = len(value) - max_length
    return f"{value[:max_length]}...<truncated, {omitted} more chars>", True


def sanitize_observation(name: str, value: str, *, max_length: int = MAX_VALUE_LENGTH) -> tuple[str, str]:
    """DE-02 + DE-07 pipeline: redact first, then bound size. A redacted
    value is never subsequently truncated to reveal partial content — it's
    already replaced outright. Returns `(sanitized_value, sanitization_note)`.
    """
    redacted_value, was_redacted = redact_value(name, value)
    if was_redacted:
        return redacted_value, "redacted: sensitive name/value pattern matched (DE-07)"
    capped_value, was_truncated = cap_value(redacted_value, max_length=max_length)
    if was_truncated:
        return capped_value, "truncated: exceeded bounded output size (DE-02)"
    return capped_value, "no redaction needed"


def redact_text(text: str) -> tuple[str, bool]:
    """DE-07 — scan free-form prose (report statements, causal-validation
    justifications, uncertainties, next steps) for the same sensitive
    value-shape patterns `redact_value` uses, masking only the matching
    substrings in place.

    Unlike `redact_value` (used for a single name/value observation, where
    the *entire* value is replaced once any marker matches), prose keeps its
    surrounding narrative — only the matched secret-shaped substring is
    replaced, since there is no separate "name" to key off of here. This
    closes a bypass where a raw secret embedded directly in
    `root_cause_statement`/`causal_validation`/`uncertainties`/`next_steps`
    would otherwise skip `record_evidence`'s redaction pipeline entirely and
    reach `report.md` unredacted.
    """
    redacted_any = False

    def _mask(match: re.Match) -> str:
        nonlocal redacted_any
        redacted_any = True
        return REDACTED_PLACEHOLDER

    result = text
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        result = pattern.sub(_mask, result)
    return result, redacted_any


def sanitize_text(text: str) -> str:
    """Redact value-shaped secrets before bounding arbitrary metadata/prose."""
    return cap_value(redact_text(text)[0])[0]


def sanitize_output(value: object, *, depth: int = 0) -> object:
    """Bound the whole tree, including JSON escaping, not just each leaf."""
    remaining_bytes = MAX_OUTPUT_BYTES - 1024
    remaining_nodes = MAX_OUTPUT_NODES
    marker = "<truncated: output budget>"

    def visit(item: object, level: int) -> object:
        nonlocal remaining_bytes, remaining_nodes
        remaining_nodes -= 1
        if level >= 5 or remaining_nodes < 1 or remaining_bytes < 128:
            return marker
        remaining_bytes -= 4
        if isinstance(item, dict):
            result = {}
            observation_name = item.get("name")
            sensitive_observation = isinstance(observation_name, str) and redact_value(observation_name, "")[1]
            for key, child in islice(item.items(), 50):
                if remaining_nodes < 1 or remaining_bytes < 128:
                    result["<truncated>"] = marker
                    break
                name = str(key)
                safe_key = sanitize_text(name)
                remaining_bytes -= len(json.dumps(safe_key).encode("utf-8")) + 2
                if safe_key in result:
                    result["<truncated>"] = "<truncated: sanitized key collision>"
                    break
                if redact_value(name, "")[1] or (sensitive_observation and name == "value"):
                    child = REDACTED_PLACEHOLDER
                result[safe_key] = visit(child, level + 1)
            if len(item) > 50:
                result["<truncated>"] = "<truncated: field limit>"
            return result
        if isinstance(item, (tuple, list)):
            result = []
            for child in item[:50]:
                if remaining_nodes < 1 or remaining_bytes < 128:
                    result.append(marker)
                    break
                result.append(visit(child, level + 1))
            if len(item) > 50:
                result.append("<truncated: item limit>")
            return result
        safe = item if item is None or isinstance(item, (bool, int, float)) else sanitize_text(str(item))
        size = len(json.dumps(safe).encode("utf-8"))
        if size > remaining_bytes - 128:
            remaining_bytes = 0
            return marker
        remaining_bytes -= size
        return safe

    sanitized = visit(value, depth)
    if len(json.dumps(sanitized).encode("utf-8")) > MAX_OUTPUT_BYTES - 128:
        return {"truncated": marker}
    return sanitized


def build_investigation_report(
    *,
    case_id: str,
    root_cause_statement: str,
    confidence: RootCauseConfidence,
    evidence_ids: tuple[str, ...],
    reproduced: bool,
    uncertainties: tuple[str, ...] = (),
    next_steps: tuple[str, ...] = (),
    causal_validation: str | None = None,
    execution_confidence: ExecutionConfidence = ExecutionConfidence.NOT_APPLICABLE,
) -> InvestigationReport:
    """DE-06 — structurally enforce the confidence bar rather than trusting
    the caller's say-so. `CONFIRMED` requires at least one cited evidence ID
    **and** a non-empty `causal_validation` justification (a controlled
    reproduction, a verified fix, or equivalent) — a single breakpoint hit
    alone can never satisfy this function's `CONFIRMED` path. `LIKELY` still
    requires at least one evidence ID; `INCONCLUSIVE` does not (evidence may
    be genuinely insufficient).

    DE-07: every free-text field here (`root_cause_statement`,
    `causal_validation`, `uncertainties`, `next_steps`) is scanned with
    `redact_text` before this function returns — this is a distinct redaction
    pass from `EvidenceStore.record_evidence`'s, since prose can carry a raw
    secret that never went through that pipeline at all.
    """
    confidence = RootCauseConfidence(confidence)
    if not isinstance(reproduced, bool) or not isinstance(root_cause_statement, str) or not root_cause_statement.strip():
        raise ValueError("report requires a nonempty statement and boolean reproduced")
    if causal_validation is not None and (not isinstance(causal_validation, str) or not causal_validation.strip()):
        raise ValueError("causal_validation must contain a substantive nonempty justification")
    if confidence in (RootCauseConfidence.CONFIRMED, RootCauseConfidence.LIKELY) and not evidence_ids:
        raise ValueError(f"{confidence.value} requires at least one cited evidence ID")
    if confidence == RootCauseConfidence.CONFIRMED and not causal_validation:
        raise ValueError(
            "CONFIRMED requires a causal_validation justification (DE-06) — a controlled "
            "reproduction, a verified fix, or equivalent direct evidence; a breakpoint hit "
            "alone is not sufficient"
        )
    statement = root_cause_statement
    if causal_validation:
        statement = f"{root_cause_statement} Causal validation: {causal_validation}"
    statement = sanitize_text(statement)
    sanitized_uncertainties = tuple(sanitize_text(u) for u in uncertainties)
    sanitized_next_steps = tuple(sanitize_text(n) for n in next_steps)
    return InvestigationReport(
        case_id=sanitize_text(case_id),
        root_cause_statement=statement,
        confidence=confidence,
        evidence_ids=tuple(sanitize_text(e) for e in evidence_ids),
        reproduced=reproduced,
        uncertainties=sanitized_uncertainties,
        next_steps=sanitized_next_steps,
        execution_confidence=execution_confidence,
        causal_validation=sanitize_text(causal_validation) if causal_validation else None,
    )


def render_report(report: InvestigationReport, *, case_state: str) -> str:
    """DE-05/DE-06 — the Markdown report template. Cites evidence IDs rather
    than embedding raw data (see docs/mcp-contract.md: "report.md cites
    evidence IDs instead of copy-pasting raw memory dumps").

    DE-07 defense in depth: this function re-applies `redact_text` to every
    free-text field immediately before writing, independent of whether the
    `InvestigationReport` passed in was built through
    `build_investigation_report` (which already redacts) or constructed by
    hand (nothing stops that — `InvestigationReport` is a plain dataclass).
    This is the actual disk-writing boundary, so it is the last line of
    defense, not the only one.
    """
    statement = sanitize_text(report.root_cause_statement)
    uncertainties = [sanitize_text(u) for u in report.uncertainties]
    next_steps = [sanitize_text(n) for n in report.next_steps]
    lines = [
        f"# Case {sanitize_text(report.case_id)}",
        "",
        f"Case state: {sanitize_text(case_state)}",
        f"Reproduced: {'YES' if report.reproduced else 'NO'}",
        f"Script execution confidence: {report.execution_confidence.value}",
        "",
        "## Root-cause statement",
        "",
        f"**Confidence: {report.confidence.value.upper()}**",
        "",
        statement,
        "",
        "## Supporting evidence",
        "",
    ]
    lines += [f"- {sanitize_text(evidence_id)}" for evidence_id in report.evidence_ids] or ["- (none cited)"]
    lines += ["", "## Uncertainties / alternative explanations", ""]
    lines += [f"- {u}" for u in uncertainties] or ["- (none noted)"]
    lines += ["", "## Recommended next steps", ""]
    lines += [f"- {n}" for n in next_steps] or ["- (none)"]
    return "\n".join(lines) + "\n"


class EvidenceStore:
    """DE-05 — one case's append-only JSONL events, `case.json`, and
    `report.md`, under `base_dir/case_id/`. `base_dir` is always
    caller-supplied; this class never picks a default location. It keeps
    each case directory inside a private base outside the source repository.
    A case directory is
    exclusively created, never reopened as a new investigation. Platforms
    without descriptor-relative no-follow opens fail closed.
    """

    def __init__(self, base_dir: Path, case_id: str, *, max_events: int = DEFAULT_MAX_EVIDENCE_PER_CASE) -> None:
        validate_case_id(case_id)
        if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
            raise OSError("secure evidence persistence requires descriptor-relative no-follow opens")
        if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        self.case_id = case_id
        self.max_events = max_events
        self._lock = threading.RLock()
        self._record_digests: dict[str, str] = {}
        base_path = Path(base_dir).resolve()
        for parent in Path(__file__).resolve().parents:
            if (parent / ".git").exists() and base_path.is_relative_to(parent):
                raise ValueError("evidence must be outside the source repository")
        base_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.case_dir = base_path / case_id
        base_fd = os.open(base_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            base_info = os.fstat(base_fd)
            if base_info.st_uid != os.getuid() or stat.S_IMODE(base_info.st_mode) & 0o077:
                raise PermissionError("evidence base must be owned by the current user and private (0700)")
            try:
                os.mkdir(case_id, mode=0o700, dir_fd=base_fd)
            except FileExistsError as exc:
                raise ValueError("case directory already exists; use a fresh case_id") from exc
            directory_fd = os.open(
                case_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd,
            )
            try:
                info = os.fstat(directory_fd)
                self._directory_identity = (info.st_dev, info.st_ino)
            finally:
                os.close(directory_fd)
        finally:
            os.close(base_fd)
        self.events_path = self.case_dir / "events.jsonl"
        self.case_path = self.case_dir / "case.json"
        self.report_path = self.case_dir / "report.md"
        self._next_sequence = 1

    @contextmanager
    def _open_file(self, name: str, mode: str) -> Iterator[TextIO]:
        """Pin the original directory and reject symlinks/non-private files."""
        try:
            directory_fd = os.open(self.case_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError as exc:
            raise ValueError("evidence case directory disappeared") from exc
        try:
            info = os.fstat(directory_fd)
            if (info.st_dev, info.st_ino) != self._directory_identity:
                raise ValueError("evidence case directory identity changed")
            temporary_name = None
            artifact_name = name
            if mode == "w":
                try:
                    existing_fd = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd,
                    )
                except FileNotFoundError:
                    pass
                else:
                    try:
                        existing = os.fstat(existing_fd)
                        if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                            raise ValueError("evidence artifact must be a regular file with a single link")
                    finally:
                        os.close(existing_fd)
                temporary_name = f".{name}.{uuid.uuid4().hex}.tmp"
                artifact_name = temporary_name
            flags = os.O_RDONLY if mode == "r" else os.O_WRONLY | os.O_CREAT
            if temporary_name is not None:
                flags |= os.O_EXCL
            if mode == "a":
                flags |= os.O_APPEND
            fd = os.open(
                artifact_name, flags | os.O_NOFOLLOW | os.O_NONBLOCK,
                mode=0o600, dir_fd=directory_fd,
            )
            try:
                file_info = os.fstat(fd)
                if not stat.S_ISREG(file_info.st_mode) or file_info.st_nlink != 1:
                    raise ValueError("evidence artifact must be a regular file with a single link")
                stream = os.fdopen(fd, mode, encoding="utf-8")
            except BaseException:
                os.close(fd)
                if temporary_name is not None:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                raise
            try:
                with stream:
                    yield stream
                if temporary_name is not None:
                    os.replace(temporary_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                    temporary_name = None
            finally:
                if temporary_name is not None:
                    os.unlink(temporary_name, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)

    def record_evidence(
        self,
        *,
        event_type: str,
        session_id: str,
        source_revision: str,
        frame: str,
        observation_name: str,
        observation_value: str,
        expected: str,
        confidence: str,
        execution_confidence: ExecutionConfidence = ExecutionConfidence.NOT_APPLICABLE,
        stop_id: str | None = None,
        frame_generation: int | None = None,
        process_start_id: str | None = None,
        plan_digest: str | None = None,
    ) -> EvidenceRecord:
        """DE-02/DE-05/DE-07: sanitize, bound, assign a stable monotonic
        evidence ID, and append to `events.jsonl`. The raw `observation_value`
        is never written anywhere once this returns — only the sanitized
        form exists in the returned record and on disk.

        The `max_events` cap (default `DEFAULT_MAX_EVIDENCE_PER_CASE`) is
        checked *before* any write for this call — exceeding it raises
        `POLICY_LIMIT` and writes nothing new, but every evidence record
        already recorded and already on disk is untouched and remains fully
        readable via `read_events()`. The cap rejects the next write; it
        never discards or truncates prior history.
        """
        with self._lock:
            if self._next_sequence > self.max_events:
                raise AutoDebugError(
                    ErrorDetail(
                        code=ErrorCode.POLICY_LIMIT,
                        message=f"case {sanitize_text(self.case_id)} reached its {self.max_events}-evidence cap",
                    )
                )
            sanitized_value, sanitization_note = sanitize_observation(
                observation_name, observation_value,
                max_length=MAX_OUTPUT_BYTES if event_type == "stack_observed" else MAX_VALUE_LENGTH,
            )
            evidence_id = f"E{self._next_sequence:04d}"
            record = EvidenceRecord(
                schema_version=SCHEMA_VERSION,
                case_id=sanitize_text(self.case_id),
                evidence_id=evidence_id,
                event_type=sanitize_text(event_type),
                session_id=sanitize_text(session_id),
                source_revision=sanitize_text(source_revision),
                frame=sanitize_text(frame),
                observation=f"{sanitize_text(observation_name)}={sanitized_value}",
                expected=sanitize_text(expected),
                sanitization=sanitization_note,
                confidence=sanitize_text(confidence),
                execution_confidence=execution_confidence,
                stop_id=sanitize_text(stop_id) if stop_id is not None else None,
                frame_generation=frame_generation,
                process_start_id=sanitize_text(process_start_id) if process_start_id is not None else None,
                plan_digest=sanitize_text(plan_digest) if plan_digest is not None else None,
            )
            self._append_event(record)
            self._record_digests[evidence_id] = self._record_digest(record)
            self._next_sequence += 1
            return record

    @staticmethod
    def _record_digest(record: EvidenceRecord) -> str:
        payload = asdict(record)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def require_capacity(self, count: int) -> None:
        with self._lock:
            if self._next_sequence - 1 + count > self.max_events:
                raise AutoDebugError(ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="case evidence budget exhausted before inspection"))

    def _append_event(self, record: EvidenceRecord) -> None:
        payload = asdict(record)
        payload["execution_confidence"] = record.execution_confidence.value
        serialized = json.dumps(payload, sort_keys=True) + "\n"
        if len(serialized.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError("sanitized evidence record exceeds serialized byte limit")
        with self._open_file("events.jsonl", "a") as f:
            f.write(serialized)

    def read_events(self) -> tuple[EvidenceRecord, ...]:
        """Idempotent read-back, e.g. for report generation or tests."""
        with self._lock:
            records = []
            try:
                with self._open_file("events.jsonl", "r") as f:
                    while True:
                        line = f.readline(MAX_EVENT_BYTES + 1)
                        if not line:
                            break
                        if len(line.encode("utf-8")) > MAX_EVENT_BYTES or len(records) >= self.max_events:
                            raise ValueError("evidence read exceeds approved record/byte limits")
                        data = json.loads(line)
                        data["execution_confidence"] = ExecutionConfidence(data["execution_confidence"])
                        record = EvidenceRecord(**data)
                        if (
                            record.case_id != self.case_id
                            or record.evidence_id != f"E{len(records) + 1:04d}"
                            or self._record_digests.get(record.evidence_id) != self._record_digest(record)
                        ):
                            raise ValueError(f"evidence E{len(records) + 1:04d} identity/content differs from this investigation's append ledger")
                        records.append(record)
                    if len(records) != len(self._record_digests):
                        raise ValueError("stored evidence was removed or truncated")
            except FileNotFoundError:
                # Only the artifact can be missing: directory errors are
                # checked separately before the descriptor-relative open.
                if self._record_digests:
                    raise ValueError("stored evidence event file disappeared") from None
                return ()
            return tuple(records)

    def finalize(self, *, case_state: str, report: InvestigationReport | None) -> None:
        """DE-05/DE-08/DE-09: write `case.json` with the case's *real*,
        current state — `CANCELLED`/`INCOMPLETE`/`FAILED`/`FINALIZED`/etc. —
        never overridden to look complete. Idempotent: calling this more than
        once (e.g. a repeated cancellation, DE-09-B) simply rewrites the same
        honest snapshot. Always callable, even with zero evidence recorded or
        no report available — a cancelled/incomplete case still gets its
        partial state persisted rather than silently dropped.
        """
        with self._lock:
            if report is not None:
                if report.case_id != self.case_id:
                    raise ValueError("report belongs to another case")
                available = {event.evidence_id for event in self.read_events()}
                if any(eid not in available for eid in report.evidence_ids):
                    raise ValueError("report cites evidence absent from this investigation")
            case_payload = {
                "schema_version": SCHEMA_VERSION,
                "case_id": sanitize_text(self.case_id),
                "state": sanitize_text(case_state),
                "evidence_count": self._next_sequence - 1,
            }
            with self._open_file("events.jsonl", "a"):
                pass
            if report is not None:
                with self._open_file("report.md", "w") as f:
                    f.write(render_report(report, case_state=case_state))
            with self._open_file("case.json", "w") as f:
                f.write(json.dumps(case_payload, sort_keys=True, indent=2))


def validate_case_id(case_id: str) -> None:
    """Require a single path component before using a case ID as a directory."""
    if (
        not isinstance(case_id, str)
        or not case_id
        or case_id in {".", ".."}
        or "/" in case_id
        or "\\" in case_id
        or "\0" in case_id
        or len(case_id.encode("utf-8")) > 255
        or sanitize_text(case_id) != case_id
    ):
        raise ValueError("case_id must be a non-empty single path component preserved by sanitization, at most 255 bytes")
