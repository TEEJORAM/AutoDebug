# Capability: Bug intake, reproduction plan and developer approval

**Status:** DRAFT. AI reasoning occurs in the **client agent**; AutoDebug validates and executes only permitted plan operations.

## ADDED Requirements

### Requirement: RP-01 — Bug input provenance
A case SHALL accept a developer-supplied description or a Jira issue summary supplied through a separately authorized client connector. AutoDebug SHALL not store Jira access credentials as part of debugger routing.

#### Scenario: RP-01-A — Jira unavailable
- **GIVEN** the client has no authorized Jira connector
- **WHEN** a developer provides bug steps as text
- **THEN** a case can still be drafted, with source marked `developer_text`.

### Requirement: RP-02 — Source and documentation analysis is reviewable
The client agent SHALL identify suspected code paths and candidate source/line/function breakpoints with rationale, referencing an actual source revision. Unknown API availability SHALL be labeled unknown rather than guessed.

#### Scenario: RP-02-A — Unverifiable API
- **GIVEN** an API method cannot be verified in documentation or locally available definitions
- **WHEN** the agent prepares a reproduction
- **THEN** it SHALL not present a fabricated API script as executable; it proposes manual steps or marks an explicit dependency.

### Requirement: RP-03 — API-script and manual fallbacks
A reproduction plan SHALL explicitly choose either `api_script` with complete reviewed script content or `manual` with numbered steps. Only previously available, approved in-app script mechanisms may be used; **no new Fusion helper**.

#### Scenario: RP-03-A — API supports reproducing
- **GIVEN** the verified Fusion API can express all required steps
- **WHEN** the agent drafts the plan
- **THEN** it includes the **complete** script, required sample document, exact steps, expected side effects and script digest.

#### Scenario: RP-03-B — Issue depends on UI-only action
- **GIVEN** the API cannot reproduce a required interactive UI gesture
- **WHEN** the plan is prepared
- **THEN** it uses `manual` steps and no claim of automation.

### Requirement: RP-04 — Developer review before debugger changes
The developer SHALL review the complete plan: target host/app/IDE, launch or attach request, breakpoints, full script or manual actions, risks, permissions, evidence limits and time budgets **before** AutoDebug launches/attaches, sets breakpoints or runs debug operations.

#### Scenario: RP-04-A — Agent asks to arm before approval
- **GIVEN** a staged but unapproved plan
- **WHEN** the agent calls `autodebug_arm_case`
- **THEN** AutoDebug returns `NOT_APPROVED` without calling any debugger API.

### Requirement: RP-05 — Independent approval binding
Approval SHALL come from a developer-controlled trusted local interaction **outside agent-callable MCP tools**, tied to a canonical plan digest, full script hash, native target identity and expiration. A modified field SHALL invalidate approval. Fake or simulated approvals SHALL be permitted only inside isolated unit/integration tests running against a fake debugger backend; such approvals SHALL NEVER authorize an operation against a real native debugger session. Real-debugger authorization SHALL remain disabled until the approval-enforcement design has passed a dedicated security review (see `tasks.md` T05 security gate).

#### Scenario: RP-05-A — Script changed after review
- **GIVEN** a developer approved script revision A
- **WHEN** script revision B is supplied for execution
- **THEN** AutoDebug returns `PLAN_CHANGED` and requires new review.

#### Scenario: RP-05-B — Chat claims approval
- **GIVEN** an agent sends a string `developer approved` without a trusted approval record
- **WHEN** it requests launch or breakpoint operations
- **THEN** no debugger action is allowed.

#### Scenario: RP-05-C — Fake-backend approval replayed against a real adapter
- **GIVEN** a test-only approval record was issued for a case routed to the fake debugger backend
- **WHEN** that same approval is presented against a request routed to a real IDE adapter
- **THEN** AutoDebug rejects the request because the approval's bound backend/target does not match, and no real debugger operation occurs.

### Requirement: RP-06 — Breakpoints bound before reproduction
After approval, AutoDebug MAY launch/attach via the real IDE only when supported. It SHALL confirm that required breakpoints are **actually bound/verified** before telling the developer to reproduce the issue.

#### Scenario: RP-06-A — Symbol file missing
- **GIVEN** a breakpoint cannot bind because symbols are missing
- **WHEN** the developer is about to reproduce
- **THEN** AutoDebug reports `BREAKPOINT_UNBOUND` and does not say the reproduction is ready.

### Requirement: RP-07 — Script execution by existing app UI
In the Fusion v1 path, AutoDebug SHALL NOT automatically execute generated scripts inside Fusion. After plan approval and verified breakpoint binding, the developer SHALL run the exact reviewed script through existing Fusion Scripts and Add-Ins; manual cases are performed by the developer.

#### Scenario: RP-07-A — Application script trigger
- **GIVEN** an approved script and bound breakpoints
- **WHEN** AutoDebug reaches `AWAITING_DEVELOPER_REPRODUCTION`
- **THEN** it tells the developer how to run the reviewed script in the existing UI and awaits a real breakpoint event.

### Requirement: RP-08 — Script execution verification boundary
AutoDebug SHALL distinguish between *script generated*, *script approved*, *script execution requested*, *developer-reported execution*, and *independently verified execution* (when instrumentation exists). Without independent instrumentation, AutoDebug SHALL NOT assert that an approved script executed unchanged solely because the developer reports running it; this uncertainty SHALL be recorded in evidence and the final report.

#### Scenario: RP-08-A — Developer reports execution, no instrumentation available
- **GIVEN** an approved script has no independent execution-verification mechanism (e.g. no Fusion-side log or checksum confirmation)
- **WHEN** the developer reports having run the script and a breakpoint subsequently pauses
- **THEN** the evidence record and report state that execution was `developer_reported`, not independently verified, while still treating the observed pause/stack/variables as genuine debugger evidence.

#### Scenario: RP-08-B — No reproduction achieved
- **GIVEN** the API-script or manual route does not produce a debugger pause within the configured timeout
- **WHEN** the case is finalized
- **THEN** the report records reproduction as NOT achieved and does not claim script execution occurred correctly.
