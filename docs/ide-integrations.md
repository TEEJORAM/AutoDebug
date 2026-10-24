# IDE integrations

**VS Code and Cursor are driven through the AutoDebug Bridge**, an original
extension that uses only the public VS Code extension API and the Debug Adapter
Protocol (`src/autodebug/bridge/extension/`, `VSCodeBridgeAdapter`; see
[ide-debug-bridge](../openspec/changes/ide-debug-bridge/design.md)). It took the
"original narrowly scoped extension" route below instead of DebugMCP.

The five client-backed adapters below cover 11 IDE/OS targets. Each delegates
to an injected, IDE-specific client (`ClientBackedAdapter` in
`src/autodebug/adapters/base.py`) and is tested only against mocks. Support is
earned through real tests; see the [compatibility ledger](compatibility-ledger.md).

## Target matrix

| IDE | Windows | macOS | Linux | Proposed approach |
|---|---|---|---|---|
| Visual Studio Code | Target | Target | Target | Connect to separately installed **Microsoft DebugMCP extension** (not vendor/fork its source); add original narrowly scoped extension only if documented APIs permit missing capabilities |
| Cursor | Target | Target | Target | Probe VS Code-compatible extension behavior **inside Cursor**; conditional DebugMCP external integration; do not assume Cursor exposes every VS Code API |
| CLion | Target | Target | Target | JetBrains built-in MCP debugger tools where supported and enabled |
| Visual Studio (full IDE) | Target | Not applicable | Not applicable | An internal Autodesk-approved bridge, or separately reviewed native Windows bridge for public distribution |
| Xcode | Not applicable | Target | Not applicable | `xcrun mcpbridge` via Apple-supported Xcode tools; probe actual debugger tool inventory |

**Total 11 IDE/OS targets.** Distinguish editor operating-system availability from native MCP/debugger integration availability. The backend may depend on version and feature flags.

## A. VS Code

- External integration: [microsoft/DebugMCP](https://github.com/microsoft/DebugMCP), installed separately after appropriate approval.
- AutoDebug connects to its published **extension** MCP service when controlling the *visible* VS Code session. The standalone DebugMCP CLI is an **independent DAP-hosting mode** and does not guarantee native IDE-session control.
- Must probe: process/session enumeration, breakpoint binding, stack/variables, stepping, multiple windows, disconnect and tool schemas.
- If critical session/stack operations are missing, use a **new independently written** minimal VS Code extension based on public VS Code Debug API, after verifying the capability is actually exposed. No source copying.

## B. Cursor

- Reuse the **same adapter abstraction**, but test Cursor's extension host separately.
- Cursor's API for registering MCP servers is not a guarantee of live-debugger access. A Cursor extension must actually expose the native debugger via supported APIs.
- If DebugMCP extension is unavailable or incompatible, return `UNAVAILABLE`, and document the needed public-API companion work. Do not silently substitute a new headless session when the user requested the active Cursor debugger.

## C. CLion

- Use JetBrains' supported built-in MCP server and its **advertised** debugger tools. Do not hardcode `xdebug_*` names until runtime discovery confirms them.
- Confirm current tool supports stack, variables, breakpoints, current session, stepping and status; record gaps.
- Authentication/permissions and session IDs must be validated against actual JetBrains configuration; do not assume a generic DAP socket exposes CLion's active session.

## D. Visual Studio (Windows only)

- Evaluate any existing internal Autodesk bridge separately with its maintainers' permission and organizational approvals.
- For a public/external version, use a **new independently written** Visual Studio SDK/EnvDTE adapter; never package or disclose Autodesk internal code without authorization.
- Check: attach/launch to the right PID, source/line breakpoints and symbols (PDB), local values, stack, multi-instance and debugger event notifications.
- Native Visual Studio is not VS Code and does not run on macOS/Linux.

## E. Xcode (macOS only)

- Apple documents external agent access through **`xcrun mcpbridge`**, with an Xcode setting to allow external agents.
- Do not claim **all** Xcode versions expose the debugger tools; enumerate advertised MCP tools and probe a disposable example project. LLDB outside Xcode is **not** the same thing as controlling Xcode's active native debug session.
- Verify: Xcode release/tool inventory, active project, paused debugger availability, stack/variables, breakpoint changes, stepping, multiple Xcode windows, tool consent.
- If `mcpbridge` exposes only source/project tools on the installed version, return `UNSUPPORTED` for missing operations. Do not use undocumented Xcode IPC/private APIs as a shortcut.

Apple setup reference: https://developer.apple.com/documentation/xcode/giving-external-agents-access-to-xcode

## Adapter-to-client mapping (all adapters)

Client method names are AutoDebug's own `Protocol`, not any IDE's real tool
names. Every real tool/schema name is **unknown until confirmed at runtime**
against an installed, approved backend.

| Adapter operation | Client call | Risk tier |
|---|---|---|
| `list_sessions()` | `list_sessions()` | Read |
| `launch_or_attach(target, config)` | `start_or_attach(target, config)` | Mutating, approval-gated |
| `set_breakpoints(session, locations)` | `set_breakpoints(id, breakpoints)` → per-breakpoint `BreakpointBindingResult` | Mutating, approval-gated |
| `is_paused(id)` / `wait_for_stop(session, timeout)` | `is_paused(id)` (wait loops over it) | Read, bounded |
| `get_stack(session, limit)` | `get_stack(id, limit)` | Sensitive read |
| `get_variables(session, frame, names)` | `get_variables(id, frame, names)` (raw; the facade redacts) | Sensitive read |
| `step(session, kind)` / `continue_execution(session)` | `step(id, kind)` / `continue_execution(id)` | Mutating, approval-gated |
| `disconnect(session)` | `disconnect(id)` | Control |

With no client attached, every operation fails with `BACKEND_UNAVAILABLE`.
When a client reports no session generation, the adapter keeps its own
per-session counter for GW-03 identity checks. There is no `evaluate` call.

Open questions to settle against a real backend (VS Code/DebugMCP first):
exact tool names and schemas; stable window/session identifiers; whether
binding failures are reported per breakpoint; whether the backend serializes
operations; whether it ever opens a hidden second session (`IDE-04-B` point 8);
and how to detect DebugMCP's standalone DAP-hosting mode.

## Rules for adapter changes

- Every adapter change needs a **contract test** with the common AutoDebug adapter protocol.
- Add a version-specific **integration test** on the applicable OS; cannot claim coverage by running unit tests on only macOS.
- Update `docs/test-plan.md`, `docs/traceability.md`, the compatibility ledger and the relevant spec when behavior changes.
- Do not mark an adapter production-ready if it merely connects to MCP but cannot control an **already-running** native debugger.
