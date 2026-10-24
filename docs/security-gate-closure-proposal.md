# Security-gate closure proposal (T05, draft)

**Status: PROPOSAL / DRAFT. NOT APPROVED. NOT IMPLEMENTED.** This document proposes candidate designs for the four unresolved, hard-blocking items from `tasks.md` T05's security gate. It does not change any code. `src/autodebug/approvals.py`'s `FAKE_BACKEND_KIND = "fake"` restriction and its unconditional refusal of any other `backend_kind` are **unchanged and must remain unchanged** until a specific proposal below is reviewed, explicitly approved, and implemented as its own small, tested task — the same discipline applied to every prior task in this project.

These are unapproved design candidates, not a legal verdict or an exemption
from Autodesk review.

Each section below presents candidate options and explicitly flags the decision as open. None of these candidates is a recommendation to implement as-is; each needs independent security review before any code is written against it.

## 0. Deployment scope for this revision (internal developer tool, not public release)

This revision re-scopes the candidates below against AutoDebug's **actual** deployment target: an internal, developer-operated debugging tool run by one Autodesk engineer on their own local disposable machine — not a public or customer-facing MCP product, not a multi-tenant service, not something distributed outside Autodesk. That distinction changes which controls are proportionate, but it does **not** remove any requirement actually grounded in project policy text. Every change below is justified by quoting the specific line it rests on — per this review's instruction, nothing is declared "no longer required" without pointing at where that requirement came from, and nothing is declared "approved" without evidence of an actual approval.

**Requirements that apply regardless of internal-vs-public scope (unconditional, not re-scoped by this document):**
- `CLAUDE.md`: *"Do not assume an AI tool call means human approval. Approval must come from a distinct local trusted user interaction, bound to a plan digest, script hash, target identity and expiration."* and *"Do not launch/attach, arm breakpoints, step/continue, evaluate expressions or run reproduction without the required approval."* — these describe a threat (the AI agent itself can run shell commands and could fake its own approval) that exists identically whether AutoDebug is used by one internal developer or a thousand external ones. Gate items 1 and 2 below remain mandatory for this reason; only their *implementation weight* is re-scoped.
- `CLAUDE.md`: *"Obtain Autodesk approval before installing any third-party agent/MCP package or sending company data to it; respect all enterprise policy settings."* and `docs/security.md`: *"Follow Autodesk approval for the third-party MCP server, packages, licenses and external model/data routing."* — this is about installing third-party software and routing data through an AI model, not about public redistribution. It applies identically to a single internal developer installing the DebugMCP extension. **Not removed.**
- `docs/security.md`: *"DebugMCP and AutoDebug may run locally, but data read by an AI agent can be sent to its model provider... Follow Autodesk-approved AI data handling and avoid sensitive information in prompts/tool responses."* — a data-classification/AI-usage requirement independent of deployment scope. **Not removed.**
- `CLAUDE.md`: *"Never connect a debugger to production processes or customer data by default. No secrets in tool arguments, logs or test fixtures."* and `docs/security.md`: *"Debugger attach to production process | Deny by default; no remote/production use case in v1."* — confirms the *existing* project scope already excludes production/customer targets for v1; this document does not change that, it only notes that AutoDebug's actual v1 target (one developer's own disposable local machine) is exactly the narrow case that line already describes.

**Historical distribution-scope considerations — no requirement waived:**
- `docs/security.md`: *"For internal Visual Studio adapter code, verify reuse and distribution permissions with maintainers. Do not publish Autodesk internal source or Jira data."* and `tasks.md` T12: *"Never package Autodesk internal code in public project."* These restrictions remain applicable. The historical T08 proposal concerned local VS Code/DebugMCP experiments, not permission to redistribute Autodesk material.
- `tasks.md` T15's "license review" remains required. Packaging/signing choices depend on a reviewed deployment design; local-only use does not establish ownership, remove license obligations, or grant an exemption from Autodesk review.

Nothing above grants approval or a legal conclusion. Scope and proportionality
arguments remain proposals for authorized review; all required approvals remain
in force.

## 1. Genuine OS-level trusted-human-presence mechanism (gate item 1)

**Problem:** `ApprovalBroker.issue_approval()`'s `human_presence_confirmed` flag is a bare boolean the calling process asserts — a same-user shell/file-access agent can set it to `True` with no actual human interaction. This is explicitly proven, not hidden, by `test_approvals.py::test_human_presence_confirmation_is_not_itself_a_security_boundary`. This requirement is **not removable for internal use** — `CLAUDE.md`'s "Approval must come from a distinct local trusted user interaction" describes the agent-can-run-shell-commands threat, which is identical whether one or a thousand people run AutoDebug.

