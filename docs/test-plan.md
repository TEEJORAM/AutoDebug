# AutoDebug — Test plan and definition of done

**Status (as of T15):** the deterministic test cases below (`TC-01`–`TC-24`) and many more are implemented and passing — `PYTHONPATH=src python3 -m unittest discover -s tests -v` runs the full suite (see `docs/status.md` for the exact, currently-verified count). All of it runs against fake/mock backends only; no real native IDE debugger has been contacted by any test in this repository, and the per-IDE integration layer (section 3 below) has not been run against a real IDE for any of the 11 target combinations — see `docs/compatibility-ledger.md`. Each acceptance scenario under `openspec/changes/autodebug-foundation/specs/` is a testable requirement.

## 1. Test layers

| Layer | Purpose | Must run before |
|---|---|---|
| Pure unit tests with fake backend | Models, session identity, plans, state machine, quota, errors | Every code review |
| MCP contract tests | Real tool registry/schema, fake backend interactions, unsupported results | Real IDE work |
| Approval and adversarial tests | Forged approval, mutated script, stale PID, unexpected concurrent operations | Any native debug mutation |
| Per-IDE integration | Real visible IDE native debugger, disposable C++ app, breakpoint/locals/step | Claiming a backend works |
| Reproduction workflow | API/manual plan and case evidence end-to-end | Product demonstration |
| Security and privacy | Token redaction, bounded dumps, local access, OS-level approval restrictions | Non-disposable targets |

## 2. Deterministic first-test cases (no native IDE)

| Test ID | Requirement | Input | Expected |
|---|---|---|---|
| TC-01 | GW-01 | Connect mock MCP client | Stable documented tool list |
| TC-02 | GW-02 | Missing Xcode on Linux | `NOT_APPLICABLE`, no attempt to run Xcode |
| TC-03 | GW-02 | Fake backend advertises no stack | `CAPABILITY_UNSUPPORTED` |
| TC-04 | GW-03 | Two sessions share process name | Explicit session selection required |
| TC-05 | GW-03 | PID reused and nonce changed | `SESSION_STALE`, zero backend mutations |
| TC-06 | RP-04 | Arm unapproved plan | `NOT_APPROVED`, zero mutations |
| TC-07 | RP-05 | Edit 1 character of reviewed script | `PLAN_CHANGED`, new approval needed |
| TC-08 | RP-05 | Agent supplies text `approved` | Rejected: no trusted developer approval |
| TC-09 | RP-06 | Fake debugger cannot bind breakpoint | No `ready to reproduce` status |
| TC-10 | RP-07 | `api_script` plan prepared | No automatic script execution from AutoDebug |
| TC-11 | DE-01 | No pause event | Bounded `TIMEOUT`, incomplete case |
| TC-12 | DE-02 | Giant nested object returned | Output capped/truncated/redacted |
| TC-13 | DE-03 | 21st step on 20-step scope | `POLICY_LIMIT` and no backend call |
| TC-14 | DE-04 | Evaluate expression | Denied in v1 |
| TC-15 | DE-05 | Successful fake case | Local sanitized JSONL + Markdown report |
| TC-16 | DE-06 | Null pointer only, no causal proof | RCA cannot be `CONFIRMED` (needs causal validation per the new bar); may be `LIKELY`/`INCONCLUSIVE` |
| TC-17 | DE-07 | Secret sentinel in debugger data | Sentinel absent from outputs/logs/case files |
| TC-18 | DE-08 | Backend dies mid-step | Case incomplete; never switches sessions |
| TC-19 | GW-05 | Concurrent step/continue | Commands serialized / controlled rejection |
| TC-20 | IDE-01 | New macOS checkout | Five adapter declarations, supported/unsupported honest |
| TC-21 | GW-06 | Fake backend: app-not-running / running-not-attached / existing-session / unsupported-config | Correct launch, attach, existing-session reuse, and `UNSUPPORTED` decline respectively; ready-to-reproduce only after bound confirmation |
| TC-22 | DE-09 | Cancel a case mid-`wait_for_stop`; cancel the same case twice | First cancel returns `CANCELLED` and interrupts the pending wait; second cancel returns the same `CANCELLED` status idempotently; fake app/session untouched |
| TC-23 | RP-08 | Fake case: developer reports script run, no instrumentation configured | Evidence/report mark `execution_confidence: developer_reported`, not independently verified |
| TC-24 | IDE-02, GW-02 | VS Code/Cursor/CLion's `probe_capabilities()`/`Router.arm_target` driven with `host_os` forced to each of Windows/macOS/Linux in turn, against their existing mocks | Identical `AVAILABLE`/`GW-06` behavior across all three — proves adapter *logic* has no OS dependency of its own; does not prove real Windows/Linux native-debugger behavior (`tests/test_cross_platform_certification.py`, T13) |

