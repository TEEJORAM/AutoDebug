# Design

## Overview

```text
AI agent (Copilot / Cursor / Claude)
   │  MCP over stdio
   ▼
AutoDebug server ── plan, digest, policy, redaction, evidence, report
   │  JSON lines over 127.0.0.1, token-authenticated
   ▼
AutoDebug Bridge extension (inside the IDE window)
   │  VS Code API: tasks, debug, breakpoints, modal dialog
   ▼
IDE debug session ── DAP ──► debugpy / C++ debugger ──► the program
```

AutoDebug stays the policy owner. The bridge adds a second, independent check:
it performs only what the approval it showed the developer covers. Neither side
alone can run an unapproved operation.

## Flow for "Help to debug AutoDebugDemo"

| # | Agent calls | AutoDebug | Bridge / IDE |
|---|---|---|---|
| 1 | reads code itself | — | — |
| 2 | `create_case`, `stage_plan` | validate plan 0.3 | resolve launch config, task, breakpoint files; return their hashes |
| 3 | `request_approval` | send plan + digest | modal dialog in the IDE |
| 4 | `wait_for_approval` (repeat) | poll | developer clicks Approve; bridge records approval |
| 5 | `arm_case` | verify approval with bridge | run build task → add breakpoints → start debugging |
| 6 | `wait_for_stop` | poll, record evidence | DAP `stopped` event |
| 7 | `get_stack`, `list_variables`, `get_variables` | redact, record | DAP `stackTrace`, `scopes`, `variables` |
| 8 | `step` / `continue` (repeat 6–8) | count steps | DAP `next` / `stepIn` / `stepOut` / `continue` |
| 9 | `complete_case` | write report, export to project | stop session, remove breakpoints |

## Bridge protocol

Newline-delimited UTF-8 JSON over one TCP connection to `127.0.0.1:<port>`.

- First line from AutoDebug: `{"hello": "<token>", "protocol": 1}`. Wrong token
  → close without reply.
- Request: `{"id": 7, "op": "stack", "args": {...}}`.
  Reply: `{"id": 7, "ok": true, "result": {...}}` or
  `{"id": 7, "ok": false, "error": {"code": "...", "message": "..."}}`.
- Operations: `describe`, `resolve_plan`, `request_approval`, `approval_status`,
  `arm`, `stop_state`, `threads`, `stack`, `scopes`, `variables`, `step`,
  `continue`, `end`. Every operation after `describe` carries `case_id` and
  `approval_id`; the bridge checks them against its own record.
- Messages over 1 MiB are rejected; each request has a timeout.

Connection files live in `<evidence base>/bridges/<window-id>.json`. On Windows
`%LOCALAPPDATA%` is already private to the user; AutoDebug still runs its
existing privacy check on the folder and file before reading the token.

## Digest

`digest = sha256(canonical plan JSON + resolved launch configuration JSON +
resolved task definition JSON + sha256 of each breakpoint file)`. The bridge
recomputes it before `arm` and before every step; a mismatch is `PLAN_CHANGED`.

## Code layout

| Path | Contents |
|---|---|
| `src/autodebug/bridge/protocol.py` | message framing, limits, error mapping |
| `src/autodebug/bridge/client.py` | discovery, connection, `BridgeClient` |
| `src/autodebug/adapters/vscode_bridge.py` | `VSCodeBridgeAdapter` on the existing adapter protocol |
| `src/autodebug/approvals.py` | `APPROVED_BACKEND_KINDS = frozenset({"fake", "vscode-bridge"})`; bridge-issued approvals |
| `src/autodebug/evidence.py` | report sections, workspace export |
| `extensions/vscode-bridge/` | `package.json`, `extension.js` (no dependencies) |
| `src/autodebug/cli.py` | `bridge install`, doctor line |
| `tests/fixtures/fake_bridge.py` | Python fake that speaks the protocol |

The existing `VSCodeAdapter` (DebugMCP placeholder) stays as it is.

## Security notes

- Loopback only; never `0.0.0.0`; token required; no unauthenticated endpoint.
- Approval comes from a modal dialog the agent's tools cannot answer. Residual
  risk: synthetic input injection on the desktop (decision 1 in the proposal).
- DAP allowlist in the bridge; `evaluate` and friends are never forwarded.
- Reading variables makes the debugger format values, which can run a type's
  `__repr__`; this is the same as the IDE's Variables panel and is accepted.
- Build tasks and launch configurations run with the developer's rights; that
  is why both are shown in the dialog and hashed into the digest.

## Unknowns to confirm at runtime

- Cursor runs the extension and its Python debugger the same way as VS Code.
- The C/C++ extension's debugger is available in the developer's IDE (its
  licence limits it to Microsoft products; Cursor may need another debugger).
- MCP clients tolerate the polling pattern for approval within their tool-call
  timeouts.