**Candidate options:**
- **A. Native OS biometric/credential prompt via a signed helper.** Requires a code-signing identity and a packaging/distribution decision for the helper binary. **Re-scoped:** that packaging/signing overhead exists to let *other people's machines* trust a binary they didn't build themselves — it is a public/multi-developer-distribution concern (`docs/security.md`'s distribution-permission language is about redistributing to parties outside the author, not about a developer running their own code on their own machine). For a single internal developer running AutoDebug only on their own disposable Mac, this overhead is not currently justified; revisit if AutoDebug is ever distributed to other developers or machines.
- **B. Separate privileged local CLI/UI tool with its own OS session confirmation**, e.g. a small terminal/GUI prompt that requires the developer to physically click/type in a window the agent cannot script into (no synthetic input injection path). **Proposed as the right-sized MVP for T08's actual scope** — it satisfies `CLAUDE.md`'s "distinct local trusted user interaction" requirement without needing distribution/signing infrastructure that a single-machine internal tool has no use for.
- **C. Hardware security key / FIDO2 challenge-response** bound to the specific plan digest. Strongest tamper resistance, highest implementation cost. Not proposed for T08's initial scope; a candidate for later hardening if AutoDebug's threat model changes (e.g., broader rollout, higher-value targets).

**Open decision:** whether Option B is acceptable as the initial mechanism for T08's internal, single-developer scope. This is still a decision for you/security review — this document proposes B as proportionate, it does not declare it approved.

## 2. Process/privilege isolation for the approval broker (gate item 2)

**Problem:** `ApprovalBroker` currently runs in-process with the same Python interpreter that will eventually host the agent-facing facade — "no MCP tool currently calls `issue_approval`" is a code-review fact today, not a structural guarantee once a transport exists. **Not removable for internal use** — the risk is the same local agent/shell process reading or writing the broker's memory, independent of how many people use AutoDebug.

**Candidate options:**
- **A. Separate OS process/daemon** owning the broker's in-memory state, communicating with AutoDebug's facade over a narrow local IPC channel (e.g., a Unix domain socket with filesystem permissions restricting it to a different OS user/group than the agent's shell session). The facade could only call a read-only `verify_approval`-equivalent RPC, never `issue_approval`. **Proposed as sufficient for T08's internal scope** — a basic OS process boundary plus filesystem-permission separation on one known developer machine, without enterprise key-management infrastructure.
- **B. OS keychain/credential-store-backed tokens** (e.g., macOS Keychain) instead of an in-memory dict. Adds real tamper-resistance but also real integration work (keychain access prompts, cross-process credential sharing). **Re-scoped:** not necessary to satisfy gate item 2's core requirement (the agent must not be able to read/write approvals directly) for a single-machine internal tool; Option A alone is proposed as adequate for now. Worth revisiting if AutoDebug's threat model broadens.
- **C. Combination of A+B** — deferred alongside B, for the same reason.

**Open decision:** whether Option A alone is acceptable as the initial mechanism for T08's scope, or whether B's extra tamper-resistance should be required before any real backend is contacted. Still a decision for you — not approved by this document.

## 3. Verified machine/device identity (gate item 3, upgrading `DE-07`)

**Problem:** `reject_prohibited_target()` currently only checks that `host_id` starts with `"local"` and does not contain `"prod"`/`"remote"` — a naming convention, not a verified identity check, as its own docstring already states. The purpose of this check, per `docs/security.md`'s own threat table ("Debugger attach to production process | Deny by default; no remote/production use case in v1"), is to stop AutoDebug from accidentally targeting a production/remote process — **not** to authenticate an unknown machine in a fleet of many.

**Candidate options:**
- **A. Enterprise device-management attestation** — query Autodesk's device-management/MDM status to confirm the machine is a known, enrolled device. **Re-scoped:** this answers "is this one of *many* machines we trust," which matters for a multi-developer or public rollout. It does not add protection against this specific threat (accidental production targeting) beyond what the naming check already does, for a tool run by one developer on their own already-known machine.
- **B. Locally generated and pinned device certificate/fingerprint.** Same re-scoping as A — meaningful once multiple machines/developers are in scope; not currently load-bearing for a single-developer internal tool.
- **C. Keep the current naming heuristic, made explicit as a documented, developer-acknowledged risk acceptance** scoped to T08's actual target: one disposable local test app, on one developer's own machine, with no remote/production use case (already the documented v1 scope). **Proposed as proportionate for T08**, not as a permanent answer — revisit before any multi-developer rollout or before targeting anything beyond a disposable local test app.

**Open decision:** this document proposes Option C is the right fit for T08's actual, narrow scope — but accepting that risk is still your decision to make explicitly, not something this review grants on your behalf.

## 4. Backend allowlist requirement (gate item 4)

**Problem:** Today, `FAKE_BACKEND_KIND = "fake"` is the only accepted value, hardcoded and unconditionally enforced in `verify_approval()`. This must stay true until a specific, reviewed, versioned code change explicitly adds another value — never a runtime config flag, environment variable, or anything an agent or user input could toggle.

**Proposed mechanism (lowest-risk, consistent with the existing pattern):**
- Replace the single constant with an explicit, hardcoded `frozenset` of approved backend kinds, e.g. `APPROVED_BACKEND_KINDS = frozenset({"fake"})`, reviewed and extended by exactly one line per newly-approved real backend, in its own commit, only after that backend's dedicated security review (items 1–3 above) has passed **for that specific IDE**. `"vscode"` would be its own, separate, explicitly reviewed addition — not bundled with this document's approval.
- No other mechanism (config file, env var, CLI flag) should ever influence this set.

**Open decision:** none strictly required here — this is close to mechanical — but confirming the "one line per approved backend, own commit, own review" discipline is acceptable before it's implemented.

## 5. Read-only capability probing vs. debugger-mutating operations — different risk tiers

Not every `autodebug_*` tool carries the same risk, and this gate-closure effort does not need to treat them uniformly:

- **Read-only, no approval gate today** (per `docs/mcp-contract.md`'s existing classification): `autodebug_health`, `autodebug_probe_adapters`, `autodebug_list_sessions`. These never launch, attach, bind a breakpoint, step, continue, or evaluate anything — they report whether a backend is installed/reachable and what it advertises. Once the DebugMCP extension is actually installed under Autodesk approval (still unresolved — see §0), running `probe_capabilities()` against it to *discover* its advertised operations carries materially lower risk than any mutating call, since nothing is armed, no process is touched, and no approval is consumed either way.
- **Approval-gated, mutating** (per `docs/mcp-contract.md`): `autodebug_arm_case`, `autodebug_step`, `autodebug_continue`, and the launch/attach/breakpoint-bind sequence `autodebug_arm_case` performs internally. These are exactly what gate items 1–4 exist to block until closed — probing does not shortcut this.

**Proposed sequencing implication:** once DebugMCP installation is actually Autodesk-approved (§0, still open), a narrowly-scoped read-only probe (confirm the extension is installed, reachable, and report its advertised capabilities — resolving the `docs/ide-integrations.md` unknowns) could reasonably proceed **before** gate items 1–4 are fully closed, since it makes no mutating call and consumes no approval. Any launch/attach/breakpoint/step/continue call remains fully blocked until the gate closes. This is a sequencing proposal only — it does not authorize installing DebugMCP, which is still pending approval.

## 6. Disposable application and synthetic data for initial integration tests

Once real T08 testing is approved and begins, it must use a **disposable local application built solely for this purpose** (e.g., a trivial throwaway script with a couple of known variables) — never a real Autodesk product, customer code, or customer data. Variable/stack contents observed during the test must be **synthetic** (values the test itself creates, like `"test_counter = 1"`), never real secrets, credentials, or customer-derived data. This satisfies `CLAUDE.md`'s "Never connect a debugger to production processes or customer data by default. No secrets in tool arguments, logs or test fixtures" using data that cannot possibly violate it, by construction — the same principle already applied throughout T01–T07's fake-backend test suite, now carried forward to the first real-backend test. `docs/compatibility-ledger.md` and `docs/ide-integrations.md` have been updated to state this explicitly.

## Explicit preservation statement

No code in `src/autodebug/approvals.py` (or any other T01–T07 file) was changed to produce this document. `FAKE_BACKEND_KIND = "fake"` and its unconditional enforcement in `verify_approval()` remain exactly as committed. The T05 security gate remains **OPEN / NOT APPROVED**. Re-scoping candidate options for internal-only deployment (§0–§3) does not reduce what gate items 1–4 require structurally — it only right-sizes *how* each is proposed to be satisfied. Nothing in this document is approved; nothing in this document is implemented. Implementing any option above requires its own future task: explicit requirement IDs, a design delta if scope changes, tests against the fake backend first (same as every prior task), and your explicit approval before any real backend is contacted.