**Implementation rule:** add tests alongside each task, not a bulk test-writing phase at the end. A test is *passing* only when actually executed, with exit status/observed output recorded. Mark blocked OS test as `NOT_TESTED`.

## 3. Integration test scenario: disposable C++ application

Construct a tiny cross-platform C++ fixture with an intentional, deterministic calculation bug and separate startup breakpoints. Build and debug it normally inside each IDE. The fixture must contain **no Autodesk code, customer data, production tokens or confidential documents**.

For each IDE/OS:

1. Record OS version, IDE version, debugger and backend MCP version and extension settings.
2. Start the app using native debugger; confirm debugger window visibly owns session.
3. Probe adapter and enumerate unique session IDs.
4. Stage plan with a source breakpoint, exact reproduction steps and short budgets.
5. Show developer approval through trusted local mechanism (after required security review).
6. Bind breakpoint before reproduction and confirm actual bound status.
7. Hit breakpoint, read limited stack and two named locals, step over, continue.
8. Verify evidence file and final report; check no data leak and correct native session identity.
9. Exit/restart application; test stale session and reconnect safely.

## 4. Compatibility ledger — every combination starts untested

This table is a quick-glance summary only. [docs/compatibility-ledger.md](compatibility-ledger.md) is the authoritative `IDE-05` record (test dates, exact IDE/backend versions, evidence pointers, limitations per cell) — created during T08 Phase 1 preparation. Updated through T13: all five adapters are now implemented (mocked-only); every macOS/Windows cell reflects an actual evidenced finding from T08–T12, not a placeholder. Windows/Linux cells for VS Code/Cursor/CLion remain `NOT_TESTED` — no Windows or Linux host exists in this development environment (T13, 2026-10-22).

| IDE | Windows | macOS | Linux |
|---|---|---|---|
| VS Code | NOT_TESTED | BLOCKED | NOT_TESTED |
| Cursor | NOT_TESTED | BLOCKED | NOT_TESTED |
| CLion | NOT_TESTED | UNSUPPORTED | NOT_TESTED |
| Visual Studio (full IDE) | BLOCKED | N/A | N/A |
| Xcode | N/A | UNSUPPORTED | N/A |

Allowed test states: `PASS` (all native-session minimum ops, meeting the `IDE-04-B` 8-point bar: session identification, breakpoint binding, debugger stop, stack inspection, variable inspection, step/continue, unsupported-op handling, no hidden second session), `PARTIAL` (some work), `UNSUPPORTED`, `BLOCKED`, `NOT_TESTED`, `N/A`. Include dates, test evidence and backend versions next to any later change in status. A connection/ping alone never counts as `PASS`.

## 4a. Reproducible Windows/Linux certification procedure (T13)

This development environment is macOS-only — there is no Windows or Linux host to run any of the steps below. This procedure exists so that whoever next has access to a real Windows or Linux machine can actually certify VS Code, Cursor, and CLion there, using the same adapters, fixtures, and acceptance bar already built and reviewed (T08–T12), without re-deriving the approach. Running this procedure is what turns a `NOT_TESTED` cell in `docs/compatibility-ledger.md` into real evidence — it does not itself produce any evidence, and nothing in this repository claims it has been run.

