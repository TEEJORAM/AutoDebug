# Current AutoDebug project status

**As of:** 2026-10-24
**Milestone:** Technical implementation frozen and committed; publication **BLOCKED**
pending the four documented external decisions. The current full suite passed **468 tests** on
macOS with Python **3.14.7** and **3.12.13**. Python 3.11 is unavailable locally;
Linux/Windows and GitHub Actions were not run. All five adapters remain
mock-validated only. Dependency-free MCP stdio and the isolated synthetic backend
are operational; there is no native debugger certification.
The real-debugger gate remains **OPEN / NOT APPROVED**.
**Approval status:** `G00` **APPROVED**, verbatim: *"I approve G00 for AutoDebug. Proceed with T01."* (2026-10-22). `T01` committed as `a744b10` + `2dd66cf`; `T02` as `357b40c`; `T03` as `bdbce23`; `T04` as `b0f47be`; `T05` as `a3dcdd3`; the project rename (DTunnel → AutoDebug) as `d22d392`; `T06` as `a4cf165`; `T07` as `3d8cb72`; `T08` as `a559400`; `T09` as `21c7bc0`; `T10` as `2dfe7cb`; `T11` as `26fd8d2`; `T12` as `302a50a`; `T13` as `884bae4`; `T14` as `3475ad5`. **T15 was approved for work this session, but its checkbox remains UNCHECKED** because independent human reviewer sign-off and approved case-data handling are outstanding. See `docs/release-readiness-checklist.md` for current blockers.
**Requirement count:** 28 requirements, 41 acceptance scenarios (unchanged).  
**Workspace:** authorized company checkout. Internal repository identifiers and
workstation locations have been generalized for publication preparation; their
historical presence and Autodesk-related provenance remain review obligations.
No remote, ownership record, or Git history was changed.
**Current implementation authorization:** the developer explicitly authorized a
complete technical closure pass on 2026-10-24, including outstanding transport,
script/stop integrity, bounded operations, packaging and release documentation;
see `openspec/changes/technical-closure/`. This supersedes the previous
single-task implementation boundary, not native/publication restrictions.
**Next permitted activity:** final documentation/content cleanup, one local
finalization commit and STOP; publication only after the
[four external decisions](ossa-legal-approval-request.md). No implementation,
native integration or further audit cycle is authorized. Historical T15 human
sign-off is not manufactured by this publication-finalization scope.

## Frozen implementation and publication finalization (2026-10-24)

- Implementation commit: `736cc154dda574a54bfc4f42ebf16d6980d71ac1`,
  preserving all 63 intended files (37 modified, 26 added).
- Its full suite ran once: 468 tests in 3.512s, OK; cached whitespace passed.
- Current-file focused content check: no actual employee email, internal URL,
  workstation path, genuine credential or private operational snapshot found.
  Public vendor URLs, synthetic markers and legitimate provenance retained.
- Finalization changes documentation only. No code/tests/CI/dependencies,
  native-debugger restrictions, attribution or ownership records are changed.
