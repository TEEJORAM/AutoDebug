# Technical design — AutoDebug foundation

**Status:** DRAFT; do not implement before approval.  
**Related:** `docs/architecture.md`, `docs/mcp-contract.md`, `docs/security.md`.

## G00 correction log (revision 2)

Applied at human request, specifications only, still **NOT APPROVED**:

1. Added `GW-06` (AI-initiated launch/attach, 4 scenarios A–D) — see `specs/gateway-and-sessions/spec.md`.
2. Strengthened `RP-05` (fake approvals restricted to fake-backend tests only; added `RP-05-C`).
3. Rewrote `DE-06` with explicit `CONFIRMED`/`LIKELY`/`INCONCLUSIVE` evidentiary bar; added `DE-06-B`.
4. Added `IDE-04-B` (positive `PASS` criteria, 8-point bar).
5. Added `DE-09` (case cancellation, 3 scenarios).
6. Clarified `DE-07` ownership split between T05 (authorization) and T06 (sanitization).
7. Added `RP-08` (script-execution verification boundary: generated/approved/requested/developer-reported/independently-verified).
8. Tightened `tasks.md` T01 to standard-library-only scaffolding; SDK pin deferred to T07.

Requirement count: **25 → 28** (+`GW-06`, +`RP-08`, +`DE-09`). Scenario count: **29 → 41**.

## Design summary — eight sentences

1. An AI coding agent reads the bug/Jira description, source and approved application API docs, and proposes hypotheses, source breakpoints, and complete API/manual reproduction steps.
2. AutoDebug is a **local Python MCP tool server**, not an LLM or a replacement debugger.
3. It exposes stable tool commands and routes them to an **existing native IDE debugging session** through one of five independent adapter modules.
4. An independent local developer approval mechanism binds the target, breakpoint locations, full script digest, allowed operations and expiration to an immutable plan.
5. When approved and supported, the IDE adapter launches/attaches and sets **verified** breakpoints before reproduction.
6. The developer runs an approved Fusion script through the **existing Scripts and Add-Ins interface**, or performs manual steps; no new app-side helper is installed.
7. AutoDebug captures a small number of bounded stack/variable observations with event IDs, while the agent uses them to decide the next step.
8. The agent writes an evidence-backed root-cause report; AutoDebug persists local, redacted JSONL/Markdown artifacts.

## Components and ownership

| Component | Responsibility | Implementation proposal |
|---|---|---|
| `server.py` | Tool registration and transport | Official Python MCP SDK, version pinned after approval |
| `models.py` | Versioned data contracts | Python dataclasses or typed validation library decided in T01 |
| `sessions.py` | Native debugger identity + staleness detection | Thread-safe/session-aware registry |
| `router.py` | Explicit adapter selection by session reference | No silent defaults |
| `adapters/base.py` | Adapter Protocol / normalized errors | Independently written Python |
| `adapters/{vscode,cursor,clion,visual_studio,xcode}.py` | External MCP bridge clients / native APIs, capabilities | Probe first; return unsupported if unknown |
| `plans.py` | Immutable plan and canonical digest | Canonical JSON + SHA-256 versioned representation |
| `approvals.py` | Verify trusted human authorization | Separate local approval broker; **not** MCP self-approval |
| `workflow.py` | Controlled state transition and quotas | Deterministic state machine |
| `evidence.py` | Bounded, sanitized observations + local files | Versioned JSONL + Markdown report |
| `policy.py` | Enforcement of target, operation and data restrictions | No network/production target by default |

## Request path (one example)

1. Claude reads issue `FUS-EXAMPLE` through approved connector or pasted text. Claude uses its **own reasoning** to propose stack/variables/breakpoints; AutoDebug does not need Jira access to function.
2. Claude calls `autodebug_probe_adapters()` and `autodebug_list_sessions()`; AutoDebug returns **verified** capabilities and process/session IDs.
3. Claude calls `autodebug_stage_plan(case, target, source_sha, breakpoints, reproduction, allowed_actions)`; server validates fields and persists the immutable plan + full-script digest.
4. A **separate developer-controlled local confirmation process** displays the plan, including complete script and target. This user interaction stores an approval bound to plan digest + native process identity + expiry. **No MCP `approve` tool exists.**
5. Claude calls `autodebug_arm_case(case_id)`. AutoDebug validates approval, session generation and permitted operations, asks adapter to launch/attach if supported, binds each breakpoint, and returns true binding evidence.
6. AutoDebug enters `AWAITING_DEVELOPER_REPRODUCTION`. Developer runs the exact reviewed Fusion script from **Scripts and Add-Ins** or performs manual steps.
7. Adapter receives/queries the **actual debugger paused state**; AutoDebug stores stop reason, a limited stack, selected locals (sanitized), and offers evidence IDs to Claude.
8. Claude requests the next **approved** step or variable read, bounded by the time/step policy. No unlimited recursive variable expansion.
9. Claude produces a Markdown RCA draft linked to evidence IDs, or marks it inconclusive. AutoDebug stores sanitized case metadata/events and the completed report locally.

## Case workflow states

`NEW -> PLAN_STAGED -> AWAITING_APPROVAL -> APPROVED -> STARTING_OR_ATTACHING -> SESSION_VERIFIED -> BREAKPOINTS_BOUND -> AWAITING_DEVELOPER_REPRODUCTION -> PAUSED -> INSPECTING -> FINALIZED`.

