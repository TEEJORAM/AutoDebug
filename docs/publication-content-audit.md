# Publication content audit - 2026-10-24

## Classification rules

`PUBLIC-SAFE` means no identified private locator, actual credential, employee
identity or proprietary payload in the reviewed current file. It is **not** a
license grant, ownership finding or guarantee of absence of unknown secrets.
All files still require the project's overall distribution authorization.

`REQUIRES-SANITIZATION` means identified nonpublic content remains.
`REQUIRES-LEGAL/OWNER REVIEW` means provenance, internal-context references,
approval records, policy, vendor terms or redistribution require an authorized
decision. Historical versions are classified separately: sanitizing current
files does not sanitize their history.

## Current files (including new preparation files)

Completeness checked against Git's tracked plus nonignored untracked inventory:
**98 files: 65 PUBLIC-SAFE, 33 REQUIRES-LEGAL/OWNER REVIEW**. The original
83-file strict-review inventory remains intact; 15 closure/build/release files
are added. No missing,
extra or duplicate current-file entries. No current identified locator remains
classified REQUIRES-SANITIZATION; historical disclosures below remain unresolved.

| File | Classification | Basis |
|---|---|---|
| `.github/workflows/tests.yml` | PUBLIC-SAFE | Generic CI, no credentials or company infrastructure |
| `.gitignore` | PUBLIC-SAFE | Generic exclusions |
| `CLAUDE.md` | REQUIRES-LEGAL/OWNER REVIEW | Autodesk/Fusion safety and development policy/provenance |
| `CONTRIBUTING.md` | REQUIRES-LEGAL/OWNER REVIEW | External contribution and ownership terms pending |
| `README.md` | REQUIRES-LEGAL/OWNER REVIEW | Company provenance and publication authorization |
| `SECURITY.md` | REQUIRES-LEGAL/OWNER REVIEW | Private disclosure contact/policy must be approved |
| `pyproject.toml` | REQUIRES-LEGAL/OWNER REVIEW | No assigned license; exact original-build candidate needs owner/distribution review |
| `docs/architecture.md` | REQUIRES-LEGAL/OWNER REVIEW | Generic design with historical company/product context |
| `docs/compatibility-ledger.md` | REQUIRES-LEGAL/OWNER REVIEW | Historical integration observations need owner release review |
| `docs/decisions.md` | REQUIRES-LEGAL/OWNER REVIEW | Generalized internal references; vendor terms/provenance |
| `docs/ide-integrations.md` | REQUIRES-LEGAL/OWNER REVIEW | Third-party and internal-bridge reuse boundaries |
| `docs/license-and-dependency-review.md` | REQUIRES-LEGAL/OWNER REVIEW | Explicit unresolved rights and approval inventory |
| `docs/mcp-contract.md` | PUBLIC-SAFE | Generic original draft contract and synthetic examples |
| `docs/publication-content-audit.md` | REQUIRES-LEGAL/OWNER REVIEW | Publication/disclosure classification requires owner acceptance |
| `docs/publication-readiness-assessment.md` | REQUIRES-LEGAL/OWNER REVIEW | Contains approval blockers and historical disclosure categories |
| `docs/release-readiness-checklist.md` | REQUIRES-LEGAL/OWNER REVIEW | Historical review and pending release authorization |
| `docs/risks.md` | REQUIRES-LEGAL/OWNER REVIEW | Enterprise/integration policy risks |
| `docs/security-gate-closure-proposal.md` | REQUIRES-LEGAL/OWNER REVIEW | Company security-policy and historical integration context |
| `docs/security.md` | REQUIRES-LEGAL/OWNER REVIEW | Data handling and company security policy |
| `docs/status.md` | REQUIRES-LEGAL/OWNER REVIEW | Historical work/approval records; locators generalized |
| `docs/test-plan.md` | REQUIRES-LEGAL/OWNER REVIEW | Historical host/integration claims and product safety context |
| `docs/traceability.md` | PUBLIC-SAFE | Generic requirement/task/test mapping |
| `docs/upgrade-rollback.md` | REQUIRES-LEGAL/OWNER REVIEW | Release/data policy and historical distribution context |
| `docs/vscode-debugmcp-mapping.md` | REQUIRES-LEGAL/OWNER REVIEW | Vendor schema assumptions and reuse terms unverified |
| `openspec/README.md` | REQUIRES-LEGAL/OWNER REVIEW | Company-context development workflow |
| `openspec/changes/autodebug-foundation/proposal.md` | REQUIRES-LEGAL/OWNER REVIEW | Original product scope and company-related provenance |
| `openspec/changes/autodebug-foundation/design.md` | REQUIRES-LEGAL/OWNER REVIEW | Approval/security design and unresolved enterprise policy |
| `openspec/changes/autodebug-foundation/tasks.md` | REQUIRES-LEGAL/OWNER REVIEW | Historical approval/work records; identity/locators generalized |
| `openspec/changes/autodebug-foundation/specs/debugging-and-evidence/spec.md` | REQUIRES-LEGAL/OWNER REVIEW | Normative security/data behavior |
| `openspec/changes/autodebug-foundation/specs/gateway-and-sessions/spec.md` | PUBLIC-SAFE | Generic debugger routing requirements |
| `openspec/changes/autodebug-foundation/specs/ide-compatibility/spec.md` | REQUIRES-LEGAL/OWNER REVIEW | Internal-adapter nonredistribution and vendor boundaries |
| `openspec/changes/autodebug-foundation/specs/reproduction-and-approval/spec.md` | REQUIRES-LEGAL/OWNER REVIEW | Historical Fusion workflow and authorization policy |
| `openspec/changes/publication-hardening/proposal.md` | REQUIRES-LEGAL/OWNER REVIEW | Technical authorization is not distribution permission |
| `openspec/changes/publication-hardening/spec.md` | PUBLIC-SAFE | Generic security requirement clarification |
| `openspec/changes/publication-hardening/design.md` | PUBLIC-SAFE | Original bounded fake-only repair design |
| `openspec/changes/publication-hardening/tasks.md` | REQUIRES-LEGAL/OWNER REVIEW | Outstanding approval records |
| `src/autodebug/__init__.py` | PUBLIC-SAFE | Generic original package code |
| `src/autodebug/adapters/__init__.py` | PUBLIC-SAFE | Generic adapter enumeration |
| `src/autodebug/adapters/base.py` | PUBLIC-SAFE | Generic adapter/capability abstractions |
| `src/autodebug/adapters/clion.py` | PUBLIC-SAFE | Original mock-tested protocol abstraction, not certified native support |
| `src/autodebug/adapters/cursor.py` | PUBLIC-SAFE | Same boundary; no copied vendor implementation identified |
| `src/autodebug/adapters/visual_studio.py` | PUBLIC-SAFE | Same boundary; not an internal bridge redistribution |
| `src/autodebug/adapters/vscode.py` | PUBLIC-SAFE | Original external-service abstraction; not DebugMCP source |
| `src/autodebug/adapters/xcode.py` | PUBLIC-SAFE | Original mock-tested abstraction |
| `src/autodebug/approvals.py` | PUBLIC-SAFE | Generic fake-only prototype; no credential persistence |
| `src/autodebug/errors.py` | PUBLIC-SAFE | Generic structured errors |
| `src/autodebug/evidence.py` | PUBLIC-SAFE | Generic evidence/sanitization implementation |
| `src/autodebug/facade.py` | PUBLIC-SAFE | Generic fake-only facade |
| `src/autodebug/models.py` | PUBLIC-SAFE | Generic typed draft schemas |
| `src/autodebug/plans.py` | PUBLIC-SAFE | Generic plan validation/digest logic |
| `src/autodebug/router.py` | PUBLIC-SAFE | Generic session routing |
| `src/autodebug/sessions.py` | PUBLIC-SAFE | Generic in-memory registry/leases |
| `src/autodebug/workflow.py` | PUBLIC-SAFE | Generic case-state workflow |
| `tests/__init__.py` | PUBLIC-SAFE | Empty package marker |
| `tests/fixtures/__init__.py` | PUBLIC-SAFE | Empty package marker |
| `tests/fixtures/fake_adapter.py` | PUBLIC-SAFE | Disposable synthetic fake debugger |
| `tests/fixtures/fake_backend.py` | PUBLIC-SAFE | Synthetic capability inventory |
| `tests/fixtures/fake_clion_client.py` | PUBLIC-SAFE | In-memory mock, not vendor source |
| `tests/fixtures/fake_cursor_client.py` | PUBLIC-SAFE | In-memory mock |
| `tests/fixtures/fake_debugmcp_client.py` | PUBLIC-SAFE | In-memory mock, not DebugMCP source |
| `tests/fixtures/fake_visual_studio_client.py` | PUBLIC-SAFE | In-memory mock, no internal bridge code identified |
| `tests/fixtures/fake_xcode_client.py` | PUBLIC-SAFE | In-memory mock |
| `tests/test_adapters.py` | PUBLIC-SAFE | Host-independent synthetic adapter checks |
| `tests/test_approvals.py` | PUBLIC-SAFE | Synthetic approval records and example-domain emails |
| `tests/test_capability_probing.py` | PUBLIC-SAFE | Synthetic OS/capability matrix |
| `tests/test_clion_adapter.py` | PUBLIC-SAFE | Mock-only tests |
| `tests/test_cross_platform_certification.py` | PUBLIC-SAFE | Simulated platforms, not native certification |
| `tests/test_cursor_adapter.py` | PUBLIC-SAFE | Mock-only tests |
| `tests/test_evidence.py` | PUBLIC-SAFE | Synthetic secret-shaped sentinels, no actual key identified |
| `tests/test_facade.py` | PUBLIC-SAFE | Disposable fake sessions, synthetic paths/identities |
| `tests/test_plans.py` | PUBLIC-SAFE | Synthetic plans |
| `tests/test_publication_evidence.py` | PUBLIC-SAFE | Disposable symlinks/hardlinks/FIFO, synthetic markers |
| `tests/test_publication_security.py` | PUBLIC-SAFE | Disposable fake approval/pause/lease/budget regressions |
| `tests/test_router.py` | PUBLIC-SAFE | Synthetic routing scenarios |
| `tests/test_sessions.py` | PUBLIC-SAFE | Synthetic process/session identities |
| `tests/test_strict_final_security.py` | PUBLIC-SAFE | Disposable strict-review identity, concurrency, cancellation, redaction and persistence regressions |
| `tests/test_t14_bug_to_evidence_demo.py` | PUBLIC-SAFE | Fictional application/bug and fake observations |
| `tests/test_t15_contract_conformance.py` | PUBLIC-SAFE | Draft contract checks |
| `tests/test_t15_security_release_gate.py` | PUBLIC-SAFE | Synthetic approval/evidence/concurrency tests |
| `tests/test_visual_studio_adapter.py` | PUBLIC-SAFE | Mock-only tests |
| `tests/test_vscode_adapter.py` | PUBLIC-SAFE | Mock-only tests |
| `tests/test_workflow.py` | PUBLIC-SAFE | Synthetic case transitions |
| `tests/test_xcode_adapter.py` | PUBLIC-SAFE | Mock-only tests |
| `build_backend.py` | PUBLIC-SAFE | Original stdlib-only offline package builder |
| `src/autodebug/__main__.py` | PUBLIC-SAFE | Generic executable entry point |
| `src/autodebug/operations.py` | PUBLIC-SAFE | Generic bounded worker/cancellation logic |
| `src/autodebug/server.py` | PUBLIC-SAFE | Original public-protocol stdio binding; public MCP documentation references only |
| `src/autodebug/synthetic.py` | PUBLIC-SAFE | Isolated in-memory fake, no native process access |
| `tests/test_server.py` | PUBLIC-SAFE | Disposable protocol/build/synthetic tests |
| `tests/test_technical_closure.py` | PUBLIC-SAFE | Synthetic security/correctness regression tests |
| `openspec/changes/technical-closure/spec.md` | PUBLIC-SAFE | Generic requirement delta |
| `openspec/changes/technical-closure/design.md` | PUBLIC-SAFE | Original fake-only technical design |
| `openspec/changes/technical-closure/proposal.md` | REQUIRES-LEGAL/OWNER REVIEW | Work authorization/provenance, not distribution permission |
| `openspec/changes/technical-closure/tasks.md` | REQUIRES-LEGAL/OWNER REVIEW | Technical completion and retained approval boundaries |
| `docs/installation.md` | PUBLIC-SAFE | Generic offline setup and synthetic protocol examples |
| `docs/release-notes.md` | PUBLIC-SAFE | Generic unreleased capability/limitation inventory |
| `docs/technical-closure-report.md` | REQUIRES-LEGAL/OWNER REVIEW | Security findings, requirements dispositions and release-policy context |
| `docs/ossa-legal-approval-request.md` | REQUIRES-LEGAL/OWNER REVIEW | Ownership/release/account/AI policy decisions require authorized signers |

