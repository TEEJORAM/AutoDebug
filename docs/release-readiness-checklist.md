# AutoDebug — T15 release readiness checklist

This maps T15's acceptance requirement ("independent reviewer signs off; no unsupported native IDE functionality described as implemented; approved case data handling") to tests, documentation, evidence, and remaining limitations. This is an AI-assisted self-review, including a separate security-review agent pass; **neither is independent human reviewer sign-off**.

## Publication preparation — 2026-10-24: pending authorization

**Publication is blocked.** Preparation of public-facing files is authorized;
publication, distribution, license assignment, and Git-history rewriting are not.
There is no assigned `LICENSE`. Historical technical assessments below do not
provide legal, ownership, security-policy, or publication clearance.

### Frozen fake-only publication: four external decisions

- [ ] Permission to publish or transfer this Autodesk-developed repository.
- [ ] Approved copyright, license and required notices.
- [ ] Approved exact public artifact/digest, GitHub destination and history
  treatment; do not push existing private history or checkpoint refs by default.
- [ ] Explicit permission for development on personal accounts/equipment;
  personal AI-service upload also needs explicit permission.

These are the finalization pass's remaining external publication decisions.
See the [approval request](ossa-legal-approval-request.md) and
[publication steps](installation.md#publication-after-permission).
Historical T15 records below are preserved, not silently signed off.
Native-debugger authorization, secure Windows evidence and unexecuted target
environments remain disclosed restrictions/limitations, not additional feature
work required to describe this release honestly as a fake-only foundation.

The provenance is Autodesk-related; do not infer personal ownership or a legal
verdict from synthetic fixtures or independently written adapter interfaces.
See [license and dependency review](license-and-dependency-review.md). No final
publication assessment is made by this preparation.

Current assessment: **BLOCKED**. The
[publication assessment](publication-readiness-assessment.md) and
[content classifications](publication-content-audit.md) supersede historical
technical conclusions below. The developer subsequently authorized comprehensive
implementation, including MCP stdio, script integrity, stop identity, bounded
operations and offline packaging. See the [complete requirement matrix and
closure report](technical-closure-report.md), [current exact results](status.md)
and [concrete approval request](ossa-legal-approval-request.md).
The earlier 425-test/39-file/83-current-file snapshot below is historical, not
the final closure boundary. Real native capability, external approvals and
unexecuted target environments remain explicitly unverified.

## Historical technical review

The sections below record the prior local review and test results, not fresh
verification of the publication-preparation working tree. Revalidate technical
claims after code hardening; use `docs/status.md` for current observed results.

## 0. Final review verdict on each of the three production fixes

A final review pass re-examined each fix against its acceptance criteria. It is not independent human sign-off.

| Fix | Verdict | Basis |
|---|---|---|
| `GW-05` — session lease serialization | **APPROVED WITH LIMITATION** | `step`/`continue` acquire a per-session lease; the step-budget check and increment are now atomic with the adapter mutation. Deterministic tests cover contention, cross-session independence, success, typed error/timeout/cancellation responses, and exceptions; leases release when the synchronous adapter call returns or raises. The adapter API has no call deadline or cancellation token, so a hung call cannot currently be interrupted and can hold the lease indefinitely. |
| `DE-08` — approval expiration | **APPROVED** | Recovery branch keyed to the exact `APPROVAL_EXPIRED` code; structurally unreachable for `TARGET_MISMATCH`, `PLAN_CHANGED`, `PERMISSION_DENIED`, or a forged `NOT_APPROVED` token (now proven for the forged case specifically, not just scope-denial). Idempotent across repeated calls (now proven: evidence and `case.json` unchanged across 3 consecutive calls). 2 new regression tests added. |
| `DE-06` — evidence-ID integrity | **APPROVED** | Evidence references are checked against the case's stored events before report creation; fabricated and cross-case IDs are rejected, and `CONFIRMED` still requires valid evidence plus causal validation. Case IDs are also constrained to a direct child of `evidence_base_dir`, preventing a case ID from redirecting evidence reads/writes to another directory. The base directory's location and permissions remain policy decisions. |

**The review found and fixed a step-budget race and case-directory escape in addition to the three initial fixes.** The security-review agent's finding is recorded as an automated review, not as human sign-off.

## 1. Contract verification

| Item | Status | Evidence |
|---|---|---|
| Error-code set matches `docs/mcp-contract.md` exactly | ✅ Done | `tests/test_t15_contract_conformance.py::TestErrorCodeContract` |
| Case-state set matches `design.md` exactly | ✅ Done | `TestCaseStateContract` |
| `EvidenceRecord` schema matches the contract's example | ✅ Done | `TestEvidenceRecordContract` |
| `ExecutionConfidence`/`RootCauseConfidence` values match contract/`DE-06` | ✅ Done | `TestEvidenceRecordContract` |
| Facade exposes exactly the 15 documented tools | ✅ Done | `TestFacadeToolSurfaceContract` |
| Standard response envelope shape | ✅ Done | `TestStandardResponseEnvelopeContract` |
| `SENSITIVE_OUTPUT_BLOCKED` documented as reserved/unused | ✅ Done | `docs/mcp-contract.md` implementation-status note |
| `get_stack` evidence-persistence gap | ⚠️ Documented limitation, not fixed | No spec requirement mandates it (`IDE-04-B`/`DE-05` reviewed); see `tasks.md` T14/T15 entries |

## 2. Security verification

| Gate | Status | Evidence |
|---|---|---|
| `SEC-01`–`SEC-06` | ✅ All verified | `docs/security.md` "Security acceptance gates" (test pointers added this session) |
| `GW-05` concurrent step/continue serialization | ✅ Fixed this session (was a real gap) | `src/autodebug/facade.py` (`SessionRegistry.lease` now acquired); `tests/test_t15_security_release_gate.py::TestGW05SessionLeaseSerialization` |
| `DE-08` approval expiration mid-investigation | ✅ Fixed this session (was a real gap; traceability.md assigns DE-08 to T15) | `_verify_approval` helper; `TestDE08ApprovalExpirationDuringInvestigation` |
| `DE-06` evidence-ID citation integrity | ✅ Fixed this session (fabricated/cross-case IDs now rejected) | `autodebug_complete_case`'s new cross-check; `TestDE06EvidenceIdIntegrity` |
| Fake-only T05 gate unchanged | ✅ Confirmed | `git diff --stat -- src/autodebug/approvals.py` empty; `FAKE_BACKEND_KIND = "fake"` byte-for-byte unchanged |
| Unauthorized requests cannot reach a debugger backend | ✅ Confirmed | `FakeAdapter.launch_or_attach_calls == 0` across every unapproved/forged/wrong-scope path |

## 3. T14 limitations disposition

| Limitation | T15 decision | Rationale |
|---|---|---|
| Approval expiration did not mark investigations `INCOMPLETE` | **Fixed** | `docs/traceability.md` explicitly assigns `DE-08` acceptance evidence to T15; `DE-08`'s own requirement text names "approval expiration" as a trigger alongside disconnect/cancellation; small, targeted fix (one new helper, reused `_mark_incomplete`). |
| `autodebug_get_stack` does not persist stack evidence | **Not fixed — documented only** | No `IDE-04-B`/`DE-05`/`DE-02` scenario requires stack-level evidence persistence distinct from variable observations; reports already satisfy `DE-06` citing only variable evidence (demonstrated in T14). Fixing this would be a design change beyond a "focused fix," so it is recorded as an open limitation per this task's explicit "do not silently expand scope" instruction. |

## 4. CI

| Item | Status |
|---|---|
| `.github/workflows/tests.yml` configured | Linux/macOS/Windows × Python 3.11/3.12; `PYTHONPATH: src` job environment and `python -m unittest discover -s tests -v`; `contents: read`; no package-install step |
| Workflow actually executed on a real GitHub Actions runner | ❌ **Not verified** — it was not run on a CI runner. The underlying command passed locally (369/369) but that is not CI evidence. |
| Workflow file reviewed line-by-line in final review | ✅ Python versions match `pyproject.toml`; zero `pip install` steps matches zero declared dependencies; exact command matches every local invocation throughout this project; nonzero `unittest` exit code is standard GitHub Actions failure signal, no suppression present |

## 5. Documentation audit

| Finding | Fixed |
|---|---|
| `README.md` claimed "no implementation has been built; G00 is NOT APPROVED" despite `T01`–`T14` being committed | ✅ Corrected |
| `docs/mcp-contract.md` header claimed "NOT implemented" despite the facade substantially implementing it | ✅ Corrected, with explicit "fake backend only, not an MCP server yet" caveat preserved |
| `docs/test-plan.md` claimed "No tests executed yet" | ✅ Corrected |
| `docs/traceability.md` claimed "No tests are currently implemented or verified" | ✅ Corrected |
| `docs/compatibility-ledger.md` | Reviewed — already accurate, no change needed |
| No overclaiming of real IDE readiness introduced by any correction | ✅ Confirmed — every correction explicitly restates "fake backend only" / "zero real IDE contact" / gate still OPEN |

## 6. Upgrade and rollback

| Item | Status |
|---|---|
| Source-tree upgrade/rollback procedure documented | ✅ `docs/upgrade-rollback.md` (new) |
| Case/evidence data handling across schema versions documented | ✅ Same doc — confirmed no migration code exists anywhere; introducing any is explicitly deferred to a future reviewed change |
| No unreviewed migration introduced | ✅ Confirmed — zero migration code added |

## 7. License and dependency review

| Item | Status |
|---|---|
| Dependency inventory | ✅ `docs/license-and-dependency-review.md` (new) — zero runtime dependencies, one build-time dependency (`setuptools`) |
| Third-party/external services reviewed | ✅ Same doc — DebugMCP, Cursor, JetBrains, Xcode, Visual Studio bridges all confirmed either absent or untested; zero code copied from any |
| Autodesk legal/security approval claimed | ❌ **Not claimed** — ownership/copyright, OSSA/Legal, license, security-policy, and publication approval remain required regardless of package installation |

## 8. Case-data handling

| Item | Status |
|---|---|
| Redaction/bounding before persistence | ✅ Confirmed, already correct (`DE-07`) |
| Caller-supplied storage base; no default path | ✅ Confirmed |
| No credential fields anywhere in the data model | ✅ Confirmed |
| Case IDs constrained beneath the configured evidence base | ✅ Implemented and regression-tested |
| Enforcing that the evidence base is outside the repository | ⚠️ **Policy decision remains open** — `docs/security.md` "T15 case-data handling review" |
| OS-level file-permission hardening | ⚠️ **Missing policy decision, flagged** |
| Retention/expiry policy | ⚠️ **Missing policy decision, flagged** |

## 9. Regression testing

| Item | Result |
|---|---|
| Full suite | **369/369 PASS** (340 pre-T15 + 21 security/release tests + 8 contract-conformance tests) |
| Command | `PYTHONPATH=src python3 -m unittest discover -s tests -v` |
| Stability | One full local run completed after the final code edits; no CI run claimed |

## Historical technical readiness: **FAKE-BACKEND REVIEW/TESTING ONLY; NOT RELEASE-CLEARED**

**Scope:** This prior classification applies only to local fake-backend review. It does not certify any IDE adapter, satisfy T15 acceptance, or authorize publication. The publication blockers above apply in addition to these technical review items:

1. **`T15`'s own acceptance text requires "independent reviewer signs off"** — this document is self-review by the implementer and cannot satisfy that line itself.
2. **Three case-data-handling policy decisions remain genuinely open:** whether/how to enforce that the configured base is outside the repository, the file-permission model, and evidence retention/deletion. Case IDs are now constrained beneath the configured base, but that does not decide the base-location policy.
3. **Zero real native-IDE validation exists for any of the 11 target combinations** — this was never T15's job to produce (that's `IDE-04`/`IDE-05`, tracked separately in `docs/compatibility-ledger.md`), but it means "release" here can only ever mean "release of the fake-backed foundation," never a claim of real IDE support.
4. **The CI workflow has not been executed on an actual runner.**
5. **GW-05 bounded timeout/cancellation remains incomplete** for blocking adapter calls: typed timeout/cancellation errors release the lease, but no deadline or interrupt mechanism exists for an adapter call that remains blocked.

## Items requiring independent reviewer sign-off

1. Whether the `GW-05`/`DE-08`/`DE-06` fixes and their regression tests are accepted as correctly scoped (not over- or under-reaching).
2. The three open case-data-handling policy decisions in `docs/security.md`'s "T15 case-data handling review" section.
3. Whether `.github/workflows/tests.yml` should be enabled as a required check once it has run successfully on a real PR.
4. Whether `T15`'s checkbox in `tasks.md` can be checked — per this task's own explicit instruction, it is being **left unchecked** pending this independent sign-off, regardless of the technical state above.
