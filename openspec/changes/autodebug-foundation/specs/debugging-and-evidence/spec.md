# Capability: Bounded debugging, evidence and root-cause report

**Status:** DRAFT.

## ADDED Requirements

### Requirement: DE-01 — Confirm a real pause
AutoDebug SHALL inspect a debugger only after confirming the selected native session is paused and collecting an actual stop reason. It SHALL not report a breakpoint hit solely from an AI hypothesis.

#### Scenario: DE-01-A — Application keeps running
- **GIVEN** an armed case whose application never reaches a breakpoint
- **WHEN** the configured timeout expires
- **THEN** AutoDebug returns `TIMEOUT`, records incomplete reproduction and does not fabricate pause data.

### Requirement: DE-02 — Small, selected observations
AutoDebug SHALL read bounded stack frames and **named selected** variables, avoiding full memory dumps, secret discovery and unbounded object expansion by default.

#### Scenario: DE-02-A — Large object
- **GIVEN** a selected variable expands into millions of child values
- **WHEN** AutoDebug collects its value
- **THEN** output is capped, redacted where required, and marked truncated.

### Requirement: DE-03 — Step-by-step reasoning under a budget
The agent MAY request one operation at a time: get stack, get variables, step, continue, wait. AutoDebug SHALL enforce approved action scopes, serialized execution, step/time/data limits and cancellation.

#### Scenario: DE-03-A — Step budget exceeded
- **GIVEN** a plan allows 20 steps and all 20 have been used
- **WHEN** the agent requests another step
- **THEN** AutoDebug returns `POLICY_LIMIT` and requests a new reviewed plan if deeper inspection is needed.

### Requirement: DE-04 — Expression evaluation opt-in
Expression evaluation is **not** part of initial functional debugging capabilities, because evaluation can execute code inside the app. A later change MUST specify its safety/authorization model before enabling it.

#### Scenario: DE-04-A — Eval attempted in v1
- **GIVEN** an initial v1 debugger session
- **WHEN** the agent requests arbitrary `evaluate_expression`
- **THEN** AutoDebug returns `CAPABILITY_UNSUPPORTED` or `PERMISSION_DENIED` without executing it.

### Requirement: DE-05 — Evidence persisted locally
AutoDebug SHALL write sanitized, versioned, append-only JSONL event records for a case and a human-readable Markdown report in a private folder ignored by Git. Every important assertion SHALL reference evidence IDs.

#### Scenario: DE-05-A — Case finalized
- **GIVEN** a case has stopped at least once and captured observations
- **WHEN** the agent finalizes the case
- **THEN** local `events.jsonl`, `case.json` and `report.md` are available; the agent receives their relative paths and a concise summary.

### Requirement: DE-06 — Honest root cause confidence
The report SHALL distinguish `CONFIRMED`, `LIKELY` or `INCONCLUSIVE` causes against the following bar:
- `CONFIRMED` requires directly observed debugging evidence supporting the proposed cause **and** credible causal validation — e.g. a controlled reproduction establishing the causal relationship, a verified fix eliminating the same failure under comparable conditions, or equivalent direct evidence that the identified condition produces the defect. A breakpoint hit alone is NOT sufficient.
- `LIKELY` applies when direct observations support a technically plausible explanation, but the causal relationship has not yet been conclusively validated.
- `INCONCLUSIVE` applies when available evidence is insufficient, contradictory, or does not reliably identify the cause.

Every conclusion SHALL cite stored evidence IDs, separate observed facts from hypotheses, identify relevant functions/source revisions/variable states when available, describe what was actually reproduced, and state what additional testing would increase confidence. AutoDebug SHALL not claim to do AI reasoning itself, and the agent SHALL NOT invent debugger observations, source locations, or confirmation results.

#### Scenario: DE-06-A — Evidence supports only suspicion
- **GIVEN** a suspect null pointer with no test of why it became null
- **WHEN** the AI writes the report
- **THEN** it marks the cause `LIKELY` or `INCONCLUSIVE`, not `CONFIRMED`.

#### Scenario: DE-06-B — Confirmed requires causal validation, not a single hit
- **GIVEN** a suspect condition was observed once at a breakpoint with no controlled re-test or differentiating fix
- **WHEN** the AI writes the report
- **THEN** it SHALL NOT label the cause `CONFIRMED`, even though the breakpoint hit matches the hypothesis exactly.

### Requirement: DE-07 — Privacy and nonproduction defaults
AutoDebug SHALL block remote/production process attachment by default and prevent storing raw tokens, passwords, confidential documents or unbounded memory in evidence artifacts. **Ownership split:** authorization/target rejection (denying a prohibited target before any debugger call) is a `T05` concern; sanitization, redaction and storage mechanics are a `T06` concern — see `docs/traceability.md`. A single passing test SHALL NOT be treated as proof that both concerns are implemented.

#### Scenario: DE-07-A — Secret fixture appears
- **GIVEN** a test variable contains a sample secret marker
- **WHEN** an observation is saved and returned to the agent
- **THEN** the value is masked and raw secret is absent from all case files and logs.

### Requirement: DE-08 — Recover from interruption safely
On debugger disconnect, user cancellation, or approval expiration, AutoDebug SHALL stop additional privileged actions, preserve sanitized partial evidence and label the case incomplete.

#### Scenario: DE-08-A — IDE exits mid-investigation
- **GIVEN** AutoDebug is investigating a paused session
- **WHEN** the IDE terminates unexpectedly
- **THEN** case state becomes failed/incomplete, with no rerouting to a different live session.

### Requirement: DE-09 — Case cancellation
Cancellation SHALL be requestable by the developer at any time, and by the AI agent only within previously approved scope. Valid case states for cancellation include any non-terminal state. On cancellation, AutoDebug SHALL: stop issuing further privileged operations immediately; interrupt any pending blocking call (e.g. `autodebug_wait_for_stop`) with a `CANCELLED` result; revoke the case's approval/permission record for further use; finalize and retain whatever sanitized evidence was already captured, marking the case `CANCELLED`; and return the same `CANCELLED` status, idempotently, on repeated cancellation requests for the same case. Cancellation SHALL NOT terminate the developer's application or the native IDE debugger session unless an explicitly approved operation authorizes that specific behavior; by default AutoDebug disconnects from the session without killing the target process.

#### Scenario: DE-09-A — Developer cancels mid-inspection
- **GIVEN** a case is `INSPECTING` with a pending `autodebug_wait_for_stop` call
- **WHEN** the developer requests cancellation
- **THEN** the pending call returns `CANCELLED`, no further privileged operations are accepted for that case, and partial sanitized evidence is retained with the case marked `CANCELLED`.

#### Scenario: DE-09-B — Repeated cancellation request
- **GIVEN** a case is already `CANCELLED`
- **WHEN** a second cancellation request arrives for the same case
- **THEN** AutoDebug returns the same `CANCELLED` status without error and without re-attempting any debugger operation.

#### Scenario: DE-09-C — Cancellation does not kill the application
- **GIVEN** an active, approved debug session with the target application running
- **WHEN** the case is cancelled without an explicit terminate-application approval
- **THEN** AutoDebug disconnects from the debugger session only; the developer's application and native IDE remain running untouched.
