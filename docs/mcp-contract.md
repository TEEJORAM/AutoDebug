# AutoDebug — MCP contract (v0 draft)

This is AutoDebug's independent tool API, **not** the Microsoft DebugMCP API. Names and data types are intentionally stable at the gateway boundary; each adapter translates to actual supported backend operations. Version all externally observable schemas.

**Implementation status:** `server.py` binds all 15 facade tools to MCP
2025-11-25 stdio with JSON schemas, initialization, cancellation and strict
JSON-RPC errors. No SDK dependency or HTTP listener exists. Real backends remain
denied. `SENSITIVE_OUTPUT_BLOCKED` rejects colliding sanitized variable names.
`stop_observed`, `stack_observed` and `variable_observed` records persist exact
synthetic stop/process/plan context; native stop identity remains uncertified.
Output schema is `0.2-draft`; `0.1-draft` plan inputs retain structural
compatibility but must satisfy current integrity rules. Existing case folders
are never resumed as a new investigation.

## Minimal tool set

| MCP tool | Read/write class | Purpose |
|---|---|---|
| `autodebug_health` | Read | Server version + local readiness; no debugger data |
| `autodebug_probe_adapters` | Read | Exact installed adapters, IDE versions and capabilities |
| `autodebug_list_sessions` | Read | Discover native debugger sessions with unique identities |
| `autodebug_create_case` | Case metadata write | Allocate private case; no debugger action |
| `autodebug_stage_plan` | Case metadata write | Persist full reviewed plan (including exact script digest); no launch/attach |
| `autodebug_get_plan` | Read | Render complete plan for **local developer review** |
| `autodebug_arm_case` | **Privileged** | Verify independent approval; launch/attach per `GW-06` scenario A–D and set breakpoints |
| `autodebug_case_status` | Read | States, bound breakpoints, warnings and capability gaps |
| `autodebug_wait_for_stop` | Read, bounded | Wait for actual paused event; timeout required |
| `autodebug_get_stack` | Sensitive read | Read limited frames from pinned session |
| `autodebug_get_variables` | Sensitive read | Read selected variables; redact and bound outputs |
| `autodebug_step` | **Privileged** | STEP_OVER/IN/OUT; enforce approval scope and step budget |
| `autodebug_continue` | **Privileged** | Resume within approved scope; explicit current target check |
| `autodebug_complete_case` | Local write | Finish, persist JSONL + Markdown artifacts; no auto-Jira update |
| `autodebug_cancel_case` | Control | Per `DE-09`: stop AutoDebug operations, interrupt pending waits, revoke approval scope, retain partial evidence; idempotent on repeat; does not implicitly terminate app/IDE |

**Trust boundary:** `autodebug_stage_plan` is **not approval**, and AutoDebug must not expose an MCP tool that lets the agent self-approve a plan. A distinct trusted local CLI/UI controlled by the human records the signed/bound approval. The CLI syntax/UI implementation remains a task to design and test; do not treat example commands as working.

**Runtime bounds:** backend calls return within the smaller of the monotonic
case deadline and operation budget (default 5 seconds, maximum 30). Cancellation
interrupts the facade wait; abandoned targets are quarantined until process
restart/review, and late values are discarded/cleaned up. Python cannot forcibly
undo an arbitrary noncooperative external call. Native adapters without a
reviewed bounded-operation contract fail closed. Step/inspection/evidence limits
are positive finite and capped (10,000 steps/records, 86,400 case seconds).
Evidence storage requires a private POSIX base outside the source checkout,
no-follow descriptor-relative access, exclusive case creation and single-link
regular artifacts. Retention/deletion is owner-controlled, not automatic.

**Wire bounds:** 256 KiB input lines, 1 MiB encoded responses, eight ordinary
in-flight requests plus one reserved cancellation, 10,000 request IDs per
connection. Strings are normally limited to 8,192 characters; complete scripts
allow at most 64 KiB UTF-8. No approval, token, adapter object, shell or evaluation
parameter can be provided through MCP. The fixed CLI `--demo` seeds only the
isolated synthetic target; no tool grants approval.

