# Requirements traceability and status

Requirement IDs are defined in `openspec/changes/autodebug-foundation/specs/`.
A requirement counts only when its acceptance scenario has a test that ran.

**Status key:** IMPLEMENTED = gateway mechanism and fake-backend acceptance
behaviour work (not native certification). PARTIAL = depends on a native
backend, client or policy that is not available. BLOCKED = external proof or
authorization missing.

| ID | Status | Tasks | Evidence (tests) | Remaining boundary |
|---|---|---|---|---|
| GW-01 | PARTIAL | T01, T07 | MCP contract and server tests | Native routing blocked by the T05 gate |
| GW-02 | IMPLEMENTED | T02, T08–T13 | Capability probing, unknown/unsupported handling | Real inventories need installed backends |
| GW-03 | PARTIAL | T03 | Unique session, PID reuse, staleness | No certified native identity provider |
| GW-04 | PARTIAL | T03, T08–T13 | No hidden/headless fallback | Live IDE session proof unavailable |
| GW-05 | IMPLEMENTED | T03, T15 | Concurrent step/continue serialization, bounded waits | No forced native interruption claimed |
| GW-06 | PARTIAL | T03, T07, T08–T12 | TC-21: launch, attach, reuse, unsupported | Native launch/attach APIs unavailable |
| RP-01 | IMPLEMENTED | T04, T14 | Bug intake without Jira credentials | — |
| RP-02 | PARTIAL | T14 | Source revision and reviewable plan | Source/API analysis belongs to the client |
| RP-03 | IMPLEMENTED | T04, T14 | API-script vs manual plan, full script hash | — |
| RP-04 | PARTIAL | T05 | Unapproved/forged approval refused | No OS-trusted local review surface |
| RP-05 | BLOCKED (real use) | T05 | Changed script, replayed fake approval (RP-05-C) | Boolean cannot attest human presence |
| RP-06 | PARTIAL | T04, T14 | Exact binding set required before ready | Real binding proof unavailable |
| RP-07 | PARTIAL | T14 | No script-run or injection tool | Developer runs scripts in the app's own UI |
| RP-08 | IMPLEMENTED | T04, T14 | TC-23: `execution_confidence` labels | No instrumentation; never claims verified |
| DE-01 | PARTIAL | T07, T14 | Stop identity, timeout, re-stop rejection | Native stop source unverified |
| DE-02 | IMPLEMENTED | T06, T07 | 1–50 frames/names, recursive bounds, redaction | — |
| DE-03 | IMPLEMENTED | T06, T07 | Step/time/data budgets, bounded waits | — |
| DE-04 | IMPLEMENTED | T07 | No evaluation tool; conditional breakpoints refused | — |
| DE-05 | IMPLEMENTED | T06, T14, T15, W1–W3 | JSONL ledger and three artifacts; escape tests on POSIX and Windows | — |
| DE-06 | IMPLEMENTED | T06, T14, T15 | Owned citations; CONFIRMED needs causal validation | Truth of the client's narrative is the client's |
| DE-07 | PARTIAL | T05, T06 | Prohibited targets refused (T05); no secret leaks (T06) | Host check is a naming heuristic |
| DE-08 | IMPLEMENTED | T06, T15 | Incomplete recovery with partial evidence | — |
| DE-09 | IMPLEMENTED | T05, T06, T07 | TC-22: idempotent cancel, revoked scope, retained evidence | Native detach unproven |
| IDE-01 | IMPLEMENTED | T01 | Five adapters, honest unavailable results | — |
| IDE-02 | IMPLEMENTED | T02 | OS applicability matrix | — |
| IDE-03 | PARTIAL | T08, T09, T12 | Original injected clients, nothing vendored | Real backend APIs/terms need approval |
| IDE-04 | BLOCKED | T08–T12 | Mock suites only | No `IDE-04-B` 8-point native certification |
| IDE-05 | IMPLEMENTED | T13, T15 | 11-cell ledger with honest states | Cells stay NOT_TESTED/BLOCKED until real tests |
| CLI-01–06 | IMPLEMENTED | `cli-usability` C1–C6 | `tests/test_cli.py`, `tests/test_server.py` | — |
| WIN-01–03 | IMPLEMENTED | `windows-evidence-storage` W1–W4 | `tests/test_windows_evidence.py`, `tests/test_publication_evidence.py` on Windows CI | — |

Test-case IDs `TC-01`–`TC-24` are defined in [test-plan.md](test-plan.md).
`CLI-*` requirements are in `openspec/changes/cli-usability/spec.md`; `WIN-*` in
`openspec/changes/windows-evidence-storage/spec.md`.
