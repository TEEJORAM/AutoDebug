# AutoDebug — Security, approvals and privacy requirements

**A debugger is privileged software.** It can read customer data, secrets, memory and potentially execute code through evaluation. An MCP endpoint that can drive a debugger needs more than ordinary agent chat approval.

## Threats and controls

| Threat | Required v1 control |
|---|---|
| AI silently launches/attaches to wrong process | Explicit approved target + absolute executable + host + IDE instance + process identity; re-check per action |
| AI uses its own tool to approve itself | Approval only through **independent trusted local developer interaction**; no MCP self-approval operation |
| Prompt injection from Jira/source/doc strings | Treat retrieved content as **data**, never as authority to change approval policy or launch commands |
| Script changes after review | Hash full script + plan; invalidate approval on any change |
| Agent runs modified code inside Fusion | Never run scripts through AutoDebug; developer uses **existing Fusion UI** with reviewed script, or an already-approved existing interface |
| Unbounded stepping, hangs, runaway costs | Step budget, operation timeouts, bounded data collection, cancellation, single serialized command stream per session |
| Leakage of PII/customer documents/credentials | Selected-variable allowlist, redaction, size caps, approved model/data routing, protected local folder |
| Exposed localhost MCP endpoint | Loopback-only + session protection; for any HTTP exposure require authentication/CSRF/session policy; no network binding by default |
| Debugger attach to production process | Deny by default; no remote/production use case in v1 |
| Unsafe expression evaluation | **Denied by default** until separately specified, permissioned and security-reviewed |
| Wrong concurrent session stepped | Explicit native debug session nonce/generation, exclusive operation lease per session and user takeover detection |
| Incorrect AI RCA confidently asserted | Cite evidence, label `CONFIRMED`, `LIKELY`, or `INCONCLUSIVE`; include missing proof |

## Privacy reality

DebugMCP and AutoDebug may run locally, **but data read by an AI agent can be sent to its model provider**. Do not interpret “the server is localhost” as “debug information never leaves the computer.” Follow Autodesk-approved AI data handling and avoid sensitive information in prompts/tool responses.

## Developer approval must cover

1. Target app/process/host, IDE and source revision.
2. Launch or attach behavior, and whether application state can change.
3. Resolved breakpoint locations and conditions.
4. The **complete** reproduction script (or complete manual steps).
5. Allowed debugging actions (read locals/stack, bounded stepping/continuing), iteration/time limits.
6. Allowed evidence classes and private output directory.
7. Expiration/cancellation behavior. New script, source revision, session/target or privileges → **new approval**.

Plan approval should be mediated by a separate human-controlled local CLI/UI. The agent cannot invent a response claiming the developer clicked Approve. Approval metadata should include canonical plan digest, expiry, actor/OS context, and be auditable without storing a reusable secret in project files.

## Safe defaults

- No network remote debug access, no production debugging, no secret exports.
- No blanket shell execution, writes to the target program, arbitrary memory reads, shelling out inside target or expression evaluation.
- Only read the minimum stack and selected variables needed; cap frame depth and serialized output size.
- Abort on stale session, wrong PID, changed source revision, missing symbols, unbound breakpoints or backend disconnect.
- Never persist a user's raw document, crash dump or full customer dataset by default.
- Case artifacts in a private, access-restricted directory outside the Git repo; ignore them in `.gitignore`.
- Treat Jira integration separately from AutoDebug's debugger credential boundary. Jira reads go through Autodesk-approved connector methods.

## Policy and open-source requirements

- Follow Autodesk approval for the third-party MCP server, packages, licenses and external model/data routing.
- Microsoft DebugMCP is an optional **separately installed** external service. Don't copy its code; using a Code of Conduct is not the same as obtaining a license or internal company approval.
- For internal Visual Studio adapter code, verify reuse and distribution permissions with maintainers. Do not publish Autodesk internal source or Jira data.
- Keep dependency versions pinned and routinely reviewed. Check how `xcrun mcpbridge`, CLion MCP, and Cursor extension access behave under enterprise policies before enabling them.

## Security acceptance gates

### Current hardening boundary

The publication-hardening delta adds explicit read/wait scopes, live pause
checks, per-session leases around inspection, a monotonic inspection budget,
case/plan/target binding, and exclusive no-follow evidence storage. See
`openspec/changes/publication-hardening/` and `tests/test_publication_security.py`,
`tests/test_publication_evidence.py`. The strict follow-up adds active-session
ownership and arming serialization, returned-target/late authorization checks,
bounded recursive sensitive-name sanitization, backend-disconnect recovery,
retryable atomic snapshots and stop-confirmed completion. See
`tests/test_strict_final_security.py`. This does not close the real-debugger gate.
The technical-closure delta adds full UTF-8 script integrity, reviewed
launch/attach configuration, process-start/stop/frame identities, structured
variable sanitization, bounded backend waits, cancellation and late-result
quarantine. Stop/stack/variable records share an integrity ledger and citations.
Evidence bases must be private, current-user-owned and outside the source Git
checkout. See [technical closure](technical-closure-report.md).
An abandoned Python daemon call cannot be forcibly undone; its target stays
quarantined and no late result becomes evidence. This is **not** proof of native
interruptibility. Secure Windows persistence, trusted OS user presence, native
certification, owner-approved retention/data routing and independent human
review remain external gates. Pattern redaction cannot identify arbitrary
confidential prose or proprietary documents.