### Strict-review completion and ownership clarification (2026-10-24)

Arming claims an active session exclusively and serializes target resolution and
breakpoint binding. An existing session is not disconnected by failed reuse;
only a newly created session is rolled back. Returned session identity and
authorization are rechecked before binding.

Completion serializes against inspection. `reproduced=True` requires a prior
confirmed pause (not proof of an actual native stop reason). Persistence must
succeed before memory becomes FINALIZED; failed completion is retryable.
Successful completion returns `state`, a concise `summary`, and `artifacts`:
`case.json`, `events.jsonl`, `report.md` mapped to paths relative to the configured
evidence base, such as `CASE-2026-001/report.md`. Zero-observation completion
creates an empty event log. Snapshot files use atomic replacement individually,
not one crash-atomic multi-file transaction.

Stack sanitization is recursive, with a 64 KiB UTF-8 output budget and 4,096
visited-node limit, plus existing depth/width bounds and explicit truncation.
Case IDs must be preserved unchanged by sanitization and fit 255 UTF-8 bytes.

## Core data model

Example `SessionRef` (illustrative JSON):

```json
{
  "host_id": "local-mac",
  "ide": "clion",
  "ide_instance_id": "clion-window-4",
  "debug_session_id": "native-session-7",
  "session_generation": 2,
  "pid": 4210,
  "process_start_id": "synthetic-start-identity"
}
```

Example `CasePlan`:

```json
{
  "schema_version": "0.2-draft",
  "case_id": "CASE-2026-001",
  "source_revision": "git-commit-sha",
  "target": {
    "host_id": "local-mac",
    "ide": "clion",
    "debug_session_id": "native-session-7",
    "pid": 4210,
    "process_start_id": "synthetic-start-identity"
  },
  "launch_configuration": [["launch_profile", "disposable-local-profile"]],
  "process_running": true,
  "breakpoints": [{"file": "/repo/src/file.cpp", "line": 123}],
  "reproduction": {
    "mode": "manual",
    "steps": ["Open a disposable design", "Invoke command X"],
    "script_sha256": null,
    "script_content": null,
    "risks": ["Disposable synthetic example only"],
    "sample_document": "No company or customer document"
  },
  "policy": {"max_steps": 20, "max_inspection_seconds": 300, "max_operation_seconds": 5.0, "max_evidence_records": 200},
  "digest_sha256": "canonical-plan-digest"
}
```

The illustrative `pid`, file path and digest are **not** live values and cannot be used to target a process. Actual identity handling needs an immutable session nonce/generation and PID/start-time verification to protect against PID reuse.

## Approval binding

### Publication-hardening clarification (2026-10-23)

Case/plan/approval IDs and routed targets must agree. Inspection uses the stored
arm approval but requires separate `op:wait_for_stop`, `op:get_stack`, and
`op:get_variables` scopes; `op:arm_case` alone grants none of these. Every poll,
read and mutation rechecks identity, plan, expiry/revocation and cancellation
under the per-session lease. Expiry is inclusive at the expiration instant.

The positive integer `max_inspection_seconds` budget starts at successful arming
and includes waits; exhaustion refuses further operations with `POLICY_LIMIT`
and retains incomplete evidence. A backend call cannot be forcibly interrupted;
authorization/deadline checks also reject late results. Continue invalidates the
cached pause. A later wait must confirm the stopped state before reading again.
Stacks allow 1-50 frames; variable requests select 1-50 names of at most 500
characters. Returned stack metadata, variable names and values are sanitized.
`SENSITIVE_OUTPUT_BLOCKED` now rejects collisions between sanitized variable
names; the earlier reserved/unused description is historical.

