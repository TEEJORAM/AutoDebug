# MCP contract (v0 draft)

AutoDebug's own tool API, **not** the Microsoft DebugMCP API. Tool names and
fields are stable at the gateway; each adapter translates them to real backend
operations. `server.py` binds all 15 tools to MCP 2025-11-25 stdio. There is no
SDK dependency or HTTP listener, and real backends are refused. Output schema
is `0.2-draft`; `0.1-draft` plan input is accepted under current integrity
rules.

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

**Trust boundary:** `autodebug_stage_plan` is **not approval**, and no MCP tool lets the agent approve a plan. Approval must come from a separate trusted local CLI/UI controlled by the developer; that interface is not built yet (only the `--demo` fixture issues a synthetic approval).

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

## Arming and completion

Arming claims the session exclusively and serializes target resolution and
breakpoint binding. A failed arm rolls back only a session it created; an
existing session is never disconnected. The returned session identity and the
approval are re-checked before binding.

Completion serializes against inspection. `reproduced=True` requires a prior
confirmed pause. Evidence must persist before the case becomes `finalized`; a
failed completion can be retried. Success returns `state`, a short `summary`
and `artifacts` (`case.json`, `events.jsonl`, `report.md`) as paths relative to
the run folder, e.g. `CASE-2026-001/report.md`. Each snapshot file is
replaced atomically, not as one multi-file transaction.

Stack output is sanitized recursively within a 64 KiB budget and 4,096 nodes.
Case IDs must survive sanitization unchanged and fit 255 UTF-8 bytes.

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

### Schema 0.3 (IDE bridge)

For the `vscode-bridge` backend ([ide-debug-bridge](../openspec/changes/ide-debug-bridge/spec.md),
`BR-03`). The plan launches one named configuration from `.vscode/launch.json`
in an absolute workspace folder; breakpoint files are relative to it and may not
leave it. `launch_configuration` must be empty and `process_running` false.

```json
{
  "schema_version": "0.3",
  "case_id": "DEMO-AREA-MOVE",
  "source_revision": "working-tree",
  "target": {"host_id": "local-windows", "ide": "vscode", "debug_session_id": null, "pid": null},
  "workspace_folder": "D:\\Projects\\AutoDebug\\examples\\AutoDebugDemo",
  "launch_configuration_name": "Debug tests",
  "build_task": null,
  "report_to_workspace": true,
  "breakpoints": [{"file": "geometry.py", "line": 15}],
  "reproduction": {"mode": "manual", "steps": ["Run the tests under the debugger"]},
  "policy": {"max_steps": 20, "max_inspection_seconds": 600, "max_build_seconds": 300}
}
```

`target.ide` is `vscode` or `cursor`; `build_task` is a task label or `null`;
`policy.max_build_seconds` is 1–900 (default 300). `resolved_inputs` is filled
by the bridge with SHA-256 hashes of the resolved launch configuration
(`launch`), build task (`task`) and each breakpoint file (`file:<path>`); a
caller that supplies it gets `PERMISSION_DENIED`. These hashes are part of the
digest, so editing any of those files changes the plan. Plans with schema
`0.1-draft` or `0.2-draft` cannot use these fields and keep their old digests.

## Approval binding

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
`SENSITIVE_OUTPUT_BLOCKED` rejects collisions between sanitized variable names.

Evidence directories are exclusive to one investigation and cannot be reopened
as a new store. Review existing evidence through its owning store; a new case
needs a fresh ID. Artifact opens reject symlinks, hardlinks and nonregular files.
Secure persistence currently requires descriptor-relative no-follow opens:
Linux/macOS supported by this mechanism, Windows persistence explicitly
unavailable. This is not a verified cross-platform or native-IDE certification.
Reports may be finalized after continuation using already-recorded evidence;
finalization does not inspect a running debugger.

- The plan digest is SHA-256 over sorted-key, separator-free JSON of the whole
  plan except the digest field (`plans.compute_plan_digest`): target identity,
  breakpoints, full script and hash, source revision, launch configuration,
  process state and policy limits.
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

Error codes:

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
