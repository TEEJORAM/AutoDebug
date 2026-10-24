# Known risks, blockers and assumptions

This is a **risk register**, not a collection of features silently promised to the developer.

| ID | Risk / assumption | Severity | Mitigation / proof required |
|---|---|---|---|
| R1 | Native debugger access differs from launching a fresh headless DAP session | High | For every IDE, demonstrate control of the visible **already-running** native session; otherwise `UNSUPPORTED` |
| R2 | Xcode installed release may lack advertised debugger MCP tools | High | Inspect `xcrun mcpbridge` capability list; log Xcode version and supported operations; no private IPC hacks |
| R3 | Cursor VS Code extension compatibility incomplete | Medium | Test DebugMCP extension in Cursor on each OS; add original minimal extension only when justified |
| R4 | CLion MCP feature/version/license policy differs by installation | Medium | Runtime tool inventory, real stop/stack/locals test; no hardcoded assumed operations |
| R5 | Internal Visual Studio bridge cannot be redistributed | High | Keep internal adapter isolated and gated; independently implement public API option if approved |
| R6 | Agent's shell access defeats naive same-user approval file | Critical | Trusted user-presence/OS permission boundary; independent security review before real debugger control; use fake backend meantime |
| R7 | Debugger output contains confidential data or credentials | Critical | Approved model usage, selected values only, redaction, output limits, private evidence paths |
| R8 | Generated Fusion API script changes customer document/data | High | Verify official API, use disposable design, review complete script, developer runs via existing UI |
| R9 | Startup breakpoints race with application startup | High | Verified pending/bound breakpoint, stop-at-entry when supported, refuse to claim success without symbols (see `GW-06` scenarios A–D and `docs/architecture.md` "Launch/attach limitations") |
| R10 | 11 IDE/OS cases cannot be tested from one Mac | Medium | Separate Windows/Linux test environments and versioned matrix; `NOT_TESTED` until validated |
| R11 | AI invents code locations, commands or root cause | High | Source SHA, runtime discovery, evidence citations; label confirmed/likely/inconclusive |
| R12 | External MCP and SDK changes break adapter compatibility | Medium | Version pins, capability probes, contract tests, upgrade changelog |
| R13 | Autodesk restrictions prevent code/Jira/data transfer to AI service | High | Check enterprise policy, approval and data classification before real internal use |
| R14 | Developer-reported script execution cannot be independently verified without instrumentation | Medium | Default `execution_confidence` to `developer_reported` (`RP-08`, ADR-009); consider an optional Fusion-side confirmation signal in a future change |

## Decision gate before T08–T12 (real IDE integration)

Do not enable live mutating debugger tools until: (1) approvals policy is reviewed; (2) user-visible target/plan binding is enforced; (3) low-privilege disposable C++ fixture works; (4) dependency and company policy reviewed; (5) actual tool API discovered. An adapter connecting successfully is not enough.

## Assumptions to verify in first review

- Developer has **Claude Desktop Code** capability enabled in Enterprise, not only general Claude Chat.
- Supported IDE versions exist on the target OS and expose required native debug APIs.
- One local AutoDebug process per developer computer is acceptable; multi-computer remote relay out of scope.
- Fusion Scripts and Add-Ins can execute the reviewed script for the chosen issue, or else manual route is used.
- Organization permits storing sanitized selected debugger values locally and passing them to the approved AI model.
