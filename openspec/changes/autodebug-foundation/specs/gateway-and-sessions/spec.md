# Capability: Gateway and native debugger session control

**Status:** DRAFT. Requirement IDs are stable references for tests, tasks and evidence.

## ADDED Requirements

### Requirement: GW-01 — One original MCP gateway
AutoDebug SHALL provide a single local MCP interface that exposes a stable, versioned set of commands to compatible AI clients. It SHALL route to **verified native debugger sessions** through platform-specific adapters. It SHALL not implement a new native debugger engine.

#### Scenario: GW-01-A — Client sees consistent tools
- **GIVEN** an AI client connects to the AutoDebug server
- **WHEN** it lists exposed tools
- **THEN** it sees the documented AutoDebug contract, regardless of installed IDEs.

### Requirement: GW-02 — Capability discovery
Each adapter SHALL report IDE/backend version, transport reachability, session-discovery ability and supported operations. `UNKNOWN`, `UNSUPPORTED`, and `UNAVAILABLE` SHALL be distinct states.

#### Scenario: GW-02-A — Missing backend
- **GIVEN** Xcode is not installed
- **WHEN** AutoDebug probes adapters
- **THEN** it reports Xcode `UNAVAILABLE` with a reason and does not invent debugger tools.

#### Scenario: GW-02-B — Backend has no stack operation
- **GIVEN** a connected backend does not advertise stack inspection
- **WHEN** an agent requests a stack
- **THEN** AutoDebug returns `CAPABILITY_UNSUPPORTED` and no fake stack.

### Requirement: GW-03 — Exact native session identity
A session SHALL be identified by host, IDE instance, backend session ID, process identity (PID + start identity where available) and generation/nonce. Mutating operations SHALL validate this identity before executing.

#### Scenario: GW-03-A — Two debuggers open
- **GIVEN** two IDE windows are debugging different processes
- **WHEN** AutoDebug lists sessions
- **THEN** it returns distinguishable session records and requires explicit selection for the next operation.

#### Scenario: GW-03-B — Stale process session
- **GIVEN** a previously selected process has exited and its PID was reused
- **WHEN** a step command targets the stale reference
- **THEN** it fails as `SESSION_STALE` or `TARGET_MISMATCH` without reaching any debugger.

### Requirement: GW-04 — Native session ownership
AutoDebug SHALL operate on the requested IDE's current native debugger when the adapter explicitly supports it. It SHALL never silently launch an independent debugger in its place.

#### Scenario: GW-04-A — Only headless DAP available
- **GIVEN** a backend supports standalone DAP but cannot access the IDE's active debugger
- **WHEN** an agent requests native-session attachment
- **THEN** AutoDebug explains the limitation and declines the native-session operation.

### Requirement: GW-06 — AI-initiated launch and attach scenarios
AutoDebug SHALL support AI-proposed, developer-approved launch or attach to a target application through the selected IDE's verified native integration, covering four distinct scenarios. A *requested* breakpoint SHALL NOT be treated as *bound* until the adapter confirms it (see `RP-06`).

#### Scenario: GW-06-A — Application not running (launch)
- **GIVEN** an approved plan identifies a target executable that is not currently running
- **WHEN** AutoDebug arms the case
- **THEN** it requests launch through the selected IDE's native integration only if that integration supports launch, and does not report ready-to-reproduce until breakpoints report bound.

#### Scenario: GW-06-B — Application running, no debugger attached
- **GIVEN** an approved plan identifies an already-running process with no attached debugger
- **WHEN** AutoDebug arms the case
- **THEN** it requests attachment to the exact approved process (PID + start identity) through a verified native IDE interface and confirms a new debug-session identity before setting breakpoints.

#### Scenario: GW-06-C — Existing active IDE debugger session
- **GIVEN** the target process already has an active native debugger session in the selected IDE
- **WHEN** AutoDebug arms the case
- **THEN** it selects that existing session, SHALL NOT launch a second/duplicate debugger, and sets/verifies breakpoints in that session only.

#### Scenario: GW-06-D — IDE cannot perform the requested launch/attach
- **GIVEN** the selected IDE's adapter does not support launch or attach for the requested configuration
- **WHEN** AutoDebug arms the case
- **THEN** it returns `UNSUPPORTED` (or the applicable typed error), tells the developer to perform the operation manually in the IDE, and resumes only after confirming the resulting session identity matches the approved target.

**Limitation note:** attaching after application startup can miss breakpoints in code paths that already executed; see `docs/architecture.md` ("Launch/attach limitations") and risk `R9` in `docs/risks.md`.

### Requirement: GW-05 — Safe operation serialization
AutoDebug SHALL serialize state-changing commands per native session, enforce stop-state preconditions, and use bounded timeouts and cancellation.

#### Scenario: GW-05-A — Concurrent continue and step
- **GIVEN** a debug session has two pending commands from different AI clients
- **WHEN** both request state changes
- **THEN** at most one operation executes at a time and the other is rejected or safely queued within policy.
