# Current AutoDebug project status

**As of:** 2026-10-24
**Milestone:** Technical implementation frozen and committed; publication **BLOCKED**
pending the four documented external decisions. Before the 2026-10-24 cleanup
the full suite passed **468 tests** on macOS with Python **3.14.7** and
**3.12.13**; after it, **474 tests** passed on Linux with Python 3.13. Python
3.11, Windows and GitHub Actions were not run. All five adapters remain
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

## Strict code review and cleanup (2026-10-24)

Developer-requested whole-repository review and cleanup. Behaviour-preserving;
no native integration, approval, transport or security-gate change.

- Five near-identical adapter implementations (~1,000 lines) now share
  `ClientBackedAdapter`/`RemoteDebugClient` in `adapters/base.py`; each adapter
  keeps its own distinctly named client `Protocol`, `ide_id`, OS list and
  provenance docstring. A write-only `_sessions` cache was removed.
- Five duplicated adapter test files (~3,450 lines) and five fake clients
  (~470 lines) were consolidated into `tests/test_ide_adapters.py` and
  `tests/fixtures/fake_ide_clients.py`. Every adapter now runs the full
  shared suite (VS Code previously ran a subset); one new test covers a
  client-reported generation, which nothing exercised before.
- Dead code removed: unused `ApprovalRequest`, an unused
  `execution_confidence` local in `autodebug_get_variables`, a redundant
  unlocked revocation re-check in `verify_approval`, and an unused
  `sanitize_output` parameter. `Case.bind_breakpoints` now fails closed with
  `NOT_APPROVED` when no plan is staged instead of raising `AttributeError`.
- Single version source (`autodebug.__version__` = `0.1.0`, was
  `0.1.0-t01`); stale "T01 scaffold"/"still-stub" docstrings refreshed;
  lint fixes (unused imports, explicit loop-variable binding, `zip(strict=True)`).
- Verification actually run: `python -m unittest discover -s tests` passed
  **474 tests** on Linux, Python 3.13; `compileall` and `git diff --check`
  clean. Python 3.11/3.12, macOS and Windows were not run in this pass.

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

## Earlier history

Superseded verification snapshots and the per-task T06–T15 session logs
were removed in the 2026-10-24 cleanup. They remain in Git history (commit `435df13`, the initial import); task
records and approvals stay in `openspec/changes/autodebug-foundation/tasks.md`.

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

- Full suite: **474/474 PASS** — `PYTHONPATH=src python3 -m unittest discover -s tests` on Linux, Python 3.13 (2026-10-24, after the cleanup), zero packages installed. Adapter coverage lives in `tests/test_ide_adapters.py`; mocked cross-platform regressions in `tests/test_cross_platform_certification.py`.
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