- `[SEC-01]` An unapproved `arm` call cannot reach a debugger backend (test using a spy adapter). — Verified: `FakeAdapter.launch_or_attach_calls` stays `0` across every unapproved/forged-approval path (`tests/test_facade.py`, `tests/test_approvals.py`).
- `[SEC-02]` Edited staged plan/digest fails closed with `PLAN_CHANGED`.
  Full UTF-8 script content and its recomputed SHA-256 are now mandatory in
  API-script plans; reviewed configuration/process state and all modeled
  budgets are hashed. See `tests/test_technical_closure.py` and plan/approval tests.
- `[SEC-03]` A forged chat approval string is rejected. — Verified: `tests/test_approvals.py::test_forged_approval_never_issued_by_broker_is_rejected` and related.
- `[SEC-04]` Wrong PID/session generation is rejected before stepping. — Verified: `test_reassigned_session_identity_blocks_step` across `test_facade.py` and all four real-adapter test files.
- `[SEC-05]` Cancellation/disconnection stops active AutoDebug work, leaving sanitized partial evidence. — Verified: `tests/test_t14_bug_to_evidence_demo.py` (`TestCancellationDemonstration`, `TestIncompleteInvestigationDemonstration`) and `tests/test_t15_security_release_gate.py` (`TestDE08ApprovalExpirationDuringInvestigation`).
- `[SEC-06]` Logs and output do not contain injected test secrets. — Verified: `tests/test_evidence.py`, `tests/test_t14_bug_to_evidence_demo.py::TestRedactionDemonstration`.

## T15 case-data handling review

**Historical review snapshot, not current release clearance.** The implementation
observations below describe the prior T15 review. Publication-preparation
hardening and its actual verification are tracked in `docs/status.md`; these
historical assertions must not be taken as a fresh security review or proof that
all output paths are safe. Pattern-based redaction is not a guarantee against
arbitrary confidential data. Policy decisions and independent review remain
required even when code adds defense-in-depth checks.

Reviewed `EvidenceStore` (`src/autodebug/evidence.py`) and `AutoDebugFacade`'s wiring of it against this document's "Case artifacts in a private, access-restricted directory outside the Git repo" and "never persist a user's raw document, crash dump or full customer dataset" requirements.

**Confirmed correct:**
- `EvidenceStore` never picks a default location — `evidence_base_dir` is always caller-supplied (constructor docstring, `facade.py:124`); no path anywhere in `src/autodebug` defaults into this repository.
- `events.jsonl` is append-only and capped (`DEFAULT_MAX_EVIDENCE_PER_CASE = 200`); redaction (`DE-07`) runs before anything is written, never after.
- Jira/source-control credentials have no field anywhere in `src/autodebug/models.py` — `record_intake` stores only a source label and free-text description.
- `.gitignore` already excludes `__pycache__/`, `*.pyc`, `*.egg-info/`, `.venv/`, `.DS_Store`. Case data has no default path, but callers can configure `evidence_base_dir` inside the repository; that location is not currently enforced, and the repository-location policy remains open.

**Missing policy decisions — each requires an explicit Autodesk policy/security decision before any code implements it; none has been invented, assumed, or silently selected here:**
1. **Evidence storage outside the repository.** `EvidenceStore` now rejects case IDs that are not a single path component and verifies that the resolved case directory is a direct child of the caller-supplied base directory. It still does not check whether that base itself is outside the repository or access-restricted. **Requires an explicit policy decision before adding that check:** "outside the repo" is ambiguous (outside this checkout only, or any Git working tree anywhere? how are symlinks handled? what happens to an existing case folder if policy changes?), and enforcing it would add a caller-facing refusal mode to a stable tool contract. No existing `RP-*`/`DE-*`/`GW-*`/`IDE-*` scenario defines that policy, so the implementation does not choose it.
2. **File-permission requirements.** `case_dir.mkdir(parents=True, exist_ok=True)` and file writes use default process umask — nothing calls `os.chmod`. **Requires a policy decision:** what permission model (owner-only `0700`/`0600`? group-readable for a shared dev machine?) is appropriate varies by OS and deployment context, and a wrong choice could itself be a availability regression (locking out a legitimate process) or a security gap (too permissive) — not something to pick without an explicit security-team answer.
3. **Evidence retention/deletion policy.** Nothing in AutoDebug ever deletes, archives, or ages out old case data — it accumulates indefinitely under whatever `evidence_base_dir` the caller chose. **Requires a policy decision:** how long sanitized debugging evidence should persist is a product/compliance question (data-minimization obligations, local disk growth, audit requirements), not a technical one — no spec requirement names a retention period, and none should be invented here.

These are not choices for the implementer to make unilaterally. They remain blockers for T15's approved-case-data acceptance criterion until an authorized policy owner makes and records each decision.
