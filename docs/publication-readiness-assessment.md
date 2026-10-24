# Publication readiness assessment - 2026-10-24

## Current comprehensive closure

**Implementation frozen.** The verified 63-file implementation is committed as
`736cc154dda574a54bfc4f42ebf16d6980d71ac1`; finalization changes documentation
only. A single focused check of current tracked content found no unnecessary
employee identity, internal URL, workstation path, actual credential or private
operational snapshot to remove. Public vendor references, synthetic fixtures
and legitimate ownership/provenance remain.

For this fake-only publication, the remaining external decisions are permission
to publish/transfer; authorized copyright/license; exact artifact/destination/
history treatment; and personal-account/equipment development permission.
See the [four-decision request](ossa-legal-approval-request.md) and
[minimal publication steps](installation.md#publication-after-permission).
Native integration, user-presence and platform limitations remain unchanged;
they are not claims of completed native support or new implementation tasks.
No existing history was rescanned, rewritten, exported or made public here.

**BLOCKED for publication.** Subsequent developer-authorized implementation
supersedes the old transport/script/timeout/packaging gaps recorded below.
See the [closure report and all 28 requirement dispositions](technical-closure-report.md),
[actual verification](status.md), [98-file classification](publication-content-audit.md),
and [owner/OSSA/Legal request](ossa-legal-approval-request.md).
No ownership/license, external transfer, personal-account development,
native-debugger authorization or independent human approval is manufactured.

The detailed previous assessment below is retained as historical provenance,
not current capability/test evidence. Its 39-file/425-test counts, 30-commit
all-ref snapshot and missing-transport statements are superseded.

## Historical strict-review assessment

## Verdict: BLOCKED

Preparation is authorized; publication is not. No commit, push, transfer, public
repository creation, remote/history modification, dependency installation, or
real-debugger enablement was performed. No license was assigned. The real gate
is **OPEN / NOT APPROVED**, fake backend only. This AI-assisted assessment is not
an independent human security review or Autodesk ownership/OSSA/Legal approval.

The worktree already contained partial publication-preparation changes. The
complete review diff includes those changes as well as this repair; it is not
represented as exclusively authored during this pass.

## Evidence and scope

Read scope: current sources, fixtures/tests, configuration and documentation,
CLAUDE instructions, complete foundation proposal/design/tasks/four capability
specs, status, security and release checklist; all reachable tracked history.
Corrected strict-review Git inventory: **HEAD ancestry: 18 commits, 186 blobs,
165 trees, 0 tags, 369 objects**; **all refs: 30 commits, 241 blobs, 199 trees,
0 tags, 470 objects**. The earlier 28-commit inventory was an intermediate
all-ref snapshot, not the current HEAD ancestry. Twelve non-HEAD commits are
agent checkpoints; these refs are not normally included in an ordinary branch
push, but a mirror/all-ref export can expose them. Exact release refs require
separate approval.
Commit author/committer identities, timestamps, messages and trailers were
included. Historical pre-rename paths were included, not just current paths.
This is reachable-history review, not a claim about undiscovered refs, dangling
objects, external clones, hosted caches, LFS services or prior distribution.

The specifically named strict-audit Markdown and its reproduction script were
not available in the repository or supplied session files. An existing local
history audit was available. The ten supplied defect descriptions were checked
with synthetic regressions rather than claiming to have run the missing script.
Detailed private history inventories and test logs are kept in local session
review artifacts, outside the checkout. They are not public-release artifacts.

## Confirmed defects and disposition

Severities describe the current fake-only foundation and local artifact risks,
not a demonstrated compromise of a native debugger.

| # | Severity | Location | Confirmed defect | Implemented repair |
|---|---|---|---|---|
| 1 | MEDIUM | `workflow.py`, `facade.py`, `approvals.py` | Foreign-case plans/approvals can be replayed under another context; cancellation misses the original case token | Bind owning case, plan, approval and routed target; reject before backend access; preserve case-scoped revocation |
| 2 | HIGH | `evidence.py` | Artifact symlinks can redirect reads/writes; replacing the case directory redirects artifacts | Descriptor-relative no-follow opens, pinned directory identity, regular/single-link checks before truncation; private creation modes; fail closed without supported APIs |
| 3 | MEDIUM | `facade.py`, `workflow.py` | Continue leaves cached inspecting state; external continuation does not block reads | Invalidate pause on continue; live-pause verification under lease before and after reads; new wait required |
| 4 | MEDIUM | `facade.py`, `approvals.py` | Reads/waits ignore approval expiration, revocation and operation scope | Separate explicit read/wait scopes; inclusive expiry; recheck every poll and before returning observations; incomplete recovery on expiry |
| 5 | MEDIUM | `facade.py`, `evidence.py` | Stack metadata and variable names bypass redaction/bounding | Bound structured stack metadata, response names and all event/report text; selected-only variable output; block sanitized-name collisions |
| 6 | MEDIUM | `evidence.py`, `facade.py` | Reused case directory accepts old investigation evidence | Exclusive case-directory creation; reject any existing directory before arming |
| 7 | MEDIUM | `evidence.py` | Concurrent appends duplicate IDs and bypass event cap | Lock cap check, ID allocation, append and increment; serialize reads/finalization; failed append does not consume an ID |
| 8 | MEDIUM | `sessions.py` | Unregister/re-register replaces an active session lock; stale unregister removes replacement | Retain per-key locks for registry lifetime; conditional unregister; identity check inside facade lease |
| 9 | MEDIUM | `facade.py` | Evidence initialization fails after arming and leaves authorized session active | Reserve evidence before debugger changes; explicit failure/revocation; roll back later arming failures without terminating the application |
| 10 | MEDIUM | `plans.py`, `facade.py` | Approved inspection time budget never enforced; invalid waits/selections unbounded | Positive integer plan budgets, finite positive waits, monotonic arm-to-inspection deadline, bounded frame/name selection; reject late results |

The separate security-review agent reproduced findings 1 and 4 at confidence
10/10 and the stale-pause contract failure. The other repairs are supported by
local regressions, not presented as independent reviewer sign-off.

## Tests actually executed

### Strict final review and approved follow-up (2026-10-24)

The initial 38-file/405-test patch was not sufficient: adversarial synthetic
tests found arming identity/authorization gaps, cross-case session interference,
recursive-name redaction and total-size gaps, missing disconnect recovery,
late-deadline evidence persistence, premature finalization and false
reproduction claims. The developer selected **Fix all issues** and approved
the bounded delta before these follow-up changes.

- Current boundary: **39 files (28 modified tracked, 11 untracked)** against
  unchanged HEAD `0f3131af79f34270043860cf7a4d0283d49825ad`; **83 current files**.
  No tracked file was deleted. The original 38-file boundary was reviewed before
  adding the strict-review regression file.
- Added **20 strict-review tests**. The first 15 ran before fixes: 14 failing
  assertions/subtests across 13 tests, two already-passing controls, zero errors.
  Five later tests cover concurrent arming, mutation cancellation, completion
  contention, atomic-write rollback/cleanup and escaped-Unicode/name redaction.
  Those five are additional coverage, not claimed as independently red-proven.
- Latest full suite: **425 tests in 1.967s, OK**, Python **3.14.7**, macOS;
  **425 tests in 1.965s, OK**, Python **3.12.13**, macOS. Expanded assertions
  cover all five returned identity fields and node-limit-dominant stack trees.
- Original repair efficacy: 35 selected tests against materialized HEAD source
  produced **33 assertion-failing tests (58 failing assertions/subtests), two
  already-green controls, zero errors**. The same 35 pass against current code.
  The FIFO test is excluded only from the vulnerable-source run; it passes in
  the current full suite. Earlier two error-only reproductions were strengthened
  to assert the actual unwanted launch and stale-poll result without hanging.
- Local configured Windows contract subset: **115 tests in 0.009s, OK**.
  This is macOS execution, not a Windows result.
- `git diff --check`, `python3 -m compileall -q src tests` and the CI commit
  whitespace command `git diff-tree --check --root -m -r HEAD` passed.
  Pylance reported no errors in the three follow-up production modules;
  informational unused-parameter/decorator notices remain.
- Python **3.11 unavailable**. No Linux, Windows, GitHub Actions or packaging run.
  No dependencies installed. The CI configuration now compiles sources and
  checks the checked-out commit (including merge parents), rather than treating
  a clean checkout's empty working-tree diff as patch verification.

Follow-up behavior: host/IDE arming serialization, existing-session leases and
exclusive active-case claims; returned-target checks; authorization/cancellation
and arming-budget rechecks; rollback disconnects only newly created sessions.
Reads recheck after the final pause and before persistence/return. A reported
backend disconnect makes the case INCOMPLETE. Stack trees are limited to 64 KiB
UTF-8 and 4,096 visited nodes with recursive sensitive-name redaction.
Completion is serialized, requires a previously confirmed stop for a reproduction
claim, persists artifacts before FINALIZED and returns relative paths/summary.
Snapshots use same-directory atomic replacement and failed attempts can retry;
the three artifacts are not one crash-atomic transaction. Case IDs must survive
sanitization losslessly and fit one 255-byte path component.

The following table is **historical initial-preparation evidence**, not the latest
verification. It is retained to distinguish prior work from this follow-up.

| Check | Observed result |
|---|---|
| Initial worktree full suite | 384 tests; 20 failures, 9 errors |
| New facade regressions before repair | 15 tests; 22 failing assertions/subtests, 1 error |
| Original HEAD evidence source with current regressions | 14 tests; 29 failures; bounded subprocess completed without timeout |
| `PYTHONPATH=src python3 -m unittest discover -s tests -v` | Python 3.14.7, macOS: 405 tests in 1.784s, OK |
| `PYTHONPATH=src python3.12 -m unittest discover -s tests -v` | Python 3.12.13, macOS: 405 tests in 1.778s, OK |
| Configured Windows contract subset, executed locally on macOS | 115 tests, OK; not Windows run evidence |
| `git diff --check` | Passed |
| `python3 -m compileall -q src tests` | Passed |
| Editor diagnostics for six changed production modules | No errors reported; not a separately configured static type-check suite |

There are 21 new facade/security regression tests and 15 evidence regression
tests in the integrated worktree (369 prior tests + 36 = 405).
The evidence test file and partial evidence hardening predated this pass; their
behavior was reproduced against original HEAD and integrated without weakening
security assertions. Existing reopening tests now assert exclusive investigation
ownership and read through the original store. Fake approvals used by tests now
explicitly grant only needed read/wait scopes. Stale/unapproved real-adapter
fixtures still assert refusal, not native access.
The host-OS portability correction in the integrated Visual Studio tests uses
explicit injected Windows/macOS/Linux applicability rather than assuming the
machine is macOS; existing generic adapter enumeration uses the actual host.

The initial old-code FIFO reproduction was stopped to avoid an indefinitely
blocking open. The bounded original-HEAD run excludes that one test; the current
full suite includes it and passes. All reproduction data are disposable,
synthetic, local fake/mock data; no native debugger or company service was used.
Python 3.11 is not locally available. Linux/Windows and GitHub Actions were not
executed. There is no configured pytest, ruff, packaging or static-check command;
no dependency was installed to invent additional checks.

## Confidential information and history

See [file-by-file classifications](publication-content-audit.md).

- Generalized current internal repository/wiki locators, employee/reviewer
  identities, home/workstation paths and operational configuration inventories.
  Historical safety restrictions, implementation approval quotations and
  Autodesk-related provenance are preserved; current technical claims were
  made explicit rather than inferred from old logs.
- Public vendor documentation references, including public Fusion API help, are
  not private endpoints. They remain subject to terms/provenance review.
- No actual credential was identified by the reviewed pattern inventory.
  Token/private-key-shaped tests are synthetic sentinels. This is not a
  guarantee that arbitrary unknown secrets or proprietary content are absent.
- Pushing existing reachable history would still disclose internal repository
  and wiki references, workstation/home paths, employee author/committer emails,
  review metadata, operational snapshots, the old project name and development
  context. Tree cleanup and ignore rules do not remove these.
- No history was rewritten and no original ownership evidence was removed from
  history. Authorized owners must decide history disposition or a separately
  authorized clean export. Neither action is authorized by this preparation.
- No copied proprietary implementation was identified; code inspection and
  "independently written" documentation cannot establish redistribution rights.
  Internal bridge references, third-party interface assumptions, notices and
  corporate work-product rights require owner/Legal review.

## Remaining technical / OpenSpec gaps

1. No MCP transport/SDK wiring, trusted OS human-presence broker or real native
   adapter certification. All five adapters remain mock-backed; zero PASS cells
   among the 11 native IDE/OS targets.
2. Secure persistence requires POSIX descriptor-relative no-follow APIs.
   Windows evidence workflows are unavailable; its CI job is contract-only.
   The developer explicitly approved retaining this fail-closed limitation.
3. Blocking synchronous adapter calls cannot be interrupted or guaranteed to
   meet wall-clock deadlines. Late-response rejection does not stop a hung
   backend. Cancellation cannot undo an already-running debugger operation.
4. Process start identity and a backend stop/frame generation are not modeled
   completely. Registry generation/PID/instance checks are not real process
   identity or native event verification.
5. Registry operation/arming locks intentionally persist for its lifetime.
   Multiple processes do not share the in-memory registry/broker. Active-session
   ownership and arming/completion contention now have regressions; independent
   concurrency review remains required before transport or real backends.
6. Evidence-base location outside Git, ownership/permission policy and
   retention/deletion decisions are not enforced comprehensively. Creation
   modes and no-follow checks are defense in depth, not policy approval.
7. Pattern-based redaction cannot recognize arbitrary confidential documents or
   every token format. Do not provide real sensitive data. Stack observations
   are sanitized but not persisted as independent stack events.
8. Full reviewed script content/risks/allowed-data scope and immutable native
   process-start identity exceed the current draft model. The foundation's
   normative requirements are not all satisfied by fake-only tests.
9. Report confidence has structural evidence/causal-justification checks, not an
   automated proof that a caller's causal narrative is true.
10. Source-tree tests need no Autodesk infrastructure or runtime dependencies.
    Packaging remains unverified; the `setuptools>=68` build range is not an
    approved exact pin. No installer/server startup command is claimed.

## Mandatory approval blockers

- Autodesk ownership/copyright and authorized distribution decision.
- Autodesk OSSA/Legal review, approved license choice and notices/attribution.
  Top-level LICENSE and license metadata remain absent; none assigned.
- Third-party/build-tool provenance, exact version and redistribution/terms
  review; no imported-source audit can grant legal clearance.
- History/metadata/sensitive-information review and approved disposition.
- Security/data-handling policy, trusted approval-enforcement design and
  independent T15 human reviewer sign-off. T15 stays unchecked.
- Approved private vulnerability intake/contact before external contribution.
- Actual CI evidence, Python 3.11 verification and truthful platform limitations.
- Explicit approval of exact artifact, repository owner and destination before
  any publication. This task authorizes none of those actions.

## Complete cumulative files-changed report

The private complete patch includes tracked modifications and every new file,
without staging. Historical/unrelated worktree edits have not been reverted.

| Files | Change |
|---|---|
| `.github/workflows/tests.yml` | Linux/macOS full suite; Windows contract-only matrix; least-privilege permissions; no installs |
| `.gitignore` | Ignore environment/case/capture files; no claim this removes tracked history |
| `README.md` | Actual fake-only capabilities, source-tree setup/testing, contribution and publication/portability limitations |
| `CONTRIBUTING.md`, `SECURITY.md` | Review-first authorized contribution and private disclosure guidance; ownership/approval boundaries |
| `docs/architecture.md` | Generalized historical source/issue example |
| `docs/compatibility-ledger.md` | Removed workstation inventory; retained honest mock-only/native statuses |
| `docs/decisions.md` | Generalized private reference locators; preserved provenance |
| `docs/license-and-dependency-review.md` | Missing license, build/runtime inventory, ownership/OSSA/Legal and history blockers |
| `docs/mcp-contract.md` | Explicit read scopes, bounded inspection, exclusive persistence and platform limits |
| `docs/release-readiness-checklist.md` | Current BLOCKED status distinguished from historical technical review |
| `docs/security-gate-closure-proposal.md` | Generalized local inventory; real-debugger gate unchanged |
| `docs/security.md` | Current controls and remaining data/security policy obligations |
| `docs/status.md` | Current observed tests and blockers; sanitized workstation locator |
| `docs/publication-content-audit.md` | Current-file classifications and historical disclosure classes |
| `docs/publication-readiness-assessment.md` | This assessment, findings, results, changed files and blockers |
| `openspec/changes/autodebug-foundation/tasks.md` | Current review evidence; identity sanitization; T15 remains unchecked |
| `openspec/changes/publication-hardening/proposal.md` | Bounded authorization and restrictions |
| `openspec/changes/publication-hardening/spec.md` | Approved requirement clarifications |
| `openspec/changes/publication-hardening/design.md` | Bounded repair design and explicit limitations |
| `openspec/changes/publication-hardening/tasks.md` | Executed technical work versus outstanding approvals |
| `src/autodebug/approvals.py` | Case/target binding and inclusive expiry; fake-only gate preserved |
| `src/autodebug/evidence.py` | Secure exclusive storage, serialization and metadata/output sanitization |
| `src/autodebug/facade.py` | Read/wait authorization, leases, live pause, budgets, safe arming and explicit storage errors |
| `src/autodebug/plans.py` | Positive integer budget validation |
| `src/autodebug/sessions.py` | Lease continuity and replacement-safe unregister |
| `src/autodebug/workflow.py` | Case-bound staging and resumed/finalization transitions |
| `tests/test_clion_adapter.py`, `tests/test_cursor_adapter.py` | Existing fake/mock facade fixtures assert unapproved reads/waits refused |
| `tests/test_visual_studio_adapter.py`, `tests/test_vscode_adapter.py`, `tests/test_xcode_adapter.py` | Same refusal boundaries; explicit injected-host applicability replaces the macOS assumption; no real debugger enablement |
| `tests/test_evidence.py` | Reject new investigation reopening existing storage; preserve append assertions |
| `tests/test_facade.py` | Explicit fake read/wait grants in relevant fixtures |
| `tests/test_t14_bug_to_evidence_demo.py` | Same explicit scopes; read existing evidence through owning store |
| `tests/test_t15_security_release_gate.py` | Explicit scopes, owning-store reads, lease contention fixture updated for serialized waits |
| `tests/test_publication_evidence.py` | 15 synthetic persistence/redaction/concurrency regression tests |
| `tests/test_publication_security.py` | 21 synthetic case/approval/pause/lease/budget regression tests |
| `tests/test_strict_final_security.py` | 20 strict-review identity/arming/redaction/budget/recovery/finalization/concurrency tests |

**Next task:** developer reviews the complete uncommitted diff and confirms
security/policy/ownership decisions. Do not commit, publish, enable real debugging,
check off T15 or begin T16 as a consequence of this technical preparation.
