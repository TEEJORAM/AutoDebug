# Requirements → tasks → verification traceability

A requirement is not “done” because code compiles; its **acceptance scenario must have a test/result**. IDs are defined in the four specs under `openspec/changes/autodebug-foundation/specs/`.

| Requirement(s) | Primary implementation tasks | Acceptance evidence |
|---|---|---|
| GW-01 | T01, T07 | MCP schema/client contract tests |
| GW-02 | T02, T08–T13 | Capability probe, unknown/unsupported handling |
| GW-03 | T03 | Unique session, PID reuse/staleness tests |
| GW-04 | T03, T08–T13 | Verified **native active IDE session** tests |
| GW-05 | T03 (lease primitive), **T15** (facade actually acquires it in `autodebug_step`/`autodebug_continue`) | Concurrent step/continue serialization test |
| GW-06 | T03, T07 (fake backend), T08–T12 (real IDE) | TC-21: launch, attach, existing-session reuse, unsupported-decline |
| RP-01 | T04, T14 | Pasted bug intake without Jira token |
| RP-02 | T14 | Source/API docs provenance; unknown method fallback |
| RP-03 | T04, T14 | API-vs-manual plan test |
| RP-04, RP-05 | T05 | Unapproved, forged approval, changed-script, fake-approval-replayed (RP-05-C) rejection |
| RP-06 | T04, T14 | Breakpoint-binding readiness gate |
| RP-07 | T14 | No in-app script injection; human-triggered Fusion script |
| RP-08 | T04, T14 | TC-23: `execution_confidence` labeling in evidence/report |
| DE-01 | T07, T14 | Real/native pause vs timeout |
| DE-02, DE-03 | T06, T07 | Selected values, truncation, quota and timeouts |
| DE-04 | T07 | Expression evaluation denied |
| DE-05, DE-06 | T06, T14, **T15** (evidence-ID citation integrity check) | JSONL/Markdown evidence and honest RCA against the `CONFIRMED`/`LIKELY`/`INCONCLUSIVE` bar |
| DE-07 | **T05** (authorization/target rejection — prohibited target denied before any debugger call) **and T06** (sanitization/storage mechanics — redaction, size caps) **as two distinct test suites**; one passing suite does not prove the other | No secret leaks (T06); no prohibited-target action reaches a backend (T05) |
| DE-08 | T06, T15 | Incomplete case recovery |
| DE-09 | T05 (approval/permission revocation), T06 (evidence retention), T07 (in-flight call interruption) — three distinct scopes, see `tasks.md` | TC-22: cancellation idempotency and safe-state tests |
| IDE-01, IDE-02 | T01, T02 | Five adapter declarations, OS matrix |
| IDE-03 | T08, T09, T12 | External bridge integrations with no copied sources |
| IDE-04 | T08–T12 | Real native session fixtures, stack/locals/step; `PASS` requires the `IDE-04-B` 8-point bar, not a bare connection |
| IDE-05 | T13, T15 | Signed/versioned 11-combination ledger |

Use test IDs `TC-01`–`TC-24` in `docs/test-plan.md`. As of `T15`, the full unittest suite (see `docs/status.md` for the exact, currently-verified count) is implemented and passing against fake/mock backends — real native-IDE verification for `IDE-04`/`IDE-05` remains outstanding per `docs/compatibility-ledger.md`.