No current identified internal URL, actual employee email or workstation locator
remains in these source-controlled documents after generalization. Public vendor
URLs and example-domain emails are deliberately retained. Generated bytecode and
Git administrative files are not publication source artifacts; no environment
files, binaries, credentials or real captured datasets are approved for release.

## Exact owner decisions for the 33 review-classified files

Each row below supplements the specific reason in the classification table.
Technical approval does not make any of these distribution decisions.

| File | Required authorized decision |
|---|---|
| `CLAUDE.md` | Approve release of company/product development constraints and provenance; retain legitimate ownership evidence |
| `CONTRIBUTING.md` | Approve contribution ownership/rights policy and who may accept external contributions |
| `README.md` | Approve public project description, company attribution and distribution claims |
| `SECURITY.md` | Designate a staffed private disclosure channel and approve response/disclosure policy |
| `pyproject.toml` | Confirm copyright owner, authorized license metadata and reviewed build-tool version/terms |
| `docs/architecture.md` | Approve disclosure of product-context architecture examples as original releasable work |
| `docs/compatibility-ledger.md` | Approve publication of historical workstation/integration observations and their limitations |
| `docs/decisions.md` | Approve retained decision provenance and public vendor reference/usage terms |
| `docs/ide-integrations.md` | Approve external bridge terms and exclusion of unapproved internal bridge redistribution |
| `docs/license-and-dependency-review.md` | Resolve ownership, license, third-party notices and exact approved dependency inventory |
| `docs/publication-content-audit.md` | Accept classifications and authorize disclosure of the audit itself |
| `docs/publication-readiness-assessment.md` | Authorize disclosure of findings/history-risk categories and accept unresolved blockers |
| `docs/release-readiness-checklist.md` | Name authorized security/release approvers and record genuine sign-offs |
| `docs/risks.md` | Approve disclosure of enterprise-policy and integration risk assessments |
| `docs/security-gate-closure-proposal.md` | Approve release of company-policy/integration context; do not convert proposed gate closure into approval |
| `docs/security.md` | Approve data classes, model routing, evidence permissions/location, retention and trusted approval design |
| `docs/status.md` | Approve release of historical work and approval records without erasing attribution |
| `docs/test-plan.md` | Approve historical host/product testing context and permitted disposable datasets |
| `docs/upgrade-rollback.md` | Approve release/data lifecycle, retention/deletion and rollback policy |
| `docs/vscode-debugmcp-mapping.md` | Confirm public schema provenance and permitted vendor interface/terms use |
| `openspec/README.md` | Approve disclosure of company-context specification workflow |
| `openspec/changes/autodebug-foundation/proposal.md` | Approve ownership and disclosure of original scope/product proposal |
| `openspec/changes/autodebug-foundation/design.md` | Approve security/trust design and disclosure of enterprise-policy assumptions |
| `openspec/changes/autodebug-foundation/tasks.md` | Approve release of historical work/approval records with provenance preserved |
| `openspec/changes/autodebug-foundation/specs/debugging-and-evidence/spec.md` | Approve normative evidence/privacy policy and its publication |
| `openspec/changes/autodebug-foundation/specs/ide-compatibility/spec.md` | Confirm internal-adapter exclusion, vendor terms and distribution boundaries |
| `openspec/changes/autodebug-foundation/specs/reproduction-and-approval/spec.md` | Approve product-specific reproduction constraints and independent human authorization policy |
| `openspec/changes/publication-hardening/proposal.md` | Confirm technical repair authorization is accurately recorded and is not distribution permission |
| `openspec/changes/publication-hardening/tasks.md` | Accept technical completion records while leaving human/legal/publication gates open |
| `openspec/changes/technical-closure/proposal.md` | Confirm broad technical implementation approval is accurate and does not authorize distribution/native access |
| `openspec/changes/technical-closure/tasks.md` | Accept verified task dispositions while preserving external release/security gates |
| `docs/technical-closure-report.md` | Approve disclosure of new security findings, mitigations, requirement gaps and policy limitations |
| `docs/ossa-legal-approval-request.md` | Assign authorized owner/OSSA/Legal/security decision makers and approve the exact request/artifact/disclosure scope |

