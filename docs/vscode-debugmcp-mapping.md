# VS Code ↔ DebugMCP adapter protocol mapping (T08)

**Status: `VSCodeAdapter` is now implemented** (`src/autodebug/adapters/vscode.py`), behind an injected `DebugMCPClient` abstraction, tested only against `tests/fixtures/fake_debugmcp_client.py` (a mock). **DebugMCP itself has still never been installed, contacted, or fetched from** — remains confirmed absent from this environment (filesystem check, 2026-10-22; see `docs/compatibility-ledger.md`). Every exact remote tool/schema name below remains unverified. This document no longer describes a future task — it describes the shape the real implementation actually took, and what remains unverified within it.

## Why this document exists

`src/autodebug/adapters/vscode.py` now implements every `BaseAdapter` operation by delegating to a constructor-injected `DebugMCPClient` (a `Protocol` AutoDebug defines itself — not DebugMCP's real wire shape). With no client attached (the default), every operation fails closed with `BACKEND_UNAVAILABLE`. This document records how `BaseAdapter`'s ten `CORE_OPERATIONS` ([src/autodebug/adapters/base.py](../src/autodebug/adapters/base.py) — `is_paused` was added this task, see "Genuine defect found and fixed" below) map onto `DebugMCPClient`'s methods, per the approach already named in [docs/ide-integrations.md](ide-integrations.md) section A and the public reference it cites (`https://github.com/microsoft/DebugMCP`).

**This mapping is still not verified against a live, installed instance of the extension.** Every "remote tool/capability name" below is therefore still marked `UNKNOWN — CONFIRM AT RUNTIME`, not a verified API name — `DebugMCPClient`'s method names (`start_or_attach`, `set_breakpoints`, ...) are AutoDebug's own abstraction, deliberately not presented as DebugMCP's real RPC method names, per `CLAUDE.md`: *"Never fabricate IDE APIs... debugger capabilities. Confirm available tools/capabilities at runtime."* A real implementation of `DebugMCPClient`, built against the actual extension once installed and Autodesk-approved, is separate, future, dependency-approval-gated work — not part of this task.

## Genuine defect found and fixed during this task

`src/autodebug/facade.py`'s `autodebug_wait_for_stop` already called `ctx.adapter.is_paused(...)` (added in T07's security review for cancellable polling) — but `is_paused` was never declared on `BaseAdapter`, only improvised on the `FakeAdapter` test double. A real adapter implementing the full, formal `BaseAdapter` contract would not have had this method. Fixed by adding `is_paused` to `BaseAdapter` (default `NotImplementedError` stub, like every other operation) and to `CORE_OPERATIONS` (now ten entries, not nine). `VSCodeAdapter.wait_for_stop` is implemented as a loop over this same primitive, so there is one source of truth for "is this session paused," not two. All 189 tests pass with this addition (166 prior + 23 new in `tests/test_vscode_adapter.py`) — purely additive, no existing adapter or test assumed exactly nine operations.

## Actual method-by-method mapping (as implemented)