`CANCELLED`, `FAILED`, `TIMED_OUT`, `INCOMPLETE` are terminal or recovery states. Any material plan/source/script/target change returns to `AWAITING_APPROVAL`. Pause state can cycle between inspecting and waiting within quota. See the `RP-*`/`DE-*` requirements for the full transition conditions, and `docs/architecture.md` for a worked example.

## Session routing invariants

- Every mutating call includes an explicit case + full session reference; never auto-select `current IDE` by process name.
- Re-check PID, process start identity, IDE instance ID and native session generation before privileged operations.
- The owner IDE/debugger stays in control; do not intercept private IDE debugger connections or start duplicate headless DAP sessions behind the developer's back.
- Serialize mutating commands and explicitly report session contention/takeover.
- Operations unavailable from a backend return a documented error and capability-state evidence.

## Five adapters and eleven targets

The **interface** for all five IDE families is defined in T01. Every adapter is present as a contract-conforming stub before native integrations are added. See `docs/ide-integrations.md`. The 11 combinations are a **test plan**, not a claim of completed support. Xcode uses Apple-supported MCP tooling where the installed release exposes debugger control; CLI LLDB in a second session is not equivalent to native Xcode debugger access. Cursor support must be tested independently from VS Code.

## Distinct software modes

- **MCP control plane** = tool invocation from AI client to AutoDebug.
- **Native debugger bridge** = approved MCP integrations or public native IDE API used by each adapter.
- **Application API script** = customer-app automation that the developer runs through an existing supported UI. It is NOT a debugger adapter and NOT AutoDebug's MCP tool.
- **Jira/API docs** = externally approved AI client knowledge; the AutoDebug server itself should not become a general document fetcher in foundation.

## Threat model and the approval gate

A boolean `approved=true` from an agent or a file editable by the same unrestricted agent **is not a security boundary**. The design requires a **trusted local user-presence process** separate from agent-callable MCP tools, ideally with OS-enforced restrictions and key storage. A small interactive CLI confirmation can validate usability for **fake/disposable targets**, but is **not** sufficient against an agent with unrestricted OS shell/file access. T05 must document the actual Mac/Windows/Linux enforcement strategy and undergo a separate security review **before controlling real developer/production applications**. Block rather than pretend this problem is solved.

Fake/simulated approval tokens are permitted **only** inside tests that run against the fake debugger backend (T05's own test suite); they must never be accepted by a real adapter code path (`RP-05`, `RP-05-C`). Real debugger operations remain disabled until the above enforcement strategy passes its dedicated security review — this gate blocks T08 onward, not T01–T07.

## Data model decisions (draft)

- `CasePlan`: schema version; source SHA; explicit target identity; ordered breakpoints; `api_script | manual` and full content/hash; side effects; scopes; budgets; creation time.
- `SessionRef`: host ID; OS; IDE family/version/instance; native debugger session ID; process PID + start identity; generation.
- `ApprovalRecord`: case ID; canonical plan digest; reviewer/human-presence proof; expiration; scope; one-time token and revocation indicator. **Not stored as a mutable agent-writable approval flag.**
- `EvidenceRecord`: monotonic evidence ID; session generation; source revision; event type; time; bounded observation; redaction metadata.
- `InvestigationReport`: root-cause statement and `CONFIRMED | LIKELY | INCONCLUSIVE`, cited evidence IDs, test/result, unresolved uncertainties, follow-up verification.

## Technology, packaging and test boundaries

- Python 3.11+ baseline **subject to enterprise toolchain checks**.
- Develop with test doubles and public mock tools first. **T01 uses Python standard library only** — no MCP SDK, no third-party packages, no package installation. The official MCP SDK is pinned in `pyproject.toml`, and real MCP transport wiring is implemented, only in **T07**, contingent on a separate, approved dependency review.
- Default stdio transport for a local Claude Code MCP. Optional secured loopback HTTP is separate change.
- Production calls to running programs are **not** part of basic CI. Run integration tests on disposable C++ test programs, one OS/IDE combination at a time.
- Store cases in a private per-user directory outside Git; avoid hardcoded paths and secrets in transcripts.

## Alternatives considered

1. **Fork DebugMCP** — rejected: high overlap, source copying concerns, only covers subset of target environments.
2. **Build independent DAP debugger** — rejected for native-session requirement: does not automatically control an IDE's existing debugger.
3. **One extension for each IDE first** — rejected for initial milestone: huge implementation cost before testing normalized gateway value.
4. **One gateway + adapter contracts + existing bridges** — selected provisionally. Reliability of each native IDE bridge remains a gating risk.

## Blocking questions to resolve in review

- **[OPEN]** How will a **trusted local developer approval** be enforced when Claude Code can also run OS shell commands? Define before real debugger integration (blocks T08+, not T01–T07).
- **[OPEN]** Which installed backend versions expose native debugger enumeration and stop events, especially Xcode, Cursor and CLion? (blocks T08–T11 claiming `PASS`, not T01).
- **[RESOLVED, this revision]** What precisely constitutes `CONFIRMED` RCA, and what evidence is sufficient for a reproducible fix? — see the rewritten `DE-06` in `specs/debugging-and-evidence/spec.md`: `CONFIRMED` requires direct evidence **and** credible causal validation (controlled reproduction, verified fix, or equivalent); a single breakpoint hit is never sufficient.
- **[OPEN]** What Autodesk policies authorize third-party MCP packages, Jira access and AI processing of debugger observations? (blocks T07's MCP SDK pin, T08–T12's IDE bridges, and T14's Jira connector — does **not** block T01, which is now standard-library-only per correction 8 below).

## Design approval

**NOT APPROVED.** Fill reviewer/date/commit after review; do not begin T01 without this explicit gate.
