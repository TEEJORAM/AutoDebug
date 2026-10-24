# Security, approvals and privacy

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

## Implemented controls

Beyond the threat table, the code enforces:

- Separate approval scopes per operation (`op:arm_case`, `op:wait_for_stop`,
  `op:get_stack`, `op:get_variables`, `op:step`, `op:continue`); arming grants
  no read scope.
- Re-checks of cancellation, session identity and ownership, plan digest,
  approval, expiry and budgets before and after every backend call, under a
  per-session lease.
- Full UTF-8 script content (≤64 KiB) with recomputed SHA-256, reviewed
  launch/attach configuration and process state inside the plan digest.
- Process-start, stop and frame identities; a changed stop discards the read.
- Bounded backend calls; abandoned targets are quarantined and late results
  discarded. Python cannot undo a noncooperative external call.
- Recursive redaction of nested values before stringification, and of report
  prose before it is written.

These do not close the real-debugger gate (see
[security-gate-closure-proposal.md](security-gate-closure-proposal.md)).

## Security acceptance tests

| ID | Requirement | Tests |
|---|---|---|
| SEC-01 | An unapproved `arm` never reaches a backend | `test_facade.py`, `test_approvals.py` (spy adapter call count stays 0) |
| SEC-02 | An edited plan or script fails with `PLAN_CHANGED` | `test_plans.py`, `test_approvals.py`, `test_technical_closure.py` |
| SEC-03 | A forged chat approval is rejected | `test_approvals.py::test_forged_approval_never_issued_by_broker_is_rejected` |
| SEC-04 | Wrong PID or session generation is refused before stepping | `test_reassigned_session_identity_blocks_step` in `test_facade.py` and `test_ide_adapters.py` |
| SEC-05 | Cancel/disconnect stops work and keeps sanitized partial evidence | `test_t14_bug_to_evidence_demo.py`, `test_t15_security_release_gate.py` |
| SEC-06 | Injected test secrets never reach outputs or files | `test_evidence.py`, `test_t14_bug_to_evidence_demo.py::TestRedactionDemonstration` |

Pattern-based redaction cannot recognise arbitrary confidential prose or
proprietary documents.

## Case-data policy

Implemented: the caller always supplies the evidence base; it must be outside
the source repository, owned by the current user and private (`0700`, files
`0600`); each case directory is created exclusively and never reused; artifacts
are opened without following links; evidence is append-only and capped.

Still requiring an authorized policy decision:

1. **Retention and deletion.** Nothing ages out or deletes case data; how long
   evidence may persist is a compliance decision.
2. **Formal sign-off** that the outside-repository rule and the permission model
   above match Autodesk policy (part of the T15 review in
   [publication.md](publication.md)).