- Existing history stays private and untouched. The
  [publication procedure](installation.md#publication-after-permission) requires
  approved exact-artifact/destination/history treatment before any upload.

## Historical comprehensive closure verification (pre-commit snapshot)

- Requirements: all 28 foundation IDs dispositioned individually in the
  [closure report](technical-closure-report.md); no deferred/native requirement
  is silently counted as passed. The [approved delta](../openspec/changes/technical-closure/spec.md)
  covers changed behavior and preserved fake-only authorization.
- Exact candidate boundary: **63 changed files = 37 modified tracked +
  26 untracked**; no tracked deletions. **98 current files = 72 tracked +
  26 untracked**, classified **65 PUBLIC-SAFE / 33 owner/legal review** with
  no missing/duplicate/extra current-file entries. Pre-existing work is retained.
- Full command `PYTHONPATH=src python3 -m unittest discover -s tests -v`:
  **468 tests in 3.535s, OK**, Python **3.14.7**, macOS.
- Full command `PYTHONPATH=src python3.12 -m unittest discover -s tests -v`:
  **468 tests in 3.455s, OK**, Python **3.12.13**, macOS.
- Starting baseline reconstructed from HEAD plus the prior exact preparation
  diff: **425 tests in 1.872s, OK**. New selected compatible regressions:
  prior source **5 tests / 9 assertion failures / 0 errors**; current source
  **5 tests, OK**. This replaces the initial TTL-import-error attempt as proof.
  No new-model import errors are counted as regression efficacy.
- Added **43 tests**: **24** technical-closure and **19** transport/build tests.
  Full suites include real subprocess MCP handshake/cancellation/synthetic
  completion, offline wheel record/metadata checks, isolated import and source
  rebuild, without dependency installation or native contact.
- Additional red/green lifecycle checks proved cancellation waited 3.008 seconds
  behind value rendering and released ownership before detach completed. Moving
  rendering outside the state lock, rechecking the stop afterward, retaining
  ownership through detach and quarantining in-flight cancellation repaired both.
  Late-launch cleanup now also proves no registered/authorized orphan survives.
- Configured Windows contract/binding/build selector: **127 tests in 0.342s,
  OK locally on macOS**, explicitly not Windows execution. Linux/Windows/CI and
  Python 3.11 runtime remain unexecuted/unavailable.
- `python3 -m compileall -q src tests build_backend.py`, `git diff --check`
  and `git diff-tree --check --root -m -r HEAD`: passed. All **54** current
  Python files parse with Python 3.11 grammar; this is NOT 3.11 runtime proof.
  Pylance workspace diagnostics: no severity-1/2 diagnostics; informational
  diagnostics remain, not a configured standalone type-check certification.
- Current-file scan: no employee addresses or workstation paths found;
  retained Autodesk URL is public Fusion API help. Credential-shaped strings
  are synthetic test fixtures, not identified actual credentials. Pattern scans
  cannot certify ownership or absence of all confidential data.
- HEAD remains `0f3131af79f34270043860cf7a4d0283d49825ad` (18 commits /
  165 trees / 186 blobs). Latest all-ref inventory: **32 commits / 210 trees /
  259 blobs = 501 objects**, including environment checkpoint references.
  All reachable blobs/commit metadata scanned locally; historical internal
  locators, employee metadata and workstation paths remain. No agent commit,
  remote/ref change or history rewrite was performed.
- Native approval remains **OPEN / NOT APPROVED**. Hung calls have bounded
  facade waits, cancellation/quarantine and late cleanup, not forced native
  interruption. Windows secure evidence fails closed. Publication, license,
  ownership/OSSA/Legal, independent human and data-policy approvals remain
  external. See the [concrete approval request](ossa-legal-approval-request.md).

## Historical strict final review and repair verification (superseded)

- The green 38-file/405-test preparation patch failed adversarial review.
  The developer approved all confirmed follow-up repairs and their bounded
  design. Twenty new strict-review tests now cover those boundaries.
- Current exact boundary: 39 files (28 modified tracked + 11 untracked),
  83 current files; HEAD remains `0f3131af79f34270043860cf7a4d0283d49825ad`.
  Initial pre-existing preparation work is retained, not attributed entirely
  to this follow-up.
- Required full suite: 425 tests in 1.967s, OK (Python 3.14.7); 425 tests in
  1.965s, OK (Python 3.12.13). Both runs were on macOS. Python 3.11 unavailable.
- `compileall`, working-tree whitespace and configured commit-whitespace checks
  passed. Local Windows contract subset: 115 tests, OK; not Windows execution.
- Original 35 selected regressions: materialized HEAD produced 33
  assertion-failing tests / 58 failing assertions and subtests, zero errors,
  two already-green controls; current source passes all 35. The FIFO test was
  excluded only from the vulnerable run and passes in the current full suite.
- Follow-up fixes add exclusive session ownership/arming serialization,
  returned-target and late authorization checks, preserved existing sessions on
  rollback, total stack-tree limits and sensitive-name redaction, disconnect
  recovery, retryable atomic snapshots and honest completion artifacts.
- Corrected history scope: HEAD has 18 commits / 186 blobs / 165 trees;
  all refs have 30 commits / 241 blobs / 199 trees, including 12 non-HEAD
  checkpoint commits. Old 28-commit counts were an intermediate all-ref snapshot.
  History still contains private locators, workstation paths and employee
  metadata; no history/ref/remotes were changed.
- Publication and T15 remain BLOCKED. No real debugger, license, OSSA/Legal,
  security-policy or independent-human approval is implied. See the current
  [assessment](publication-readiness-assessment.md) and
  [83-file audit with 29 exact owner decisions](publication-content-audit.md).

## Initial preparation verification (2026-10-23; superseded snapshot)

- Requirements: RP-04/05, GW-03/05, DE-01/02/03/05/06/07/08/09; explicit read
  scopes and fail-closed unsupported evidence platforms were approved by the
  developer before implementation. See `openspec/changes/publication-hardening/`.
- Existing partial publication edits were preserved and integrated, not reverted.
  Baseline: 384 tests, 20 failures and 9 errors. New facade regressions initially
  ran 15 tests with 22 failing subtests/assertions and 1 error.
- Current suite: `PYTHONPATH=src python3 -m unittest discover -s tests -v`:
  **405 tests in 1.784s, OK** (Python 3.14.7).
  `PYTHONPATH=src python3.12 -m unittest discover -s tests -v`:
  **405 tests in 1.778s, OK** (Python 3.12.13).
- Configured Windows contract subset: **115 tests, OK**, executed locally on
  macOS only. Linux/macOS full-suite CI and Windows contract-only CI are
  configured, not executed. Windows secure persistence remains unavailable.
- `git diff --check` and `python3 -m compileall -q src tests` passed.
  Editor diagnostics reported no errors in the six changed production modules.
- Original HEAD evidence regressions: 14 tests, 29 failures, no timeout in the
  bounded run. The FIFO/nonregular-artifact test was excluded from that old-code
  run because the vulnerable open can block; the current full suite includes it.
- Intermediate all-ref history inventory: 28 commits, 197 blobs, 178 trees, no
  tags (403 objects); corrected current scopes are above. Historical internal locators, workstation paths and
  employee/commit metadata remain; current sanitation does not remove them.
- No commit, push, publication, repository creation, remote change, history
  rewrite, dependency installation or real debugger enablement was performed.
  No license or Autodesk OSSA/Legal/publication approval is asserted.
- Full findings, changed-file inventory, unresolved contract gaps and approvals:
  [publication assessment](publication-readiness-assessment.md) and
  [file classifications](publication-content-audit.md). T15 remains unchecked.

Everything below is historical evidence, not verification of the current tree.

## T15 implementation pass (historical; superseded by the final review update below)

**Approved scope (developer, verbatim):** *"I approve T15 — Security / Quality / Release Gate (`GW-*`, `RP-*`, `DE-*`, `IDE-*`) for AutoDebug."* Contract verification, security verification, T14-limitations disposition, CI, documentation audit, upgrade/rollback, license/dependency review, case-data handling review, release-readiness checklist, full regression, status updates — preserving the fake-only T05 gate, no real debugger contact, no unapproved dependencies, and leaving T15 unchecked pending independent reviewer sign-off.

**Three genuine production fixes in `src/autodebug/facade.py`, each narrowly scoped and regression-tested (`tests/test_t15_security_release_gate.py`, 9 tests):**
1. **`GW-05`** — `SessionRegistry.lease()` (T03) was never acquired by `autodebug_step`/`autodebug_continue`; two concurrent calls on the same session could race with zero serialization. Fixed: both now run inside `with self._registry.lease(ctx.session):`, failing closed with `POLICY_LIMIT` on contention. Proven with a real race window using a test-only blocking adapter, not just by inspection.
2. **`DE-08`** — approval expiration discovered mid-investigation did not label the case `INCOMPLETE`, despite `DE-08`'s own text naming "approval expiration" as a trigger and `docs/traceability.md` assigning `DE-08`'s acceptance evidence to T15 by name. Fixed with a new `_verify_approval` helper mirroring the existing `SESSION_STALE` handling — catches `APPROVAL_EXPIRED` specifically, calls the existing `_mark_incomplete`; every other authorization refusal is unaffected. 4 new tests cover step/continue expiration, arm-time expiration (confirmed unaffected — no session/evidence exists yet), and confirm scope-denial still never marks a case incomplete.
3. **`DE-06`** — "every conclusion SHALL cite stored evidence IDs" was never enforced; `autodebug_complete_case` accepted any caller-supplied `evidence_ids`, including fabricated ones or real IDs belonging to a *different* case (IDs are per-case sequential counters, so two cases' first records are each independently `"E0001"`). Fixed with a cross-check against the case's own recorded events before building the report. 3 new tests: fabricated ID rejected, a real-but-wrong-case ID rejected, a genuine ID accepted (positive control). One pre-existing test (`test_confirmed_without_causal_validation_is_rejected`) was updated to record genuine evidence first, since it would otherwise fail on the new check instead of the causal-validation bar it is actually testing — a corrected fixture, not a weakened assertion.

**Contract verification:** new `tests/test_t15_contract_conformance.py` (8 tests) pins the `ErrorCode`/`CaseState`/`EvidenceRecord`/`ExecutionConfidence`/`RootCauseConfidence` sets and the facade's 15-tool surface and response-envelope shape exactly against `docs/mcp-contract.md`/`design.md`. All 8 passed immediately — the implementation already matched; this adds a drift guard, it found no contract mismatch itself (the mismatches found were behavioral, listed above).

**Security verification:** confirmed all 6 `docs/security.md` acceptance gates (`SEC-01`–`SEC-06`) have existing test coverage — pointers added directly to `docs/security.md`. Confirmed `FakeAdapter.launch_or_attach_calls` stays `0` across every unapproved/forged/wrong-scope path. Confirmed `git diff --stat -- src/autodebug/approvals.py` is empty and `FAKE_BACKEND_KIND = "fake"` is byte-for-byte unchanged throughout.

**T14 limitations disposition:** (1) approval-expiration-incomplete — **fixed** (justified: `docs/traceability.md` names T15 for `DE-08`, fix is small and targeted). (2) `autodebug_get_stack` not persisting evidence — **documented only, not fixed**: no `IDE-04-B`/`DE-05`/`DE-02` scenario requires it, and `DE-06`'s bar is already satisfiable with variable-only evidence (T14 demonstrated this). Recorded, not silently expanded into new architecture.

**CI:** added `.github/workflows/tests.yml` (Python 3.11/3.12, zero dependencies, runs the full suite). **Not verified on an actual runner** — only the underlying command verified locally and repeatedly. Recorded honestly as unverified-in-environment, not claimed as a passing CI badge.

**Documentation audit — four stale claims corrected, no new unsupported claims introduced:** `README.md` ("no implementation has been built; G00 is NOT APPROVED" → corrected to reflect T01–T14 committed, gate still open); `docs/mcp-contract.md` ("NOT implemented" → corrected, with "not yet an MCP server" explicitly preserved, plus two new notes: `SENSITIVE_OUTPUT_BLOCKED` is reserved/unused, and the evidence example's `"paused"` `event_type` is illustrative only); `docs/test-plan.md` and `docs/traceability.md` (both claimed "no tests executed/implemented" → corrected). `docs/compatibility-ledger.md` reviewed, found already accurate.

**Upgrade/rollback:** new `docs/upgrade-rollback.md` — plain Git for the source tree (no package/release artifact exists); confirmed zero migration code exists anywhere (`grep -rln "migrat" src/autodebug/*.py` → empty) and confirmed case data is never stored inside the repo, so a source rollback never touches it. Any future schema migration is explicitly deferred to a separate reviewed change.

**License/dependency review:** new `docs/license-and-dependency-review.md` — zero runtime dependencies (confirmed by grepping every import in `src/autodebug/`), one build-time-only dependency (`setuptools`), zero third-party/DebugMCP code copied. Explicitly does not claim Autodesk legal/security approval — none has been sought, since nothing new was installed.

**Case-data handling review:** added a section to `docs/security.md`. Confirmed correct: no default in-repo path, redaction-before-write, no credential fields. **Three missing policy decisions flagged, not fixed** (no acceptance scenario requires them): no code-level repo-path enforcement for `evidence_base_dir`, no OS-level file-permission hardening, no retention/expiry policy.

**Release readiness checklist:** new `docs/release-readiness-checklist.md`. **Verdict: CONDITIONALLY READY** (fake-backend scope only) — all fixable gaps fixed and tested, full suite green, documentation accurate, T05 gate unchanged — but gated on independent reviewer sign-off (which this document cannot itself provide), three open case-data policy decisions, and the CI workflow being unverified on a real runner.

**Test command + observed result:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **357/357 PASS** (340 prior + 9 `test_t15_security_release_gate.py` + 8 `test_t15_contract_conformance.py`). Re-ran 4× consecutively, no flakiness.

**`git diff --stat` confirms scope:** `src/autodebug/facade.py` (three fixes only), one corrected pre-existing test fixture (`tests/test_facade.py`), two new test files, five documentation corrections (`README.md`, `docs/mcp-contract.md`, `docs/test-plan.md`, `docs/traceability.md`, `docs/security.md`), three new docs, one new CI workflow file. Zero other `src/` files touched; `approvals.py` and every adapter file byte-for-byte unchanged.

**T15 left UNCHECKED, by explicit instruction:** all technical work is complete and green, but T15's acceptance text itself requires "independent reviewer signs off" — not satisfiable by implementer self-review.

**Decisions needing developer/reviewer review:** (1) whether the three fixes are correctly scoped; (2) the three open case-data-handling policy decisions in `docs/security.md`; (3) whether to require the new CI workflow once proven on a real runner; (4) the explicit independent sign-off needed to check T15's box.

## T15 final review update — fake-backend scope only; release blockers remain

**Automated review finding fixed:** the step-budget check originally ran before lease acquisition, leaving a scheduling window in which concurrent calls could exceed `max_steps`. The check is now performed while holding the same per-session lease as the adapter mutation. A deterministic race regression verifies that the second caller is refused after the first consumes the final step.

**Additional evidence-boundary fix:** case IDs are validated as single path components, and `EvidenceStore` verifies the resolved case directory is a direct child of the supplied evidence base. This prevents a case ID from escaping that base and reading or writing another directory. It does **not** decide whether the configured base itself must be outside the repository.

**Lease outcome checks:** regression tests cover success, contention, backend errors, unexpected exceptions, and adapter-reported `TIMEOUT`/`CANCELLED` outcomes; all prove the lease is released when the synchronous adapter call returns or raises. The adapter interface has no operation deadline or cancellation token, so an adapter call that hangs cannot currently be interrupted and can retain its lease indefinitely. GW-05 is therefore **partially satisfied**, not fully release-validated.

**Production-fix assessment:** GW-05 serialization and atomic step-budget enforcement are accepted; its timeout/active-cancellation requirement remains open. DE-08 expiration handling and DE-06 cited-evidence checks are accepted on the inspected/tested fake-backend paths. These are technical review verdicts, not independent human sign-off.

**Validation:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` — **369 tests passed** locally after the final code edits. This is not a CI-runner result. `.github/workflows/tests.yml` has not run on GitHub Actions.

**Remaining T15 blockers:** Autodesk policy decisions for (1) whether/how to enforce an evidence base outside the repository, (2) file permissions, and (3) retention/deletion; independent human reviewer sign-off; an actual CI-runner result if CI is to be a release gate. All five IDE adapters remain mock-backed and unverified; the T05 real-debugger gate remains **OPEN / NOT APPROVED**. T15 stays unchecked.

### Historical self-review notes (not independent reviewer sign-off)

**Reviewed:** `CLAUDE.md`, T15's `tasks.md` entry, relevant specs, `docs/release-readiness-checklist.md`, and the complete diff including untracked files.

**`GW-05` — APPROVED, with 2 new regression tests added (no production code change):** confirmed the lease is acquired immediately around the adapter mutation in both `autodebug_step`/`autodebug_continue`, never around the cheaper preceding checks. Confirmed by direct code reading that `SessionLease.__exit__` (T03, unchanged) always releases the lock regardless of success or exception — but this was previously untested for the exception path, so added `test_lease_is_released_even_when_the_adapter_raises` (a `RaisingOnceStepAdapter` fixture that fails once, proving the lease isn't stuck afterward). Also added `test_concurrent_steps_on_different_sessions_do_not_block_each_other`, proving the per-session key (`host_id`/`ide`/`debug_session_id`) means two unrelated sessions never contend — **this test initially failed** because two independently-constructed `FakeAdapter` instances both number their own sessions starting at `"fake-session-1"`, so with the shared default `TargetRef` the "two different sessions" actually collided on the same registry key; fixed by giving the second case a distinct `host_id`, which is a test-fixture correction, not a production concern (real adapters generate genuinely unique IDs). Confirmed via `sessions.py`'s existing, unmodified `unregister()` that `_op_locks` entries are cleaned up on disconnect — no lock-table leak.

**`DE-08` — APPROVED, with 2 new regression tests added (no production code change):** confirmed `_verify_approval`'s recovery branch is keyed to the exact `ErrorCode.APPROVAL_EXPIRED` value via `is` identity comparison, structurally unreachable for any other `verify_approval` failure. Added `test_a_forged_approval_does_not_mark_the_case_incomplete` (an attacker-supplied `NOT_APPROVED` token, not just the already-tested scope-denied `PERMISSION_DENIED` case) and `test_expiration_handling_is_idempotent_across_repeated_calls` (proving a second and third privileged call against an already-`INCOMPLETE` case fail closed with `NOT_PAUSED` from the ordinary state gate — which runs before `_verify_approval` is ever reached again — without corrupting `case.json` or duplicating evidence). Confirmed `check_plan_unchanged()`'s `PLAN_CHANGED` is raised directly in `autodebug_step`/`continue`, never passing through `_verify_approval` at all — structurally safe by construction, no test needed.

**`DE-06` — APPROVED, no gaps found, no new tests needed:** traced the full order of checks in `autodebug_complete_case` — the evidence-ID cross-check runs first, then `build_investigation_report`'s `CONFIRMED`-requires-`causal_validation` check; verified these compose correctly (a real-but-insufficiently-validated `CONFIRMED` claim is still rejected, for the right reason). Strengthened `tests/test_facade.py::test_confirmed_without_causal_validation_is_rejected` with message-content assertions, so a future regression in the evidence-ID check masking this test's real subject would be caught. Confirmed `ctx.evidence_store is not None` cannot be bypassed in practice — reaching `INSPECTING` state structurally requires a successful arm, which always sets `evidence_store` before any session-mutating state is reachable. No malformed-input or report-state-transition bypass found.

**Contract and security test coverage (item 2):** the contract suite has 8 tests and the security/release suite has 21 tests after review regressions; together they contribute 29 T15-specific tests to the final 369-test suite.

**CI and documentation (item 3):** `.github/workflows/tests.yml` reviewed line by line — Python 3.11/3.12 matches `pyproject.toml`'s `requires-python`, zero `pip install` steps matches zero declared dependencies, `PYTHONPATH=src python3 -m unittest discover -s tests -v` exactly matches every command used throughout this project, and a nonzero `unittest` exit code on any failure is standard behavior GitHub Actions already treats as a failed check — no explicit failure-suppression exists. **Still not executed on an actual runner** — this remains stated honestly as unverified-in-environment, not claimed as passing CI. Re-checked README/mcp-contract/security/traceability/test-plan/license/upgrade-rollback docs for accuracy — all consistent with the current implementation and with each other; no overclaim found.

**Release-gate classification (item 4):** rewrote `docs/security.md`'s three case-data policy-decision entries to explicitly state each **requires an Autodesk policy/security decision, not merely a code change** — repo-path enforcement (ambiguous scope, new caller-facing refusal mode), file-permission model (OS/deployment-dependent, wrong choice is itself a risk), and retention/deletion policy (a compliance question, not a technical one). None invented or silently selected. Re-confirmed: `git diff --stat -- src/autodebug/adapters/ docs/compatibility-ledger.md` is empty — all five adapters remain mock-backed and unverified against any real native debugger; `git diff --stat -- src/autodebug/approvals.py` is empty and `FAKE_BACKEND_KIND = "fake"` is unchanged — the T05 gate remains **OPEN / NOT APPROVED**; grepped every new/changed doc for overclaiming language — none found; confirmed every mention of "independent reviewer" or "sign-off" in `docs/release-readiness-checklist.md`, `docs/status.md`, and `tasks.md` explicitly states this review is implementer self-review and cannot substitute for independent human sign-off.

**Scope check:** `git status --short` after this review's additions shows the identical 9 modified + 6 new files as the implementation pass — no file outside T15's declared scope was touched. The only net production-code change across the entire T15 implementation-plus-review arc remains the original `src/autodebug/facade.py` diff; this review added zero further production code, only test coverage and documentation precision.

**Test command + observed result:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **369/369 PASS** (340 pre-T15 + 29 T15-specific: 8 contract-conformance + 21 security/release-gate). One final full local run was observed; no CI run is claimed.

**T15 remains UNCHECKED:** all three production fixes are approved, all explicitly-requested verification has been performed, and 4 additional regression gaps were found and closed during this very review (proving the review was substantive, not rubber-stamping) — but `T15`'s own acceptance text requires "independent reviewer signs off," which this document, written by the same implementer, cannot provide. The three case-data policy decisions also remain open and require an explicit Autodesk decision before `T15` can be considered fully resolved.

## T14 bug-to-evidence demonstration (this session) — fake-backend end-to-end proof, two genuine defects found and fixed

**Approved scope (developer, verbatim):** *"I approve T14 — Bug-to-Evidence Demonstration (`RP-01`–`RP-07`, `DE-01`–`DE-08`) for AutoDebug."* Demonstrate the complete workflow against the fake backend and a disposable synthetic case; support reviewed api_script and manual plans without ever automating manual steps; demonstrate breakpoint binding, stops, stack/variable inspection, stepping, bounded evidence; require CONFIRMED to cite real evidence and causal validation; test authorization failures, cancellation, timeouts, redaction, and incomplete investigations; add comprehensive end-to-end tests; preserve the T05 gate; no dependency install, no real debugger contact, no commit/push, no T15.

**Workflow demonstrated end to end (requirement #1):** `TestConfirmedApiScriptDemonstration` in the new `tests/test_t14_bug_to_evidence_demo.py` drives one disposable synthetic case (`maybe_divide(a, b)`, a fictitious inverted-guard bug — not a real file in this repo or any product) through every stage: `autodebug_create_case` → `autodebug_stage_plan` → a separately-issued `ApprovalRecord` → `autodebug_arm_case` → the fake adapter's own `simulate_stop` (standing in for the developer's own reproduction, never called from `src/autodebug`) → `autodebug_wait_for_stop` → `autodebug_get_stack`/`autodebug_get_variables` → `autodebug_step`/`autodebug_continue` → `autodebug_complete_case`, finishing with a `report.md`/`events.jsonl`/`case.json` triad on disk in a throwaway temp directory.

**Two genuine defects found and fixed in `src/autodebug/facade.py` while building this demonstration (not new architecture — both are T07/T04 gaps surfaced by actually exercising the full workflow):**
1. **RP-08 violation:** `autodebug_get_variables` never passed `execution_confidence` to `EvidenceStore.record_evidence`, so every observation silently defaulted to `NOT_APPLICABLE` — including `api_script`-mode cases, which `docs/mcp-contract.md` explicitly requires default to `DEVELOPER_REPORTED` absent real instrumentation (none exists in this project). Fixed: `execution_confidence` is now computed from `ctx.case.plan.reproduction.mode` immediately before recording. Covered by `TestConfirmedApiScriptDemonstration` (asserts `DEVELOPER_REPORTED`) and `TestManualPlanLikelyDemonstration` (asserts `NOT_APPLICABLE`).
2. **DE-08 unreachable:** `Case.mark_incomplete()` (added in T04) had no caller anywhere in the facade, making DE-08's "label the case incomplete" requirement structurally undemonstrable — this session's own instruction #6 required testing it. Fixed: `_verify_session` now catches `SESSION_STALE` specifically (a disconnect, not a `TARGET_MISMATCH` security refusal) and calls a new `_mark_incomplete` helper, which best-effort transitions the case to `INCOMPLETE` and finalizes partial evidence to disk. Covered by `TestIncompleteInvestigationDemonstration`.

**Regression from fix #2, found and corrected (not reverted):** the DE-08 fix caused the first of four sequential post-disconnect calls (`get_stack`) to transition the case to `INCOMPLETE`, so the later `step`/`continue` calls — which check `case.state` before re-verifying session identity — now correctly return `NOT_PAUSED` instead of a second `SESSION_STALE`. This is a strictly stronger guarantee (the case is no longer in any privileged-operable state at all), not a weaker one, so the five pre-existing tests asserting the old behavior (`test_facade.py`, `test_cursor_adapter.py`, `test_clion_adapter.py`, `test_xcode_adapter.py`, `test_visual_studio_adapter.py`) were updated to match, not reverted against.

**Manual-vs-api_script distinction (requirement #3, RP-07):** `TestManualPlanLikelyDemonstration` structurally confirms (via `inspect.getsource`) that no facade code path ever executes a `ReproductionPlan.steps` string, then demonstrates a manual-mode case producing `NOT_APPLICABLE`-labeled evidence and a `LIKELY` (not `CONFIRMED`) report.

**Breakpoint binding, stops, inspection, stepping, bounded evidence (requirement #4):** covered throughout `TestConfirmedApiScriptDemonstration` and reused by every other scenario class; evidence recording is bounded by `EvidenceStore`'s existing `DEFAULT_MAX_EVIDENCE_PER_CASE` cap (unchanged, not re-tested this session — already covered by `test_evidence.py`).

**CONFIRMED requires cited evidence + causal validation (requirement #5, DE-06):** `TestConfirmedApiScriptDemonstration` proves `autodebug_complete_case` refuses `CONFIRMED` with zero evidence IDs (`INTERNAL_ERROR` from `build_investigation_report`'s own `ValueError`) and only succeeds once both an evidence ID and a `causal_validation` string (describing re-running the reviewed script with the guard flipped and reverted) are supplied. `TestInconclusiveWithoutSufficientEvidenceDemonstration` proves `INCONCLUSIVE` is the only level that accepts zero evidence IDs — insufficient evidence is reported honestly, never stretched upward.

**Authorization failures, cancellation, timeouts, redaction, incomplete investigations (requirement #6):** `TestAuthorizationFailureDemonstration` (two scenarios: missing `op:step` scope → `PERMISSION_DENIED`; a fully-scoped approval issued for a real `VSCodeAdapter`'s `ide_id` → `PERMISSION_DENIED` from the still-unchanged T05 gate, re-verified rather than assumed even for this demo's own case). `TestCancellationDemonstration` (DE-09: a background `autodebug_wait_for_stop` is interrupted within one poll tick by `autodebug_cancel_case`, case ends `cancelled` on disk). `TestTimeoutDemonstration` (DE-01: a breakpoint that never hits times out, never hangs or fabricates a pause). `TestRedactionDemonstration` (DE-07: a `password` variable and a `sk-`-shaped secret embedded directly in free-text root-cause prose are both redacted before touching `events.jsonl`/`report.md`). `TestIncompleteInvestigationDemonstration` (DE-08, exercising fix #2 above: a mid-investigation disconnect preserves already-recorded evidence byte-for-byte and labels the case `incomplete` on disk).

**Simulated vs. real evidence clearly distinguished (requirement #7):** the new test file's module docstring and every class docstring state explicitly that `FakeAdapter` is an in-memory test double, not any real IDE, and that the T05 gate remains closed; `TestAuthorizationFailureDemonstration`'s second scenario is itself a live re-check of that gate rather than a documentation claim alone.

**Test command + observed result:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **339/339 PASS** (330 prior + 9 new in `tests/test_t14_bug_to_evidence_demo.py`). Re-ran 4× consecutively (1 verbose + 3 quiet), no flakiness, including the threaded cancellation test. Zero packages installed; zero real IDE/debugger/network contact.

**`git diff --stat` confirms scope:** `src/autodebug/facade.py` (57 insertions / 2 deletions — the two fixes above, nothing else), `tests/test_facade.py` / `tests/test_cursor_adapter.py` / `tests/test_clion_adapter.py` / `tests/test_xcode_adapter.py` / `tests/test_visual_studio_adapter.py` (regression-assertion corrections only), plus new `tests/test_t14_bug_to_evidence_demo.py`. No adapter file touched; `FAKE_BACKEND_KIND = "fake"` in `approvals.py` byte-for-byte unchanged (re-confirmed by `TestAuthorizationFailureDemonstration`, not just by inspection).

**Open limitations (honest, unresolved):** this is a fake-backend demonstration only — it proves the workflow's wiring and the five enforcement properties (DE-01/06/07/08/09, RP-07/08) are internally consistent and testable, not that any real IDE/debugger integration works. For an actual Fusion example, the developer must still execute a reviewed script through the existing Fusion scripting UI — nothing here does that or claims to. Real native-debugger certification for any of the five adapters remains blocked exactly as recorded under T08–T13 (no approved bridge/host for four of five adapters; T05 gate still open).

**Decision needing developer review:** whether the five regression-test corrections (SESSION_STALE → NOT_PAUSED for post-disconnect `step`/`continue`) are accepted as a genuine strengthening rather than a behavior change requiring separate sign-off — documented above with the reasoning, not silently folded in.

## T14 final security and integration review (this session) — no production defects found; four targeted regression tests added

**Reviewed:** `CLAUDE.md`, T14's `tasks.md` entry, `RP-01`–`RP-08`/`DE-01`–`DE-09` spec text, and the complete diff (`src/autodebug/facade.py`, all 5 edited test files, the new demonstration file).

**RP-08 execution confidence — verified correct:** `autodebug_get_variables` computes `execution_confidence` once per call, directly from `ctx.case.plan.reproduction.mode` — a value set at plan-staging time from the developer-approved plan, never inferred after the fact or fabricated. `plans.stage_plan` already restricts `mode` to exactly `"api_script"`/`"manual"` (`ValueError` otherwise), so the two-way branch is exhaustive; there is no third mode that could silently fall through to the wrong label. The `DEVELOPER_REPORTED` label for `api_script` matches RP-08-A's scenario text exactly ("the evidence record... states that execution was developer_reported, not independently verified, while still treating the observed pause/stack/variables as genuine debugger evidence") — the pause/stack/variable values themselves are never marked uncertain, only the claim that the exact reviewed script executed unchanged. Confirmed this fix does not interact with the separate `sanitize_observation`/redaction pipeline (`record_evidence` still redacts independently). No defect found here.

**DE-08 incomplete investigations — verified correct, four coverage gaps closed with new regression tests (not production changes):**
- **Genuine staleness → INCOMPLETE, evidence preserved:** confirmed by direct experimentation (`registry.verify_identity` → `SESSION_STALE` only when the session is no longer registered at all) and by the existing test suite.
- **Wrong session IDs / cross-session requests cannot mark a valid case incomplete:** `_mark_incomplete` is called only from the `SESSION_STALE` branch of `_verify_session`'s except clause — a reused PID or reassigned generation/IDE-instance (`TARGET_MISMATCH`, a security concern, not a disconnect) takes a separate code path and never reaches it. This was true in the implementation but was **not previously asserted by any test** — added `self.assertEqual(ctx.case.state.value, "paused")` after the `TARGET_MISMATCH` assertion in all 5 `test_reassigned_session_identity_blocks_step` tests (`test_facade.py` + 4 adapter files) to lock it in.
- **Authorization failures cannot mark a valid case incomplete:** `verify_approval`'s checks (`PERMISSION_DENIED`, `PLAN_CHANGED`, `APPROVAL_EXPIRED`, `CANCELLED`-from-revocation) run in `autodebug_step`/`autodebug_continue` only *after* `_verify_session` has already succeeded, so they can never trigger `_mark_incomplete` either. Previously unasserted — added a case-state assertion to `TestAuthorizationFailureDemonstration.test_arming_without_any_approval_scope_for_step_is_refused` confirming the case remains `paused` after a `PERMISSION_DENIED` scope refusal.
- **Repeated stale-session handling is safe, not corrupting or duplicating evidence:** verified by direct experimentation — three consecutive `SESSION_STALE`-triggering calls produce byte-identical `case.json` snapshots and exactly one `events.jsonl` line throughout, because `Case.mark_incomplete()` raises (swallowed) on an already-`INCOMPLETE` case and `EvidenceStore.finalize()` is idempotent by design (rewrites the same snapshot, never appends). Strengthened `TestIncompleteInvestigationDemonstration` with an explicit second `SESSION_STALE`-triggering call (`get_variables`, which unlike `step`/`continue` always re-verifies session identity) asserting `case.json` and the evidence list are unchanged across both calls.
- **SESSION_STALE → NOT_PAUSED behavior change, evaluated explicitly:** `autodebug_step`/`autodebug_continue` check `case.state` *before* calling `_verify_session`. Immediately after a disconnect, whichever privileged tool is called *first* observes `SESSION_STALE` (and triggers the `INCOMPLETE` transition); every call *after* that — `get_stack`/`get_variables` (which always re-verify identity) still correctly report `SESSION_STALE`, while `step`/`continue` (gated on `case.state` first) now correctly report `NOT_PAUSED`, since the case is no longer in any privileged-operable state at all. This is consistent with `docs/mcp-contract.md`'s documented error-code list (`NOT_PAUSED` is the documented code for "case is not currently paused or inspecting") and is a strictly more precise, stronger refusal than a repeated `SESSION_STALE` would be — **retained as correct, not merely because the tests pass.** Added a new test, `test_step_as_the_first_call_after_disconnect_also_reports_session_stale_and_marks_incomplete`, proving the order-independence claim directly (unlike the five pre-existing tests, which only ever call `get_stack` first).

**Scope-boundary findings (not fixed — flagged for a separate decision, not silently folded in):**
1. DE-08's requirement text names three triggers — "debugger disconnect, user cancellation, or approval expiration." This session's fix covers disconnect (`SESSION_STALE` → `_mark_incomplete`). Cancellation is already covered, more specifically, by DE-09's existing `CANCELLED` terminal state (a more informative label than generic `INCOMPLETE`, satisfying DE-08's intent). **Approval expiration occurring mid-investigation** (an `APPROVAL_EXPIRED` result from `autodebug_step`/`autodebug_continue` on an already-paused/inspecting case) currently leaves the case state unchanged — it does not transition to `INCOMPLETE`. This is a pre-existing gap, not introduced by this session's fix, and was outside this review's explicit, narrower scope (session staleness only); it is recorded here rather than fixed without a separate approved task, per `CLAUDE.md`'s "never silently expand scope" rule.
2. `autodebug_get_stack` has never recorded any evidence via `EvidenceStore.record_evidence` (only `autodebug_get_variables` does) — pre-existing since T07, unrelated to this session's fixes, and not required by any `RP`/`DE` requirement text reviewed. Noted for awareness only.

**Unintended weakening check:** reviewed every assertion changed across the 5 edited test files — in every case, an assertion was either added (new, stricter checks) or the single `SESSION_STALE`→`NOT_PAUSED` substitution was made, which is a stronger check (case is unusable at all, not merely session-identity-stale), never a check removed or loosened.

**Test command + observed result:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **340/340 PASS** (339 prior + 1 new order-independence test; 4 of the "new" assertions strengthen existing tests rather than adding new ones). Re-ran 4× consecutively, no flakiness.

**`git diff --stat -- src/`:** only `src/autodebug/facade.py` changed (unchanged from the implementation pass — this review added zero production code). `approvals.py`, `workflow.py`, `sessions.py`, `models.py`, `evidence.py`, and every adapter file are byte-for-byte unchanged, confirmed by an empty `git diff` against each.

**T14 acceptance criteria re-confirmed:** all stages produce auditable success/failure; no unsupported-automation claim; the report correctly labels `developer_reported` vs `independently_verified` vs `not_applicable` execution. T14's checkbox remains checked, with the two scope-boundary findings above recorded as open, honestly-scoped limitations rather than silently absorbed into "done."

## T13 remaining OS certification (this session) — mocked regression + procedure, zero production code touched

**Evidence review (requirement #1):** of the 11 intended cells, **zero have real native-debugger evidence.** 5 cells (one per adapter) have real-*environment* evidence already gathered in T08–T12 explaining why real validation is currently impossible; 6 cells (VS Code/Cursor/CLion × Windows/Linux) remain `NOT_TESTED` — no Windows or Linux host exists in this environment to check at all; 4 cells are `N/A` (Visual Studio macOS/Linux, Xcode Windows/Linux). Added as a new "Evidence summary" section at the top of `docs/compatibility-ledger.md`.

**macOS findings explicitly preserved:** `git diff --stat` against the ledger's 5 existing macOS/Windows rows confirms only additive changes (new evidence summary, `NOT_TESTED` row notes) — no existing status, date, or evidence pointer altered.

**Platform detection/capability-probing/fail-closed verified across all five adapters (requirements #3–4):** added `tests/test_cross_platform_certification.py` (7 tests). Confirms VS Code/Cursor/CLion report `AVAILABLE` on all three of their supported OSes via mocked `host_os` overrides; confirms all five adapters correctly report `NOT_APPLICABLE` outside their declared `supported_os` (generalizing T02's per-cell check into one pass); confirms `BACKEND_UNAVAILABLE` fail-closed is identical across all five without a client; and drives `Router.arm_target`'s launch/reuse paths for the three cross-platform adapters across Windows/macOS/Linux, proving their own operation code has zero `platform.system()` dependency. **Explicitly documented everywhere as mocked adapter-logic verification, not real Windows/Linux validation** — no ledger cell's status changed.

**Reproducible certification procedure (requirement #5):** added `docs/test-plan.md` section 4a — prerequisites (confirm exact IDE version, check independently for a registered debugger-capable MCP server/bridge per IDE, Autodesk approval, explicit note the T05 gate must close before any mutating step) and a 5-step procedure for whoever next has access to a real Windows/Linux host.

**Honest recording (requirement #6):** the 6 `NOT_TESTED` cells carry no fabricated version/date; their notes now name the specific reason (no host) and point to the new test file and procedure.

**Security protections and gate preserved (requirement #7):** zero changes to any `src/` file this session — `git diff --stat -- src/` is empty. `FAKE_BACKEND_KIND = "fake"` untouched. Security gate remains `OPEN / NOT APPROVED`.

**Test results:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **330/330 PASS** (323 prior + 7 new). Re-ran 5x, no flakiness. Zero packages installed; zero real IDE/debugger/network contact; zero production code touched.

**Remaining limitation (unchanged, not a stop-all):** no Windows or Linux host exists in this environment. T13 cannot be completed for real until one does — this session's work is preparation only, matching T08 Phase 1's precedent.

## T13 final review (this session) — one documentation defect found and fixed, no code change

Found and fixed a genuine counting error: the evidence summary (added in T13's implementation) said "3 cells are `N/A`" while naming all 4 actual `N/A` rows (Visual Studio × macOS/Linux, Xcode × Windows/Linux) — corrected to 4 in `docs/compatibility-ledger.md`, `tasks.md`, and this file, with the arithmetic shown (5 evidenced + 6 `NOT_TESTED` + 4 `N/A` = 15 rows; 5+6 = 11 intended). The per-cell table itself was always correct; only the summary prose miscounted it. Re-verified everything else: all 11 cells/4 N/A exclusions otherwise accurate, the 6 `NOT_TESTED` cells carry no fabricated evidence, the 7 cross-platform tests correctly cover OS applicability/capability probing/fail-closed behavior, the certification procedure names all 8 `IDE-04-B` points and correctly gates mutating steps behind the still-open T05 gate, no mocked result is presented as real certification anywhere, and zero `src/` files or adapters were touched. **330/330 PASS**, re-ran 3x, no flakiness.

## T12 implementation (this session) — real `VisualStudioAdapter`, mocked-only, T05 gate unchanged

**Environment check (read-only, `platform.system()` only, no process spawned, no network contact):** `platform.system()` reports **`"Darwin"`** — this machine is macOS, not Windows. Visual Studio (full IDE) is Windows-only. **This is the most fundamental limitation among all five adapters: T08–T11 all had the correct OS available to at least attempt a probe; here there is no Windows host at all, so neither an Autodesk-approved internal bridge nor a public-API/EnvDTE extension can even be checked for presence.** Matches `IDE-05-A`'s own acceptance scenario exactly ("GIVEN only a Mac test host is available... THEN Windows and Linux test cases remain NOT_TESTED or BLOCKED"). Recorded as `BLOCKED` (cannot test), not `UNSUPPORTED` (which implies a real probe ran). **This reflects the absence of a Windows host in this environment — not a claim that Visual Studio or either integration path lacks native debugger support.**

**Implemented:** `src/autodebug/adapters/visual_studio.py` mirrors the other four real adapters' architecture but depends on its own `VisualStudioDebugClient` `Protocol` — distinct from all four others', and copies no proprietary bridge code. Same fail-closed convention: no client attached → `BACKEND_UNAVAILABLE`. `probe()`/`probe_capabilities()` (unchanged) already correctly report `NOT_APPLICABLE` on this non-Windows host — confirmed, not modified.

**`GW-06` A–D, breakpoint binding, stack/variable inspection, stepping, continuation — all implemented and proven against `FakeVisualStudioDebugClient` (new mock fixture), independent of the approval gate** — capability-probing tests explicitly force `host_os="Windows"` to exercise adapter logic despite the real host being macOS. `get_variables` returns the raw, unredacted value — `DE-07` redaction re-confirmed end-to-end through the real facade tool with this fifth adapter too. A new `IDE-02-A` regression (`test_this_actual_macos_host_reports_not_applicable`) confirms `NOT_APPLICABLE` against the **genuine** current host (not a hypothetical non-matching OS, as every other adapter's equivalent test used) — the strongest form of this check among all five adapters. `TestNeverSpawnsAnIndependentDebuggerProcess` (added from the start this time, mirroring T11's final-review addition) confirms the module contains no `subprocess`/`os.system`/`Popen`.

**Authorization gate confirmed NOT bypassed, including cross-adapter:** a fully-wired `VisualStudioAdapter` is still refused by `authorize_and_arm` when the approval was issued for `backend_kind="fake"`. Additionally confirmed: `VisualStudioDebugClient` is distinct from all four others' client types; `VisualStudioAdapter.ide_id` differs from all four others'; a `vscode`-scoped approval does not authorize a `visual_studio`-identified adapter. `FAKE_BACKEND_KIND = "fake"` in `approvals.py` was not touched.

**Facade protections proven with this fifth real adapter, front-loaded from the start:** stale/reassigned-session identity, `_rollback_failed_arming`, real-thread cancellation, the `DE-03` step-budget structural-unreachability finding, and the redaction boundary — all re-proven with a real `VisualStudioAdapter` session.

**Test results:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **323/323 PASS** (289 prior + 34 new in `tests/test_visual_studio_adapter.py`, plus `test_adapters.py`'s `REAL_ADAPTERS` tuple extended to all five adapters — the stub/`NotImplementedError` branch is now dead code kept as a structural safety net). Re-ran 5x, no flakiness. Zero packages installed; zero real IDE/debugger/network contact.

**Compatibility ledger:** Visual Studio/Windows updated to **`BLOCKED`** (not `UNSUPPORTED`, not `PASS`, not `PARTIAL`) — 0 of 8 `IDE-04-B` points verified; no Windows host exists in this environment to even attempt a probe. See `docs/compatibility-ledger.md`.

**Remaining blocker (specific, not a stop-all):** no Windows host exists in this environment at all — the most fundamental of the five adapters' blockers. Once available, a decision on internal-bridge vs. public-API-extension integration is needed, then Autodesk approval, then a real `VisualStudioDebugClient` implementation — `VisualStudioAdapter` itself needs no further change to accept one.

## T12 final security and integration review (this session) — no genuine defect found, zero diff

Re-checked `VisualStudioAdapter`/`VisualStudioDebugClient` for invented APIs or copied proprietary bridge code (none — the two `EnvDTE` mentions are docstring prose, not code), fail-closed behavior without a client (confirmed), OS-mismatch rejection on the genuine host (confirmed), `GW-06` A–D and breakpoint/stack/variable/step/continue against the mock (confirmed), no hidden/independent process (confirmed, structural guard already present), cross-adapter isolation against all four other adapters (confirmed), and the unchanged `FAKE_BACKEND_KIND = "fake"` gate (confirmed, zero diff). Ran VS Code + Cursor + CLion + Xcode + Visual Studio + facade test modules together (190 tests) to confirm zero regression. **Unlike T08/T09/T11, this implementation already front-loaded every protection pattern from the start — no follow-up fix or test was needed.** No code, test, or documentation changed this review. **323/323 PASS**, re-ran 3x, no flakiness.

## T11 implementation (this session) — real `XcodeAdapter`, mocked-only, T05 gate unchanged

**Environment check (read-only — `xcode-select -p`, `xcodebuild -version`, `xcrun -f mcpbridge`, and a recursive bundle search; no network contact), performed independently of T08/T09/T10's findings:** Xcode **is installed** — `xcode-select -p` → `/Applications/Xcode.app/Contents/Developer`; `xcodebuild -version` → **Xcode 26.0.1, build 17A400**. `xcrun -f mcpbridge` fails ("unable to find utility 'mcpbridge', not a developer tool or in PATH"), and a recursive search of the entire `/Applications/Xcode.app` bundle finds zero matches for `mcpbridge`. **Closer to T08's VS Code finding (IDE installed, specific tool absent) than T10's CLion finding (the IDE itself absent).** Per `IDE-04-A`, recorded as `UNSUPPORTED`, not `PASS`/`PARTIAL`, since the tool is entirely absent from this installation. **This finding is scoped to this Xcode 26.0.1 installation on this machine — not a claim that `mcpbridge` can never exist on any Xcode version.** **Actual Xcode-specific tool inventory via `mcpbridge`: none** — evidenced, not a placeholder.

**Implemented:** `src/autodebug/adapters/xcode.py` mirrors the other three real adapters' architecture but depends on its own `XcodeDebugClient` `Protocol` — distinct from all three others' client types. Same fail-closed convention: no client attached → `BACKEND_UNAVAILABLE`.

**`GW-06` A–D, breakpoint binding, stack/variable inspection, stepping, continuation — all implemented and proven against `FakeXcodeDebugClient` (new mock fixture), independent of the approval gate — including an explicit "no hidden second (e.g. independent LLDB) session" check.** `get_variables` returns the raw, unredacted value — `DE-07` redaction re-confirmed end-to-end through the real facade tool with this fourth adapter too. A new `IDE-02-A` regression (`test_wrong_os_never_probes_even_a_fully_supported_backend`) confirms Xcode's macOS-only `supported_os` is respected at the integration-test level, not just generically in `test_capability_probing.py` — the first adapter proof task where this was directly exercised, since Xcode is the first of the four real adapters whose OS list is not all three platforms.

**Authorization gate confirmed NOT bypassed, including cross-adapter:** a fully-wired `XcodeAdapter` is still refused by `authorize_and_arm` when the approval was issued for `backend_kind="fake"`. Additionally confirmed: `XcodeDebugClient` is distinct from all three other adapters' client types; `XcodeAdapter.ide_id` differs from all three others'; a `vscode`-scoped approval does not authorize an `xcode`-identified adapter. `FAKE_BACKEND_KIND = "fake"` in `approvals.py` was not touched.

**Facade protections proven with this fourth real adapter, front-loaded from the start:** stale/reassigned-session identity, `_rollback_failed_arming`, real-thread cancellation, the `DE-03` step-budget structural-unreachability finding, and the redaction boundary — all re-proven with a real `XcodeAdapter` session, not deferred to a follow-up review.

**Test results:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **288/288 PASS** (255 prior + 33 new in `tests/test_xcode_adapter.py`, plus `test_adapters.py`'s `REAL_ADAPTERS` tuple extended to include `XcodeAdapter`). Re-ran 5x, no flakiness. Zero packages installed; zero real IDE/debugger/network contact.

**Compatibility ledger:** Xcode/macOS updated to **`UNSUPPORTED`** (not `PASS`, not `PARTIAL`) — 0 of 8 `IDE-04-B` points verified; Xcode itself is present and functional, but the specific `mcpbridge` facility is absent from this installation. See `docs/compatibility-ledger.md`.

**Remaining blocker (specific, not a stop-all):** `xcrun mcpbridge` does not exist on this machine's installed Xcode 26.0.1. Whether a different Xcode version, build, or an undocumented preference exposes it was not investigated this session (explicitly out of scope — probing the *currently installed* version, not reconfiguring/upgrading Xcode). Once found, Autodesk approval for whatever that requires, then a real `XcodeDebugClient` implementation — `XcodeAdapter` itself needs no further change to accept one.

## T11 final security and integration review (this session) — one structural gap closed, no production code changed

Re-checked `XcodeAdapter`/`XcodeDebugClient` for invented Apple MCP APIs (none), fail-closed behavior without a client (confirmed), `GW-06` A–D and breakpoint/stack/variable/step/continue against the mock (confirmed), the `IDE-02-A` macOS-only check (confirmed), cross-adapter isolation across all four real adapters (confirmed), and the unchanged `FAKE_BACKEND_KIND = "fake"` gate (confirmed, zero diff). Ran VS Code + Cursor + CLion + Xcode + facade test modules together (155 tests) to confirm zero regression beyond the full-suite count alone. **Found one genuine structural gap:** "no independent LLDB process" was only proven at the mechanism level (Router never issues a second `launch_or_attach`), not structurally (nothing proved `XcodeAdapter` contains zero process-spawning code at all). Added a regression test asserting the module source contains no `subprocess`/`os.system`/`Popen` — confirmed zero matches. No production code changed. **289/289 PASS**, re-ran 3x, no flakiness.

## T10 implementation (this session) — real `CLionAdapter`, mocked-only, T05 gate unchanged

**Environment check (read-only, no process spawned, no network contact), performed independently of T08/T09's findings:** a comprehensive local search (`/Applications`, `~/Applications`, JetBrains Toolbox's apps directory, Spotlight `mdfind "kMDItemFSName == 'CLion.app'"`) found **no installed CLion application anywhere on this machine** — only three residual JetBrains config directories (`CLion2024.2`, `CLion2024.3`, `CLion2025.1`) left from a prior install, with no MCP-related plugin in any of them. **This is the strongest absence of the three real adapters attempted: the IDE application itself is missing, not just a bridge/extension.** Per `tasks.md` T10's own literal "`UNSUPPORTED` if missing" criterion and your explicit instruction this session, this is recorded as `UNSUPPORTED` — deliberately different from `BLOCKED` (used for VS Code/Cursor), not an inconsistency. **Actual CLion-specific tool inventory: none** — evidenced, not a placeholder.

**Implemented:** `src/autodebug/adapters/clion.py` mirrors `VSCodeAdapter`/`CursorAdapter`'s architecture but depends on its own `CLionDebugClient` `Protocol` — distinct from both other adapters' client types — so nothing implies CLion shares a remote protocol or capability set with either. Same fail-closed convention: no client attached → `BACKEND_UNAVAILABLE`.

**`GW-06` A–D, breakpoint binding, stack/variable inspection, stepping, continuation — all implemented and proven against `FakeCLionDebugClient` (new mock fixture), independent of the approval gate.** `get_variables` returns the raw, unredacted value — `DE-07` redaction re-confirmed end-to-end through the real facade tool with this third adapter too.

**Authorization gate confirmed NOT bypassed, including cross-adapter:** a fully-wired `CLionAdapter` is still refused by `authorize_and_arm` when the approval was issued for `backend_kind="fake"`. Additionally confirmed: `CLionDebugClient` is distinct from both `vscode.DebugMCPClient` and `cursor.CursorDebugClient`; `CLionAdapter.ide_id` differs from both other adapters'; a `vscode`-scoped approval does not authorize a `clion`-identified adapter. `FAKE_BACKEND_KIND = "fake"` in `approvals.py` was not touched.

**Facade protections re-confirmed with this third real adapter (the T09-review discipline, not inferred):** stale/reassigned-session identity, `_rollback_failed_arming`, real-thread cancellation, and the `DE-03` step-budget structural-unreachability finding all re-proven with a real `CLionAdapter` session.

**Test results:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **255/255 PASS** (223 prior + 32 new in `tests/test_clion_adapter.py`, plus `test_adapters.py`'s `REAL_ADAPTERS` tuple extended to include `CLionAdapter`). Re-ran 5x, no flakiness. Zero packages installed; zero real IDE/debugger/network contact.

**Compatibility ledger:** CLion/macOS updated to **`UNSUPPORTED`** (not `BLOCKED`, not `PARTIAL`, not `PASS`, per this task's own criterion) — 0 of 8 `IDE-04-B` points verified; CLion itself is absent, so there is no real protocol to even describe. See `docs/compatibility-ledger.md`.

**Remaining blocker (specific, not a stop-all):** CLion is not installed on this machine at all — the most fundamental of the three adapter blockers so far. Once installed, its JetBrains MCP server's advertised debugger tools would need runtime discovery (never hardcoded), then Autodesk approval for whatever that requires, then a real `CLionDebugClient` implementation — `CLionAdapter` itself needs no further change to accept one.

## T10 final security and integration review (this session) — no code defect, one doc clarity fix

Re-checked `CLionAdapter`/`CLionDebugClient` for invented JetBrains MCP APIs (none), fail-closed behavior without a client (confirmed), `GW-06` A–D and breakpoint/stack/variable/step/continue against the mock (confirmed), cross-adapter isolation both directions (confirmed), and the unchanged `FAKE_BACKEND_KIND = "fake"` gate (confirmed, zero diff). Ran VS Code + Cursor + CLion + facade test modules together (122 tests) to confirm zero regression beyond the full-suite count alone. **Unlike T08/T09, this implementation already front-loaded the full facade-protection regression suite (stale session, rollback, cancellation, step-budget, redaction) from the start — no follow-up test was needed.** Only fix: clarified `docs/compatibility-ledger.md`'s CLion row so its `UNSUPPORTED` status cannot be misread as "CLion lacks native debugger support as a product" — it reflects this machine's environment only. No code or test changed. **255/255 PASS**, re-ran 3x, no flakiness.

## T09 implementation (this session) — real `CursorAdapter`, mocked-only, T05 gate unchanged

**Environment check (read-only, no process spawned, no network contact), performed independently of T08's VS Code finding:** `cat ~/.cursor/mcp.json` → `{"mcpServers": {}}` — zero MCP servers are registered with Cursor at all. `ls ~/.cursor/extensions` lists only generic editor/tooling extensions (`ms-python.debugpy`, `cursorpyright`, `remote-containers`, `remote-ssh`, `rainbow-csv`, `traycer`, `claude-code`) — none exposing native-debugger control via MCP. Cursor.app and its CLI are installed; nothing exposing debugger control via MCP is. **Actual Cursor-specific tool inventory: none** — this is the evidenced finding, not a placeholder.

**Implemented:** `src/autodebug/adapters/cursor.py` mirrors `VSCodeAdapter`'s architecture (per `docs/ide-integrations.md` section B's "reuse the same adapter abstraction" guidance) but depends on its own `CursorDebugClient` `Protocol` — deliberately distinct from `vscode.DebugMCPClient` — so nothing implies Cursor and VS Code share a remote protocol or capability set. Same fail-closed convention: no client attached → `BACKEND_UNAVAILABLE`. `RemoteSessionInfo` (T08's generic remote-session shape) was moved from `vscode.py` into `base.py` as a small additive refactor, since it was always adapter-agnostic — `vscode.py` re-exports it, so no existing import broke.

**`GW-06` A–D, breakpoint binding, stack/variable inspection, stepping, continuation — all implemented and proven against `FakeCursorDebugClient` (new mock fixture), independent of the approval gate.** `get_variables` returns the raw, unredacted value — `DE-07` redaction still happens exactly once, at the facade layer, re-confirmed end-to-end through the real facade tool with this adapter too.

**Authorization gate confirmed NOT bypassed, including cross-adapter:** a fully-wired `CursorAdapter` is still refused by `authorize_and_arm` when the approval was issued for `backend_kind="fake"`. Additionally confirmed: `CursorDebugClient`/`vscode.DebugMCPClient` are distinct types, `CursorAdapter.ide_id != VSCodeAdapter.ide_id`, and a `vscode`-scoped approval does not authorize a `cursor`-identified adapter. `FAKE_BACKEND_KIND = "fake"` in `approvals.py` was not touched.

**Test results:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **218/218 PASS** (191 prior + 27 new: 25 in `tests/test_cursor_adapter.py`, plus `test_adapters.py`'s two generic T01 tests generalized to a `REAL_ADAPTERS` tuple covering both `VSCodeAdapter` and `CursorAdapter`). Re-ran 3x, no flakiness. Zero packages installed; zero real IDE/debugger/network contact.

**Compatibility ledger:** Cursor/macOS updated to **`BLOCKED`** (not `PARTIAL`, not `PASS`) — 0 of 8 `IDE-04-B` points verified; zero MCP servers registered means there is no real protocol to even describe yet, let alone test. See `docs/compatibility-ledger.md`.

**Remaining blocker (specific, not a stop-all):** no Cursor native-debugger MCP bridge was discovered or configured on this machine — a materially different (and more fundamental) blocker than T08's "known extension, not installed." Once one is identified and configured, Autodesk approval to install/enable it would be the next step, then a real `CursorDebugClient` implementation — `CursorAdapter` itself needs no further change to accept one.

## T09 final security and integration review (this session) — a coverage gap closed, no production code changed

**Finding:** `_verify_session` (stale-session re-check), `_rollback_failed_arming` (bind-failure cleanup), cancellation, and the `DE-03` step-budget check had only ever been tested against `FakeAdapter` — never against either real adapter class. The logic is adapter-agnostic by construction, so this was a verification gap, not a known divergence, but needed evidence per this review's explicit instruction.

**Added (`tests/test_cursor_adapter.py`, 5 new tests):** stale/reassigned-session identity blocks `get_stack`/`get_variables`/`step`/`continue` with a real `CursorAdapter` session; `_rollback_failed_arming` correctly disconnects/unregisters/revokes/fails a real, live Cursor session (called directly, since the public `autodebug_arm_case` path for a `"cursor"`-identified adapter is refused by the authorization gate before binding is ever attempted); `autodebug_cancel_case` interrupts a real Cursor session's pending wait promptly via a genuine background thread; and an explicit, passing test confirming `DE-03`'s step-budget check is structurally unreachable for any non-`"fake"` adapter — `ApprovalBroker.verify_approval`'s unconditional refusal runs before the budget check, confirmed even with an approval issued for `backend_kind="cursor"` with a perfectly matching scope.

**This is a security-positive finding, not a defect** — it confirms the T05 gate blocks every privileged path (`arm_case`, `step`, `continue`) for a real adapter, not just `arm_case`. `DE-03` itself remains correctly exercised against `FakeAdapter` in `test_facade.py`, where the gate legitimately opens.

**Re-verified, unchanged:** no invented MCP tool names in either adapter; every operation fails closed with `BACKEND_UNAVAILABLE` without a client; all `GW-06` scenarios and breakpoint/stack/variable/step/continue operations remain correctly proven against the mock; the `RemoteSessionInfo` move preserves `VSCodeAdapter` behavior exactly (same class object via both import paths, zero regression); `FAKE_BACKEND_KIND = "fake"` unchanged; Cursor/macOS ledger status remains `BLOCKED`, 0/8 `IDE-04-B`; T09 checkbox remains unchecked.

**Test results:** **223/223 PASS** (218 prior + 5 new). Re-ran 5x, no flakiness (including the real-thread cancellation test). Zero packages installed; zero real IDE/debugger/network contact. Only `tests/test_cursor_adapter.py` changed — no `src/` file touched this review.

## T08 implementation (this session) — real `VSCodeAdapter`, mocked-only, T05 gate unchanged

**Environment check (read-only, no process spawned, no network contact):** `ls ~/.vscode/extensions` found `ms-python.debugpy` only — DebugMCP is **not installed**, and no evidence of Autodesk approval to install it exists. Real validation against the extension did not happen this session for that specific, evidenced reason — not because it was skipped.

**Implemented:** `src/autodebug/adapters/vscode.py` now implements every `BaseAdapter` operation by delegating to a constructor-injected `DebugMCPClient` — AutoDebug's own `Protocol` abstraction, not DebugMCP's real wire shape (every remote tool/schema name remains `UNKNOWN — CONFIRM AT RUNTIME`, per the updated `docs/vscode-debugmcp-mapping.md`). With no client attached (`VSCodeAdapter()` still works with zero args), every operation fails closed with `BACKEND_UNAVAILABLE` (`IDE-03-A`) instead of the other four stub adapters' bare `NotImplementedError` — an intentional, documented difference, since this adapter is no longer a stub.

**Genuine defect found and fixed:** `facade.py`'s cancellable `autodebug_wait_for_stop` already called `ctx.adapter.is_paused(...)`, but `is_paused` was never declared on `BaseAdapter` — only improvised on the `FakeAdapter` test double. Fixed by adding it to `BaseAdapter` (default `NotImplementedError` stub) and `CORE_OPERATIONS` (now 10 entries). Purely additive; full suite re-confirmed passing.

**`GW-06` A–D, breakpoint binding, stack/variable inspection, stepping, continuation — all implemented and proven against `FakeDebugMCPClient` (new mock fixture), independent of the approval gate** (driven directly through `Router`/`SessionRegistry`, same pattern `test_router.py` already uses for `FakeAdapter`). `get_variables` returns the **raw, unredacted** value, confirming `DE-07` redaction still happens exactly once, at the facade layer.

**Authorization gate confirmed NOT bypassed:** a fully-wired `VSCodeAdapter(client=FakeDebugMCPClient())` — not a bare stub — is still refused by `authorize_and_arm` when the approval was only issued for `backend_kind="fake"`; the client is never reached (0 calls, 0 sessions registered). `FAKE_BACKEND_KIND = "fake"` in `approvals.py` was not touched.

**Test results:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **189/189 PASS** (166 prior + 23 new in `tests/test_vscode_adapter.py`; `test_adapters.py`'s T01 enumeration test updated in place to expect `BACKEND_UNAVAILABLE` for `VSCodeAdapter` specifically). Re-ran 3x, no flakiness. Zero packages installed; zero real IDE/debugger/network contact.

**Compatibility ledger:** VS Code/macOS updated to **`BLOCKED`** (not `PARTIAL`, not `PASS`) — 0 of 8 `IDE-04-B` points verified against the real extension; the adapter's own translation logic is proven only against a mock. See `docs/compatibility-ledger.md`.

**Remaining blocker (specific, not a stop-all):** Autodesk policy approval to install the DebugMCP VS Code extension (unresolved since T08 Phase 1, blocker #1). Once granted, a real `DebugMCPClient` implementation is the next piece of separate, future work — `VSCodeAdapter` itself needs no further change to accept one.

## T08 final implementation review (this session) — two genuine gaps found and fixed

1. **`is_paused`'s new contract was unverified on the four still-stub adapters.** Generic `CORE_OPERATIONS`-driven probing tests happened to cover it indirectly, but nothing called `instance.is_paused(...)` directly on `Cursor`/`CLion`/`VisualStudio`/`Xcode` adapters. Fixed with a new regression test confirming all four still raise `NotImplementedError` and `VSCodeAdapter` (no client) still raises `BACKEND_UNAVAILABLE`.
2. **The facade's redaction boundary (`DE-07`) had never been exercised with the real `VSCodeAdapter`** — only inferred from `FakeAdapter` coverage, since `autodebug_arm_case` always refuses a `"vscode"` case by design. Fixed with a new test that walks `Case`'s own public state-machine methods directly (never touching `authorize_and_arm`/`ApprovalBroker`) to reach a state where `autodebug_get_variables` is reachable, then confirms a real secret value comes back as `REDACTED_PLACEHOLDER` through the actual facade tool and never appears in the on-disk `events.jsonl` bytes.

**Re-confirmed, unchanged:** no fabricated DebugMCP tool names anywhere; all four `GW-06` scenarios and breakpoint/stack/variable/step/continue operations remain correctly proven against the mock; every missing-client operation still fails closed with `BACKEND_UNAVAILABLE`; the T05 authorization gate still cannot be bypassed. `docs/compatibility-ledger.md`'s VS Code/macOS row remains `BLOCKED`; `tasks.md` T08's checkbox remains unchecked.

**Test results:** **191/191 PASS** (189 prior + 2 new regression tests). Re-ran 3x, no flakiness. Zero packages installed; zero real IDE/debugger/network contact. Only `tests/test_adapters.py` and `tests/test_vscode_adapter.py` changed in this review pass — no `src/` file touched.

## T08 Phase 1 preparation (this session) — documentation only, T08 NOT started

Per the developer's explicit instruction, this session was **preparation only** — no adapter code, no dependency installation, no DebugMCP/real-debugger contact, no commit/push, T09 not started. Three new files were added:

1. **[docs/vscode-debugmcp-mapping.md](vscode-debugmcp-mapping.md)** — a proposed, unverified mapping from `BaseAdapter`'s nine `CORE_OPERATIONS` to DebugMCP's expected capability areas, plus a proposed `GW-06` scenario mapping. Every exact remote tool/schema name is marked `UNKNOWN — CONFIRM AT RUNTIME` — DebugMCP was not installed, contacted, or fetched from; nothing here is a verified API, per `CLAUDE.md`'s anti-fabrication rule. Lists 7 explicit unknowns a future implementation task must resolve.
2. **[docs/compatibility-ledger.md](compatibility-ledger.md)** — the full `IDE-05` per-cell ledger for all 11 target combinations (and the out-of-scope `N/A` cells). **VS Code/macOS, and every other target cell, is `NOT_TESTED`.** Cross-referenced from `docs/test-plan.md` section 4.
3. **[docs/security-gate-closure-proposal.md](security-gate-closure-proposal.md)** — candidate (not selected) designs for the four hard-blocking T05 gate items: (1) OS-level human-presence mechanism, (2) approval-broker process isolation, (3) verified machine/device identity upgrading `DE-07`, (4) a hardcoded `APPROVED_BACKEND_KINDS` allowlist pattern. Every item is flagged as an open decision for you/security review — none was implemented.

**Explicitly preserved:** `src/autodebug/approvals.py`'s `FAKE_BACKEND_KIND = "fake"` restriction is byte-for-byte unchanged; `git diff --stat` against every T01–T07 `src/autodebug/` file returns empty. **The T05 security gate remains OPEN / NOT APPROVED** — this session's documents propose candidate designs for 4 of its 7 items but close none of them.

**Remaining Autodesk policy approvals / security decisions before any real T08 work:**
1. Autodesk policy approval to install the DebugMCP VS Code extension.
2. Autodesk policy approval for any MCP SDK/package needed to reach it.
3. Autodesk-approved AI data-handling confirmation for real debugger observations (per `docs/security.md`).
4. Which human-presence-mechanism candidate to pursue (`docs/security-gate-closure-proposal.md` §1).
5. Which process-isolation approach to pursue (§2).
6. Whether the interim `DE-07` risk-acceptance placeholder (§3-C) is acceptable for a single disposable T08 machine, or a stronger mechanism must land first.
7. Confirmation of the exact installed DebugMCP/VS Code versions once/if installation is approved.

**Test command + observed result:** unchanged this session — `PYTHONPATH=src python3 -m unittest discover -s tests -v` → `Ran 166 tests in ~0.15s — OK` (no test file touched; documentation-only task).

## T08 Phase 1 deployment-scope review (this session) — documentation review only

Re-scoped the three Phase 1 documents against AutoDebug's actual deployment target: an internal, developer-operated debugging tool, not a public or customer-facing MCP product. **Nothing was newly approved; nothing scope-independent was removed.**

- **Unconditionally kept, with citation** (not public-distribution-specific, so not removed): `CLAUDE.md`'s "distinct local trusted user interaction" requirement (blockers 4–5 above); Autodesk approval before installing DebugMCP or any MCP SDK (blockers 1–2, `CLAUDE.md`/`docs/security.md`); Autodesk-approved AI data-handling confirmation (blocker 3, `docs/security.md`); no production/customer-data targeting by default.
- **Re-scoped, not removed** (right-sized for one internal developer on one known machine — still needs your explicit sign-off): §1's proposed MVP is now a simple local CLI/UI confirmation rather than signed-biometric-helper infrastructure only needed for multi-machine distribution; §2's proposed mechanism is a basic OS-process/filesystem-permission boundary rather than OS-keychain integration; §3 proposes the existing `DE-07` heuristic plus an explicit risk acceptance as proportionate for one disposable test app, since `docs/security.md` already states "no remote/production use case in v1." Enterprise-grade alternatives remain the likely requirement before any multi-developer/public rollout — deferred, not discarded.
- **Confirmed not engaged** (was never a T08 blocker, not "waived"): redistribution-specific language (`tasks.md` T12, `docs/security.md`'s Visual Studio clause) — T08 touches no internal Autodesk code and redistributes nothing.
- **Added:** a read-only-probing-vs-mutating-operations distinction (§5 of the closure proposal; a new "Risk tier" column in `docs/vscode-debugmcp-mapping.md`) — read-only capability probing could proceed once DebugMCP install is approved, without waiting for gate items 1–4 to close; mutating calls (`launch_or_attach`/`set_breakpoints`/`step`/`continue_execution`) remain fully blocked either way. A disposable-app-and-synthetic-data requirement (§6) was added to all three Phase 1 documents for any future real-backend test.
- **Preserved, unchanged:** explicit developer authorization, session-identity checks, redaction, and `DE-03` operation limits — no enforcement code touched; `git diff --stat` against every `src/`/`tests/` file remains empty.
- **Security gate remains OPEN / NOT APPROVED.**

## T07 summary (this session) — MCP tool facade and fake end-to-end

Added `src/autodebug/facade.py` (`AutoDebugFacade`) exposing all 15 documented `autodebug_*` tools as plain stdlib callables (no MCP SDK pinned or installed — explicit developer instruction this session, see `tasks.md` T07's "Dependency-approval deviation" note). All four `GW-06` scenarios (launch, attach-to-running, existing-session reuse, decline-unsupported) are exercised end-to-end against `FakeAdapter`/`FULL_SUPPORT`. `autodebug_arm_case` is the only tool touching `Router`, and it calls `authorize_and_arm` exclusively — a structural regression test (`test_facade_never_calls_bare_router_arm_target`) greps the module source to keep this enforced, not just reviewed once. No tool calls `ApprovalBroker.issue_approval` (also structurally tested) — approvals must always arrive from a separate trusted process. `autodebug_cancel_case` (`DE-09`) sets a per-case `threading.Event` that `autodebug_wait_for_stop`'s own poll loop checks every ~10ms, ahead of checking for a real pause, so cancellation from another thread returns `CANCELLED` within one tick — proven with a real background thread in `test_cancellation_mid_wait_returns_cancelled_promptly`, not just a mocked clock. `tests/fixtures/fake_adapter.py` (a test fixture, not a T01–T06 production file) gained minimal in-memory `set_breakpoints`/`get_stack`/`get_variables`/`step`/`continue_execution`/`simulate_stop` support so the facade has something to exercise end-to-end; the real adapter stubs are untouched. 23 new tests in `tests/test_facade.py`; full suite re-run 5x with no flakiness. `git diff --stat` against every T01–T06 `src/autodebug/` file and `pyproject.toml` returns empty.

**Open decisions/limitations from T07 (see `tasks.md` T07 for full detail):** (1) `Case`/`CaseState` (T04) has no dedicated step/continue sub-state — `autodebug_step`/`autodebug_continue` accept `PAUSED` or `INSPECTING` and track the `DE-03` step budget separately in the facade's own per-case context, not in `workflow.py`; this was reviewed again this session and left as-is — it is a deliberate scope decision, not an oversight, and no `workflow.py` change was made; (2) `autodebug_probe_adapters` takes caller-supplied adapter/backend/host_os triples rather than owning IDE discovery — still zero real-IDE contact, real discovery remains T08–T12.

## T07 security and integration review (this session)

Reviewed `facade.py` against `CLAUDE.md`, `GW-03`, `RP-04`–`RP-06`, `DE-01`, `DE-03`, `DE-09`, and `docs/mcp-contract.md`'s approval-binding/re-check requirements. **Two genuine defects found and fixed, both using only existing T01–T06 primitives — no new `Case` state, no new error code, no architecture change:**

1. **Missing per-call session-identity re-check (`GW-03-B`).** Only `autodebug_wait_for_stop` re-verified a session's PID/generation/IDE-instance identity before touching the adapter. `autodebug_get_stack`, `autodebug_get_variables`, `autodebug_step`, and `autodebug_continue` did not — an exited or reassigned (PID-reused) session would have silently kept serving stale reads or accepting commands. Fixed with a shared `_verify_session(ctx)` helper, now called at the top of all five session-touching tools. Verified with new stale-session tests: an unregistered session now returns `SESSION_STALE` and a reassigned (bumped-generation) session now returns `TARGET_MISMATCH` from every one of the four previously-unguarded tools.
2. **`BREAKPOINT_UNBOUND` orphaned a live, authorized session.** A failed bind left the session armed, registered, and discoverable via `autodebug_list_sessions` indefinitely, with its approval token still valid and reusable — a real resource/security hygiene defect, not just an inconvenient state. Fixed with `_rollback_failed_arming`: disconnects the adapter session, unregisters it, revokes the case's approval (`ApprovalBroker.revoke_for_case`, reusing T05's existing DE-09 mechanism), and moves the case to the existing terminal `FAILED` state. Verified: after a forced bind failure, the registry is empty, `adapter.disconnect` was called exactly once, the case is `failed`, and the revoked approval independently fails `ApprovalBroker.verify_approval` with `CANCELLED`. A second test confirms the rollback is scoped to the failing case only.

**Explicitly tested this review, as requested:** expired approvals (`APPROVAL_EXPIRED`), revoked approvals (prior session), forged approvals (prior session), wrong-scope approvals (prior session), changed/revised plans (prior session, re-verified), backend-identity spoofing via a real `VSCodeAdapter` (prior session, re-verified), stale sessions (new), reassigned-session identity (new), and failed breakpoint binding with full rollback (new). `step`/`continue`/breakpoint operations were re-confirmed to have no path that bypasses `verify_approval` or reaches a real adapter — both are covered by the same `backend_kind != "fake"` refusal already proven end-to-end through the facade.

**Redaction/evidence persistence:** re-confirmed, not re-architected — `test_secret_variable_never_reaches_disk_unredacted` and the full T06 `test_evidence.py` suite both still pass unchanged; `EvidenceStore` is still only constructed after breakpoints bind successfully, so the new rollback path never has a partially-initialized evidence store to worry about.

**Test results:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` → **166/166 PASS** (161 prior + 5 new: 1 expired-approval, 2 stale/reassigned-session, 2 breakpoint-binding-rollback). Re-ran 5x consecutively, no flakiness. Zero packages installed. `git diff --stat` against every T01–T06 `src/autodebug/` file and `pyproject.toml` remains empty — this review's only `src/` change is inside `facade.py` itself (a T07 file).

**Security gate re-confirmed OPEN / NOT APPROVED** — unaffected by this review; no change touched `approvals.py`, `router.py`, or any other T01–T06 file.

## T06 security review (this session)

**Confirmed defect, fixed:** `build_investigation_report()`'s free-text fields had zero redaction — a raw secret embedded directly in report prose (not a named observation) would have reached `report.md` on disk unredacted, bypassing `DE-07` entirely through a code path different from `EvidenceStore.record_evidence()`. Fixed with a new `redact_text()` function applied at **two independent points**: inside `build_investigation_report()` (the common path) and again inside `render_report()` itself (defense in depth, since `InvestigationReport` is a plain dataclass that can be hand-constructed, bypassing the builder). 7 regression tests added, one per field plus one proving a hand-built report is still caught at render time. The 200-evidence cap was re-verified to never silently discard history — an explicit test now confirms the file has exactly the pre-cap line count after a rejected write. All T01–T05 files remain byte-for-byte unchanged.

## Security Gate status (T05) — OPEN / NOT APPROVED

`src/autodebug/approvals.py` is a prototype of the approval *mechanism* (digest/target/expiry/scope binding, revocation) tested only against the fake backend. It is explicitly NOT the OS-enforced, trusted-local-user-presence mechanism `design.md`'s threat model requires. `issue_approval()`'s `human_presence_confirmed` flag cannot verify a human actually approved anything — `tests/test_approvals.py::test_human_presence_confirmation_is_not_itself_a_security_boundary` proves this directly. Real-backend authorization is independently and unconditionally refused in `verify_approval()` (`backend_kind != "fake"` → `PERMISSION_DENIED`, confirmed exact-match with no case/substring/whitespace bypass), so the gate holds even though the underlying human-presence problem remains unsolved.

**Security review findings (this session, two confirmed defects fixed):**
1. `Router.arm_target` (T03) had zero coupling to `ApprovalBroker` — it could be called directly, fully bypassing authorization. Fixed with `authorize_and_arm()`, a composed function that verifies before arming. This is **not** a complete fix: Python cannot prevent bare `Router.arm_target` from still being called directly. **Binding requirement for T07:** its future MCP facade must call `authorize_and_arm` exclusively and must never expose bare `Router.arm_target` to agent-reachable code.
2. `authorize_and_arm`'s `backend_kind` was a free-standing string parameter, decoupled from the `adapter` object also passed in — a caller could pass a real `VSCodeAdapter()` while separately claiming `backend_kind="fake"`, and (with `target.ide` also set to match) the approval check would have accepted it. Fixed by removing `backend_kind` as a parameter entirely; it is now derived exclusively from `adapter.ide_id`, so there is no second channel that can disagree with the real adapter being armed. Confirmed with a regression test using an actual `VSCodeAdapter` instance, plus a structural guard (`inspect.signature`) proving the parameter can't be silently reintroduced.

**Requirements before real debugger integration (T08+)** — see the full 7-item list in `tasks.md` T05: (1) a genuine OS-level trusted-human-presence mechanism, (2) real process/privilege isolation for the broker, (3) a verified machine/device-identity check replacing `DE-07`'s current naming heuristic, (4) a hardcoded, reviewed `backend_kind` allowlist (never agent-influenced), (5) `authorize_and_arm` as the only facade entrypoint, (6) `SessionRegistry.verify_identity` wired into the same enforcement point, (7) consideration of a cryptographically signed approval record. **None of these are satisfied yet. Do not treat T05 or T07 as enabling any real debugger control.**

**T07 update to item (5):** `src/autodebug/facade.py` now exists and is confirmed, by a structural regression test (not just review), to call `authorize_and_arm` exclusively from `autodebug_arm_case` and to never call `ApprovalBroker.issue_approval` anywhere. Item (5) is satisfied for the fake-backend facade as built; items (1)-(4), (6), (7) remain open and are unaffected by T07.

## Existing artifacts

- `CLAUDE.md` project guidance; `README.md` onboarding and setup.
- OpenSpec-style foundation proposal, 4 capability specs (28 requirements, 41 scenarios), design and ordered tasks (G00 ✅, T01 ✅, T02 ✅, T03 ✅, T04 ✅, T05 ✅, T06–T15 pending).
- `docs/`: architecture, IDE integrations, MCP contract, security, test plan, decisions, traceability, risks (9 files — see `README.md` for the full list).
- `src/autodebug/`: `__init__.py`, `models.py` (`TargetRef.ide_instance_id`, `IntakeSource` enum), `errors.py`, `sessions.py` (`SessionRegistry`), `router.py` (`Router`), `plans.py` (plan validation + canonical digest), `workflow.py` (`Case` state machine), `approvals.py` (`ApprovalBroker`, `reject_prohibited_target`, `authorize_and_arm`), `evidence.py` (`EvidenceStore`, redaction, `build_investigation_report`, `render_report`), `facade.py` (`AutoDebugFacade` — the 15 `autodebug_*` tools, fake backend only), `adapters/` (`base.py` + 5 stubs). `tests/`: `test_adapters.py`, `test_capability_probing.py`, `test_sessions.py`, `test_router.py`, `test_plans.py`, `test_workflow.py`, `test_approvals.py`, `test_evidence.py`, `test_facade.py` (stdlib `unittest`), `fixtures/` (`fake_backend.py`, `fake_adapter.py` — extended for T07). `pyproject.toml` (zero dependencies, still unpinned for any MCP SDK).

## Actual test results

- T01–T13 unit tests: **330/330 PASS** — `PYTHONPATH=src python3 -m unittest discover -s tests -v` → `Ran 330 tests in ~0.8s — OK`, zero packages installed. Re-run 5x consecutively, no flakiness. T06 totals 39 tests; T07 totals 28 tests; T08 totals 25 tests; T09 totals 32 tests; T10 totals 32 tests; T11 totals 34 tests; T12 totals 34 tests (see `tasks.md` for breakdowns); T13 adds 7 new mocked cross-platform regression tests in `tests/test_cross_platform_certification.py`.
- Native IDE integration: **NOT TESTED against a real backend, for any of the five adapters, on any OS.** `VSCodeAdapter`'s (T08), `CursorAdapter`'s (T09), `CLionAdapter`'s (T10), `XcodeAdapter`'s (T11), and `VisualStudioAdapter`'s (T12) own logic is implemented and unit-tested against mocks, including cross-platform (`host_os`-forced) mock coverage added in T13; zero of the 8 `IDE-04-B` points are verified against any real extension/bridge/host, on macOS, Windows, or Linux. All five adapters are now implemented; none has real `IDE-04-B` evidence on any OS. Windows/Linux certification remains entirely blocked on the absence of a Windows/Linux host in this environment (T13).
- Real-backend approval enforcement: **NOT ENABLED** — blocked by the open security gate below; T07's facade only ever arms against the fake backend and is structurally tested to never call `issue_approval` or bare `Router.arm_target`.
- Real Fusion API reproduction: **NOT TESTED** (T14).

## Blockers to review before implementing further tasks

1. Verify enterprise permission to use Claude Code with project data, plus any third-party MCP extensions, before pinning/installing the official MCP SDK (blocks a future real-transport task, T08–T12, T14). T07 itself did not pin the SDK — see `tasks.md` T07's "Dependency-approval deviation" note.
2. **Decide/validate a real OS-level human-presence approval mechanism** that a shell-capable agent cannot trivially forge — T05 prototyped the digest/target/expiry/revocation mechanism around this gap, but did not and could not close it (blocks T05's real-world enablement, T08+).
3. Confirm exact native debugger capabilities per installed IDE release; no version assumed (blocks T08–T11's `PASS` claims).
4. **Unexplained Git auto-push** (investigated, not yet resolved): commits have been reaching `origin/main` without an explicit `git push`, most likely via SmartGit's background sync — see the investigation report delivered earlier this session. Recommend quitting SmartGit/Sourcetree, or disabling their auto-push setting for this repo, before further commits.
5. `DE-07`'s `reject_prohibited_target` is a host-naming heuristic, not a reviewed production/remote-detection policy — flagged for security review before T08+.
6. **Resolved by T07:** `authorize_and_arm` closes the intended-caller path, and `src/autodebug/facade.py` is now confirmed (structurally tested) to call it exclusively from `autodebug_arm_case`, never bare `Router.arm_target`. Bare `Router.arm_target` remains directly *callable* in Python (no language-level enforcement) — this residual fact is unchanged — but no code in this repository's tool-facing surface does so.
7. **Resolved by T07:** `EvidenceStore` (T06) is now wired into the case lifecycle inside `facade.py` (`autodebug_arm_case` creates it, `autodebug_get_variables` records observations through it, `autodebug_complete_case`/`autodebug_cancel_case` finalize it) — no longer demonstrated in a test only.
8. **Resolved by this session's T07 security review:** a `BREAKPOINT_UNBOUND` failure partway through `autodebug_arm_case` previously left the case stuck at `SESSION_VERIFIED` with a live, registered, still-authorized session and no retry tool. `_rollback_failed_arming` now disconnects/unregisters the session, revokes the approval, and moves the case to `FAILED` — see `tasks.md` T07's security review entry. No retry-binding tool exists (and still isn't in scope); a failed case must be re-staged as a new case.
9. **New from this session's T07 security review:** four tools (`autodebug_get_stack`, `autodebug_get_variables`, `autodebug_step`, `autodebug_continue`) previously had no session-identity re-check at all — fixed with a shared `_verify_session` helper; see `tasks.md` T07 for detail.

10. **New from T08 Phase 1 preparation:** items 2 and 5 have candidate (not selected) closure designs in `docs/security-gate-closure-proposal.md`; item 1 (Autodesk policy approval) and item 3 (exact IDE/backend versions) remain entirely open.
11. **Resolved by T08's implementation:** `VSCodeAdapter` is real, tested against a mock, and still correctly refused by the unchanged T05 gate. VS Code/macOS real validation remains `BLOCKED` on item 1 (DebugMCP install approval) specifically.
12. **New from T09:** no Cursor native-debugger MCP bridge was discovered or configured on this machine (`~/.cursor/mcp.json` → zero servers registered) — a more fundamental blocker than T08's, since there isn't yet a specific extension to request approval for. `CursorAdapter` itself is implemented and tested against a mock (`FakeCursorDebugClient`) and correctly refused by the same unchanged T05 gate.
13. **New from T10:** CLion is not installed on this machine at all (three residual JetBrains config directories only, no app, no MCP plugin) — the most fundamental of the four adapter blockers so far, since there is no IDE to even probe for a bridge. `CLionAdapter` itself is implemented and tested against a mock (`FakeCLionDebugClient`) and correctly refused by the same unchanged T05 gate.
14. **New from T11:** Xcode itself is installed (26.0.1, build 17A400) but `xcrun mcpbridge` was not found anywhere in the installation — a VS-Code-like blocker (IDE present, specific tool absent), not a CLion-like one. `XcodeAdapter` itself is implemented and tested against a mock (`FakeXcodeDebugClient`) and correctly refused by the same unchanged T05 gate.
15. **New from T12:** no Windows host exists in this environment at all (`platform.system() == "Darwin"`) — the most fundamental of the five adapters' blockers, since there is no OS to even check for an internal bridge or public-API extension. `VisualStudioAdapter` itself is implemented and tested against a mock (`FakeVisualStudioDebugClient`) and correctly refused by the same unchanged T05 gate. All five adapters are now implemented.
16. **Reaffirmed by T13:** no Windows or Linux host exists in this environment — items 12–15's blockers for Cursor/CLion/Xcode/Visual Studio apply equally to certifying VS Code/Cursor/CLion on Windows/Linux (6 cells). T13 added mocked cross-platform regression coverage and a reproducible certification procedure (`docs/test-plan.md` section 4a) but could not, and did not claim to, resolve the underlying host-availability blocker.

None of the above blocked implementing T08–T13's work independently of the gate, per each task's explicit instruction. Real native-debugger validation for any of the five adapters, on any OS, remains blocked on item 1 (and, for Cursor/CLion/Xcode/Visual Studio, and now all three cross-platform adapters' Windows/Linux cells, on a bridge/installation/tool/host existing at all).

## Next one action

Developer reviews this session's T13 diff (`tests/test_cross_platform_certification.py`, `docs/compatibility-ledger.md`, `docs/test-plan.md`) and the `tasks.md`/`status.md` updates (currently uncommitted). Once accepted, commit this work. All five IDE adapters are now implemented (T08–T12); T13's remaining OS certification is blocked until a real Windows and/or Linux host becomes available — not something achievable from this environment. **T14 — bug-to-evidence demonstration** remains the next task not blocked on a missing OS, though it still requires the T05 gate and Autodesk approvals this project has not yet obtained.

## Update rules

When work is reviewed, record: task ID, reviewer, commit/PR, exact test command/output, status and known limitations. Never mark an item completed because Claude promised to do it.

## End-of-session update template

Fill this in at the end of every working session so the next session (or a fresh Claude context) can resume from this file alone:

```text
Date:
Task ID:
Spec revision/commit:
Files actually changed:
Tests actually run (commands + results):
Review approval/PR:
Known blockers:
Next one approved task:
```