| `BaseAdapter` method | `CORE_OPERATIONS` key | Risk tier | `DebugMCPClient` method it delegates to | Exact remote DebugMCP tool/schema name | Confidence |
|---|---|---|---|---|---|
| `list_sessions()` | `list_sessions` | Read-only | `client.list_sessions()` | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `launch_or_attach(target, reviewed_configuration)` | `launch_or_attach` | **Mutating — approval-gated** | `client.start_or_attach(target, reviewed_configuration)` | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `set_breakpoints(session, resolved_locations)` | `set_breakpoints` | **Mutating — approval-gated** | `client.set_breakpoints(remote_session_id, breakpoints)` — returns `BreakpointBindingResult` tuples directly (`RP-06`'s existing type, not a new one) | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `is_paused(debug_session_id)` | `is_paused` (new, added this task) | Read, bounded | `client.is_paused(remote_session_id)` | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `wait_for_stop(session, timeout)` | `wait_for_stop` | Read, bounded | Implemented as a loop over `is_paused`/`client.is_paused`, not a separate client call | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `get_stack(session, frame_limit)` | `get_stack` | Sensitive read | `client.get_stack(remote_session_id, frame_limit)` | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `get_variables(session, frame_id, selected_names)` | `get_variables` | Sensitive read | `client.get_variables(remote_session_id, frame_id, selected_names)` — returns raw, unredacted values; redaction happens once, at the facade layer | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `step(session, kind)` | `step` | **Mutating — approval-gated** | `client.step(remote_session_id, kind)` | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `continue_execution(session)` | `continue_execution` | **Mutating — approval-gated** | `client.continue_execution(remote_session_id)` | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |
| `disconnect(session)` | `disconnect` | Control | `client.disconnect(remote_session_id)` | `UNKNOWN — CONFIRM AT RUNTIME` | Unverified |

`DebugMCPClient`'s method names above (`start_or_attach`, `set_breakpoints`, ...) are AutoDebug's own `Protocol` ([src/autodebug/adapters/vscode.py](../src/autodebug/adapters/vscode.py)), not DebugMCP's real RPC names — the "Exact remote DebugMCP tool/schema name" column remains the honest, unverified unknown; a real `DebugMCPClient` implementation (future, separate, dependency-gated work) is what would actually know those names.

**Risk-tier note:** per `docs/mcp-contract.md`'s existing tool classification and `docs/security-gate-closure-proposal.md` §5, read-only/sensitive-read operations never arm, launch, bind, step, or continue anything — they carry materially lower risk than the three rows marked **mutating — approval-gated**, which are exactly what the T05 security gate (still OPEN/NOT APPROVED) blocks until it closes. Discovering *whether* DebugMCP supports a read-only row (via `probe_capabilities()`, once the extension is actually installed under Autodesk approval) does not require the gate to be closed first; attempting any mutating row does.

## Required test data for initial integration (once approved)

Any future real-backend test exercising this mapping must target a **disposable local application built solely for the test** (not a real Autodesk product, not customer code) and observe only **synthetic** variable/stack values the test itself creates — never real secrets, credentials, or customer-derived data. See `docs/security-gate-closure-proposal.md` §6 for the full rationale. This document does not itself run any such test.

## `GW-06` scenario mapping — implemented and proven against a mock

| Scenario | Implementation, proven in `tests/test_vscode_adapter.py::TestGW06ScenariosAgainstRouter` | Real-DebugMCP status |
|---|---|---|
| `GW-06-A` (launch, not running) | `VSCodeAdapter.launch_or_attach` → `client.start_or_attach`; `Router.arm_target` does not report ready until `set_breakpoints` confirms binding | Proven against `FakeDebugMCPClient` only |
| `GW-06-B` (attach, already running) | Same path, `process_running=True`; `SessionRef.pid` carries the approved target's PID | Proven against `FakeDebugMCPClient` only |
| `GW-06-C` (existing active session) | `Router.resolve()` (unchanged `router.py`) reuses the registered session; `test_scenario_c_existing_session_reused_no_hidden_second_session` confirms `client.start_or_attach_calls` stays at 1 | Proven against `FakeDebugMCPClient` only — real DebugMCP's `list_sessions` behavior for this case is still unverified |
| `GW-06-D` (unsupported) | `client.can_start_or_attach = False` + a `CapabilityReport` lacking `launch_or_attach` → `CAPABILITY_UNSUPPORTED`, zero calls reach the client | Proven against `FakeDebugMCPClient` only |

## Unknowns that remain unresolved (unchanged by this task — still require a real, approved DebugMCP connection)

1. **Exact remote tool/resource names and request/response schemas** — only discoverable by running a real `DebugMCPClient` implementation against the actual installed, approved extension.
2. **Session identity fields** — whether the extension exposes a stable per-window identifier and a usable "generation"/start-time equivalent. `VSCodeAdapter` now has a documented fallback (`RemoteSessionInfo.generation = None` → the adapter tracks its own counter), but whether DebugMCP itself can report one directly is still unknown.
3. **Breakpoint-binding confirmation shape** — whether a real bind failure is reported per-breakpoint or only in aggregate. `DebugMCPClient.set_breakpoints`'s signature already assumes per-breakpoint reporting (reusing `BreakpointBindingResult`); a real client may need to synthesize this from a coarser real response.
4. **Concurrency/session-serialization behavior** — still unknown whether DebugMCP itself serializes operations per session, independent of `SessionRegistry.lease()` (`GW-05`, unchanged).
5. **Expression-evaluation exposure** — still out of scope. `DebugMCPClient` has no `evaluate` method; none was added.
6. **"No hidden second debugger session" confirmation (`IDE-04-B` point 8)** — the mocked test proves `VSCodeAdapter`'s *own* logic never issues a second `start_or_attach` call when a session is already registered; it does not and cannot prove DebugMCP itself never opens a second session internally. That remains unverified until tested against the real extension.
7. **DAP-hosting CLI mode trap** — still unresolved; `DebugMCPClient` has no detection logic for which mode it's actually talking to, since there is no real connection yet to detect it on.

## What this task did and did not do

- **Did:** implement `VSCodeAdapter` fully, behind an injected `DebugMCPClient` abstraction; add the missing `is_paused` primitive to `BaseAdapter`/`CORE_OPERATIONS`; prove all of the above against a mock (`tests/fixtures/fake_debugmcp_client.py`); confirm the T05 authorization gate still refuses this adapter exactly as before.
- **Did not:** install the DebugMCP extension, any MCP SDK, or any other package; contact DebugMCP or any real debugger (confirmed absent from this environment); resolve any of the 7 unknowns above against real evidence; authorize real-backend operations — the T05 security gate remains **OPEN / NOT APPROVED**.