**Prerequisites before starting:**
1. A real Windows or Linux machine, with the target IDE (VS Code, Cursor, or CLion) actually installed — confirm the exact IDE version first (`code --version`, `cursor --version`, or the JetBrains Toolbox/about dialog for CLion).
2. For VS Code/Cursor: confirm whether the Microsoft DebugMCP extension (or Cursor's own equivalent, if one exists by then) is installed and registered — the same checks already run on macOS in T08/T09 apply identically: inspect the extensions directory and any `mcp.json`-equivalent config for a registered debugger-capable MCP server. Do not assume parity with the macOS findings recorded in `docs/compatibility-ledger.md` — check independently, per `docs/ide-integrations.md` section B's explicit warning.
3. For CLion: confirm the JetBrains built-in MCP server's actually advertised debugger tools at runtime — do not assume the tool names used anywhere in this codebase are correct; `src/autodebug/adapters/clion.py`'s `CLionDebugClient` `Protocol` is AutoDebug's own abstraction, not a verified real schema.
4. Autodesk policy approval to install whatever extension/bridge is required — not something this procedure grants; confirm separately first (see `docs/status.md`'s blockers list).
5. **The T05 real-debugger security gate remains OPEN / NOT APPROVED.** This procedure covers steps 1–3 below (discovery/capability-probing only) without needing the gate to close. Steps 4+ (any real `launch_or_attach`/breakpoint/step/continue call) require the gate to be closed first — do not attempt them under this procedure alone.

**Procedure (per IDE):**
1. Build a real `<Vscode|Cursor|CLion>DebugClient` implementing the adapter's existing `Protocol` (already defined in `src/autodebug/adapters/{vscode,cursor,clion}.py`) against the real extension/bridge discovered above. Do not modify the `Protocol` itself without a reviewed design change — if the real tool's shape doesn't fit, that mismatch is itself a finding to record, not something to silently paper over.
2. Run the adapter's existing mocked test suite (`tests/test_{vscode,cursor,clion}_adapter.py`) unmodified against the new real client, by substituting it for the fake fixture in a throwaway local script (not a repository change) — this sanity-checks the real client satisfies the same `Protocol` shape the mock does, before trusting any further result.
3. Call `probe_capabilities()` with the real backend and `host_os=platform.system()` (no override needed — this is now the real host). Record the exact reported `CapabilityState` per `CORE_OPERATIONS` operation. This alone is **read-only** and does not require the T05 gate.
4. **Only once the T05 gate has a reviewed, approved path to closure for this backend** (see `docs/security-gate-closure-proposal.md`): exercise the full `IDE-04-B` 8-point bar against a disposable test application (never a real Autodesk product, customer code, or customer data) — session identification, breakpoint binding, debugger stop, stack inspection, variable inspection, step/continue, unsupported-op handling, and explicit confirmation no hidden second session was created.
5. Record the result in `docs/compatibility-ledger.md`: exact test date, exact IDE/backend version, which of the 8 points passed, a pointer to evidence, and any limitation found. `PASS` requires all 8; anything less is `PARTIAL` with the specific gaps named. A successful connection or tool listing alone is never `PASS` (`IDE-04-B`).

## 5. Root-cause report quality test

Provide an example case with incomplete evidence. The report must say `LIKELY` or `INCONCLUSIVE`, cite events by ID, note alternative explanations and recommend a verification test. Provide another case with a controlled reproduction **and** a differentiating fix test (or equivalent causal validation) to permit `CONFIRMED` — per `DE-06`, a single breakpoint hit never qualifies on its own.

## 6. Before merging a PR

- [ ] Linked requirement ID and spec version noted in PR
- [ ] Review of behavior change happened **before** coding
- [ ] Tests for acceptance scenarios exist and ran successfully
- [ ] No unreviewed dependency, license, external process or token usage
- [ ] Relevant adapter compatibility status updated (including NOT_TESTED)
- [ ] Docs, tasks and `status.md` reflect actual behavior
