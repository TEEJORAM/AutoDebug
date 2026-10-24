# CLAUDE.md — AutoDebug project instructions for Claude Code

This file is instructions for **building AutoDebug**, not an instruction to run a debugging investigation on a real application.

## Project
- AutoDebug is a **new, independently written** Python MCP gateway. It federates access to already-running native IDE debugging sessions through verified adapters.
- Five IDE families in design scope: VS Code, Cursor, CLion (Windows/macOS/Linux); Visual Studio (Windows); Xcode (macOS). **Target support is not implemented support.**
- The AI client owns source/Jira/API-doc analysis and narrative reasoning. AutoDebug owns verified session routing, plan/approval enforcement, debugger operations and local evidence persistence.
- For Fusion reproduction use **only the existing Fusion scripting UI or already-approved supported facilities**. No new embedded server/helper or undocumented injection.
- Functional bugs first; performance profiling later.

## Source of truth and reading order
1. `README.md` and `docs/status.md` for orientation.
2. `openspec/changes/autodebug-foundation/proposal.md` for scope.
3. Relevant `openspec/changes/autodebug-foundation/specs/*/spec.md` for **required behavior**.
4. `openspec/changes/autodebug-foundation/design.md` and `docs/architecture.md`, `docs/mcp-contract.md` for design.
5. `openspec/changes/autodebug-foundation/tasks.md` for the currently approved task.
6. `docs/security.md` and `docs/test-plan.md` before edits to execution, approvals, or captured data.

Keep this file short; open the other Markdown docs only when relevant to the current task.

## Mandatory spec-driven process
- **Do not write application code at the first session.** First review the proposed specs, identify unknowns, and request explicit human sign-off on the foundation proposal/design.
- After approval, implement **only the named task** in `tasks.md`, in a small change. Never silently expand scope or check off work not completed.
- For every task: identify linked requirement IDs, state a brief approach, write/update tests, implement, run checks, report observed results, then update `tasks.md` and `docs/status.md`.
- For material scope/behavior changes, write a **new change proposal / requirements delta / design / tasks**, obtain approval, then code. Keep specs and code synchronized.
- A broken or unavailable integration is `UNSUPPORTED` or `UNAVAILABLE`, not an invented success.
- Never fabricate IDE APIs, Xcode or CLion tool names, debugger capabilities, test runs, data, commits or Jira access. Confirm available tools/capabilities at runtime.

## Safety, originality, and approvals
- Never copy, fork, vendor, or repackage Microsoft DebugMCP source into AutoDebug. Treat an installed DebugMCP extension as an **external MCP server** when approved; use public protocols and original adapter code.
- Obtain Autodesk approval before installing any third-party agent/MCP package or sending company data to it; respect all enterprise policy settings.
- Never connect a debugger to production processes or customer data by default. No secrets in tool arguments, logs or test fixtures.
- Do not assume an AI tool call means **human approval**. Approval must come from a distinct local trusted user interaction, bound to a plan digest, script hash, target identity and expiration.
- Do not launch/attach, arm breakpoints, step/continue, evaluate expressions or run reproduction without the required approval. A changed plan/script invalidates prior approval.
- Default to loopback-only local access and least-privilege operations; never open an unauthenticated debug endpoint to a network.
- Expression evaluation may have side effects: deny by default until separately specified, reviewed and tested.

## Engineering conventions once approved
- Python 3.11+ baseline is **proposed**, not yet validated against Autodesk toolchain; use typed interfaces, stdlib where sufficient, dependency injection and structured errors.
- One adapter protocol, separate backend implementations, mock/fake backend for deterministic tests.
- Session identity must include host, IDE instance, backend session and process identity. No guessing by process name.
- Persist sanitized event evidence with stable IDs. Root-cause reports must distinguish `confirmed`, `likely` and `inconclusive` findings.
- Pin and review dependencies before adding; do not install globally without user approval.
- Suggested future checks after scaffolding: `python -m pytest` and `python -m ruff check .`; these are **not yet configured or runnable**.

## Response template for an implementation task
Summarize: (1) requirement IDs, (2) files planned/changed, (3) test results **actually run**, (4) limitations, (5) next task, (6) any decision needing developer review. Stop after one approved task.