Evidence directories are exclusive to one investigation and cannot be reopened
as a new store. Review existing evidence through its owning store; a new case
needs a fresh ID. Artifact opens reject symlinks, hardlinks and nonregular files.
Secure persistence currently requires descriptor-relative no-follow opens:
Linux/macOS supported by this mechanism, Windows persistence explicitly
unavailable. This is not a verified cross-platform or native-IDE certification.
Reports may be finalized after continuation using already-recorded evidence;
finalization does not inspect a running debugger.

- Canonicalize the exact plan using a defined JSON canonicalization algorithm **chosen in design review**, including absolute target identity, ordered breakpoints, script contents hash, source revision, allowed operations, expiration, and output scope.
- Produce a cryptographic digest of that canonical representation. Do not hash whitespace-dependent ad-hoc string formats.
- Show the **complete plan and full script** to the developer in an independently trusted local surface. User approves **that digest**, subject to policy and short lifetime.
- Agent cannot invoke approval on the user's behalf. If any signed field changes, `PLAN_CHANGED` or `APPROVAL_EXPIRED` is returned.
- Re-check approval + session identity on **every** privileged call. After attach, the resulting native session must be explicitly bound under the reviewed target scope; otherwise re-approve.

## Standard response envelope

```json
{
  "ok": false,
  "case_id": "CASE-2026-001",
  "error": {
    "code": "CAPABILITY_UNSUPPORTED",
    "message": "The active Xcode bridge did not advertise stack inspection",
    "recoverable": false
  }
}
```

Proposed error codes:

`CAPABILITY_UNSUPPORTED`, `BACKEND_UNAVAILABLE`, `SESSION_AMBIGUOUS`, `SESSION_STALE`, `TARGET_MISMATCH`, `NOT_APPROVED`, `PLAN_CHANGED`, `APPROVAL_EXPIRED`, `BREAKPOINT_UNBOUND`, `NOT_PAUSED`, `TIMEOUT`, `PERMISSION_DENIED`, `POLICY_LIMIT`, `SENSITIVE_OUTPUT_BLOCKED`, `CANCELLED`, `INTERNAL_ERROR`.

## Evidence record, append-only JSONL

```json
{
  "schema_version": "0.2-draft",
  "case_id": "CASE-2026-001",
  "evidence_id": "E0007",
  "event_type": "variable_observed",
  "session_id": "native-session-7",
  "source_revision": "git-commit-sha",
  "frame": "function in file.cpp:123",
  "observation": "selected variable was null",
  "expected": "selected variable was initialized",
  "sanitization": "selected variables only; redacted",
  "confidence": "observation-only",
  "execution_confidence": "developer_reported",
  "stop_id": "synthetic-stop-3",
  "frame_generation": 3,
  "process_start_id": "synthetic-start-identity",
  "plan_digest": "canonical-plan-digest"
}
```

`execution_confidence` (per `RP-08`) is one of `not_applicable` (manual reproduction), `developer_reported` (developer says the script ran; no instrumentation confirms it), or `independently_verified` (a separate, instrumented signal confirmed execution). AutoDebug SHALL default to `developer_reported` for `api_script` cases absent real instrumentation.

Evidence is append-only, idempotent per `(case_id, evidence_id)`, capped in size/count and never sent wholesale into model context by default. `report.md` cites evidence IDs instead of copy-pasting raw memory dumps.

## Protocol transport

The operational transport is newline-delimited UTF-8 JSON-RPC on **stdio**,
pinned to MCP 2025-11-25. Initialize, send `notifications/initialized`, then
use `tools/list` / `tools/call`. Cancellation notifications suppress the
cancelled request response and revoke its case; cancellation tools return a
normal result. EOF cancels tracked cases and retires bounded workers.
See [installation](installation.md) for exact commands and synthetic handshake.
HTTP is intentionally deferred until a separately reviewed authentication,
CSRF and session-isolation design exists. External backend transport clients
are injected test doubles today, not operational native integrations.

## Versioning

Changes to stable tool names or required fields are breaking changes and require an updated spec plus contract tests. Keep transport schema, adapter protocol and stored `events.jsonl` schema versioned separately.
