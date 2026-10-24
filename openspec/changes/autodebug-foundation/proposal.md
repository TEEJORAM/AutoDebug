# Foundation proposal — AutoDebug

**Change:** `autodebug-foundation`\
**Status:** DRAFT — needs developer review / approval before coding\
**Owner:** Developer\
**Updated:** 2026-10-22

## Problem

AI assistants can read code and help interpret bug reports, but their ability to **safely and consistently investigate a breakpoint in the developer's existing native IDE** differs by IDE and OS. Individual debugger MCP integrations exist, but they expose different commands, session identifiers, tool availability and safety models. Reproduction and evidence collection can remain manual and difficult to verify.

## User-visible outcome

A developer provides a Jira issue (through an approved tool) or bug description. The AI analyzes the description, code and available app API documentation. It proposes relevant breakpoints and either:

- an **entire, readable application API script** for reproducing the issue, when the existing application API supports the steps; or
- exact **manual reproduction steps**, when the API is missing or insufficient.

Before modifying a debug session, the developer reviews the full plan, script and target and explicitly approves. AutoDebug launches or attaches to the app **if supported and approved**, verifies breakpoint binding, and waits for the developer to run the script through the app's existing mechanism or perform manual steps. Once paused, AutoDebug exposes small, selected debugging observations; the AI investigates incrementally. The final report returns to the IDE and saves redacted JSONL + Markdown evidence locally.

## Scope — approved target architecture, not yet built

- Five adapters from the outset: VS Code, Cursor and CLion on Windows/macOS/Linux; Visual Studio on Windows only; Xcode on macOS only (**11 IDE/OS target cases**).
- One original Python MCP gateway and versioned, consistent tool/adapter contracts.
- Existing native debugger session must be used. A newly launched independent headless DAP session is not a silent substitute.
- Reuse external IDE MCP servers when installed and approved. No copying of Microsoft DebugMCP or any internal Autodesk bridge source.
- Application startup/attach can be agent-requested **after developer review**, conditional on backend capability.
- Jira and product API documentation access through **approved external agent connectors**; support pasted issue text when unavailable.
- Full script/manual plan review and independent human approval, verified native session identities, bounded investigation.
- Evidence and evidence-linked root cause report; careful use of `CONFIRMED`, `LIKELY`, `INCONCLUSIVE`.
- Cross-platform application **functional bugs** only in foundation. Performance profiling in future change.

## Explicit non-goals for this change

- A new debugger engine, IDE replacement, generic headless debugging product or debugger protocol implementation.
- New Fusion runtime helper / embedded HTTP server / unapproved application script injection.
- Agent automatically clicking `Run` in Fusion without a separately verified approved existing mechanism: **human executes the reviewed script through the Fusion Scripts and Add-Ins UI** in v1.
- Any remote multi-machine relay, production process debugging, arbitrary memory dumping, unrestricted expression evaluation, automatic code modification or Jira updates.
- Guaranteeing every native IDE exposes all operations today. Unsupported features must be reported honestly.
- Full performance profiling or GPU profiling.

## Delivery approach

All five adapters exist as **contract-compliant modules** from the start, initially returning honest unsupported states. Core components and tests use a **fake debugger backend**. Gradually validate real native IDE integrations, first on macOS where the developer works, then Windows and Linux in supported environments.

## Evidence that the project is useful

Run the same reproducible C++ bug with direct IDE MCP use vs AutoDebug. Measure: correct process targeted, breakpoint binding success, reproducibility, human interactions, investigation time, misleading results, recovery from disconnect, quality of evidence report. Mark anything not measured as not measured.

## Success definition

- A new contributor can use `CLAUDE.md` + the approved specs to implement one task without guessing scope.
- Unit and contract tests enforce session and approval safety before real debugger integration.
- At least one complete **approved** bug-to-report demonstration is shown against a real native IDE debugger, then the five adapter integrations are separately capability-tested.
- The final compatibility matrix records `PASS`, `PARTIAL`, `UNSUPPORTED`, `BLOCKED`, or `NOT_TESTED` for each of the 11 targets; no unsupported claims.

## Dependencies and risk

Company approval may be needed for IDE tools, third-party MCP servers, Claude model/data routing, and license review. Some IDE APIs may not expose active native debugger sessions or necessary events. An AI agent with unrestricted local shell access can circumvent naive same-user approval files; real deployment requires enforced permission and human-presence controls beyond instructions alone. See `docs/security.md` and `docs/risks.md`.

## Human approval record (fill after review)

- [ ] Product outcome and non-goals approved
- [ ] Security and data-handling plan reviewed
- [ ] Five IDE target matrix acknowledged as aspirational until tested
- [ ] Implementation tasks and acceptance criteria approved
- Reviewer / date / approved commit SHA: **Not yet approved**