## Historical versions: not sanitized

Every historical blob was included, including old `src/dtunnel/` and
`openspec/changes/dtunnel-foundation/` paths. Full object/path inventories are
private review artifacts, not redistributed here.

| Historical file / metadata class | Classification | Remaining risk |
|---|---|---|
| `README.md` | REQUIRES-SANITIZATION | Internal repository locator |
| `docs/decisions.md` | REQUIRES-SANITIZATION | Internal wiki spaces/page identifiers and build guidance locators |
| `docs/ide-integrations.md` | REQUIRES-SANITIZATION | Historical internal integration/repository locator |
| `docs/status.md` | REQUIRES-SANITIZATION | Repository/workstation/home paths and operational snapshots |
| `openspec/changes/autodebug-foundation/tasks.md` and pre-rename counterpart | REQUIRES-SANITIZATION | Reviewer/employee identity and historical integration configuration |
| `docs/compatibility-ledger.md` | REQUIRES-LEGAL/OWNER REVIEW | Prior workstation/integration inventories |
| `docs/security-gate-closure-proposal.md` | REQUIRES-LEGAL/OWNER REVIEW | Prior local tool/policy inventories |
| `docs/license-and-dependency-review.md` | REQUIRES-SANITIZATION | Internal repository locator and prior distribution context |
| All commit authors/committers/messages/trailers | REQUIRES-LEGAL/OWNER REVIEW | Employee email/identity, provenance, ownership and consent |
| Remaining historical documentation and foundation specifications | REQUIRES-LEGAL/OWNER REVIEW | Company work-product/security/product context and vendor references |
| Historical current-name/pre-rename source, tests and configuration | PUBLIC-SAFE | No actual credential/proprietary payload identified by inventory; legal ownership still unresolved |

Sanitization means authorized disposition is still needed, **not** permission to
rewrite history. Existing history must not be pushed publicly as-is. Removing
attribution or reassigning ownership is not a remediation. Preserve the original
private review record and obtain Autodesk owner/OSSA/Legal decisions first.
