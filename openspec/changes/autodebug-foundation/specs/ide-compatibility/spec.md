# Capability: Five IDE adapters and cross-platform compatibility

**Status:** DRAFT. Do not interpret an OS target as verified debugger support.

## ADDED Requirements

### Requirement: IDE-01 — Declare five IDE families from project start
AutoDebug SHALL define independent adapters for VS Code, Cursor, CLion, Visual Studio and Xcode, all conforming to the same typed adapter protocol. Stub adapters SHALL return explicit not-implemented errors until proven working.

#### Scenario: IDE-01-A — First scaffold on macOS
- **GIVEN** a fresh checkout of the initial project scaffold on macOS
- **WHEN** all adapters are probed
- **THEN** five adapters are listed and Windows-only Visual Studio is marked `NOT_APPLICABLE` rather than crashing or claiming support.

### Requirement: IDE-02 — Correct OS availability matrix
VS Code, Cursor and CLion SHALL be target-supported on Windows/macOS/Linux. Visual Studio (full IDE) SHALL be Windows-only. Xcode SHALL be macOS-only, for **11 intended IDE/OS combinations**.

#### Scenario: IDE-02-A — Xcode on Linux
- **GIVEN** the host OS is Linux
- **WHEN** Xcode adapter discovery runs
- **THEN** it reports `NOT_APPLICABLE` and does not try to spawn `xcrun`.

### Requirement: IDE-03 — Reuse external integrations without copying source
Where possible, AutoDebug SHALL communicate through the permitted published MCP interface of separately installed native IDE integrations. **Microsoft DebugMCP source is not copied or vendored.** Internal Autodesk adapters are not redistributed without authorization.

#### Scenario: IDE-03-A — DebugMCP not installed
- **GIVEN** the IDE supports an external MCP bridge but that bridge is absent
- **WHEN** AutoDebug probes the adapter
- **THEN** it reports `UNAVAILABLE` and instructions for sanctioned installation, not an automatic download or code copy.

### Requirement: IDE-04 — Native debugger proof required
A backend SHALL be called `PASS` only when a disposable app in the **visible IDE's existing native debugger** supports the required scenario: list exact session, set/bind breakpoint, detect pause, inspect stack and selected locals, step, continue, and disconnect without cross-session errors.

#### Scenario: IDE-04-A — Xcode tools lack debugging
- **GIVEN** the installed Xcode MCP bridge exposes no native debugger control
- **WHEN** AutoDebug runs capability tests
- **THEN** Xcode is marked `PARTIAL` or `UNSUPPORTED`, with a tool-inventory evidence note, not `PASS`.

#### Scenario: IDE-04-B — Positive PASS criteria met
- **GIVEN** a disposable test application is running under the IDE's own native debugger, with the adapter's backend version and OS recorded
- **WHEN** AutoDebug runs the full capability test, covering: correct IDE and debugger-session identification; confirmed breakpoint binding; confirmed debugger stop; successful stack inspection; successful supported variable inspection; successful supported stepping or continuation; correct handling of unsupported operations; and confirmation that no hidden second debugger session was created
- **THEN** the IDE/OS combination may be marked `PASS` for exactly the verified operations, with the test date, IDE/backend version and OS recorded in the compatibility ledger; a successful MCP connection or tool listing alone is insufficient for `PASS`.

### Requirement: IDE-05 — Compatibility report by OS
The project SHALL maintain a compatibility table for 11 intended combinations with test dates, exact versions, results, evidence and limitations.

#### Scenario: IDE-05-A — No Windows test infrastructure
- **GIVEN** only a Mac test host is available
- **WHEN** compatibility documentation is updated
- **THEN** Windows and Linux test cases remain `NOT_TESTED` or `BLOCKED` instead of green checkmarks.
