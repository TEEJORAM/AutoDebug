# AutoDebug — Spec-Driven Development

**Status: operational fake-only MCP stdio gateway; publication BLOCKED.**
All five IDE adapters (VS Code, Cursor, CLion, Visual Studio, Xcode) are
mock-tested abstractions, **not native-debugger-certified integrations**.
The real-debugger authorization gate remains **OPEN / NOT APPROVED**.
The dependency-free stdio transport exposes 15 tools and a standalone synthetic
demonstration, without a network listener, approval tool, shell, or evaluation.
See [current results](docs/status.md), the [complete requirement matrix](docs/technical-closure-report.md),
and the [compatibility ledger](docs/compatibility-ledger.md) (zero native `PASS` cells).
**Updated:** 24 October 2026

**Implementation frozen for this iteration.** The verified 63-file foundation
is preserved in local commit `736cc154dda574a54bfc4f42ebf16d6980d71ac1`.
This publication-finalization pass changes documentation only; it does not
enable native integrations or reopen implementation work.

## What AutoDebug does

A developer can give Claude a Jira issue or bug description. The intended workflow is for Claude to study source and application API documentation, then propose a reviewable breakpoint and reproduction plan. After a distinct developer approval, a verified AutoDebug adapter would use the application's existing native IDE debugger and collect evidence. **That end-to-end native-debugger workflow is not currently implemented or validated:** the current facade and adapters are fake/mock-backed, and the T05 real-debugger gate remains open.

AutoDebug is a local Python MCP **tool server**, not an LLM or second AI agent.
Source/Jira/API-doc analysis and causal reasoning belong to the client.
AutoDebug owns verified routing, immutable script/plan validation, scoped
authorization, bounded operations and sanitized local evidence. Its operational
transport is MCP 2025-11-25 newline-delimited JSON-RPC over stdio. Real IDE use
still requires approved, verified integrations and a trusted local human broker.

## Supported IDEs and operating systems

| IDE | Windows | macOS | Linux |
|---|---|---|---|
| VS Code | Target | Target | Target |
| Cursor | Target | Target | Target |
| CLion | Target | Target | Target |
| Visual Studio | Target | — | — |
| Xcode | — | Target | — |

**11 target IDE/OS combinations.** These are design targets, not claims of verified support — each is proven incrementally, one IDE at a time, against a real disposable test application (see `openspec/changes/autodebug-foundation/specs/ide-compatibility/spec.md`).

## Architecture and native integration boundary

```text
Developer → Claude (reads Jira/source/API docs, proposes plan)
         → AutoDebug MCP stdio server → policy/approval/session/evidence facade
         → isolated synthetic adapter (operational)
         → IDE adapter (mock-tested only; native access BLOCKED)
         → the IDE's own, already-running native debugger
         → target application
```

Claude never talks to an IDE directly, and AutoDebug never runs a second debugger behind the IDE's back. See `docs/architecture.md` for the full component diagram and sequence flow.

## Intended end-to-end workflow

1. Developer provides a Jira ticket or bug description.
2. Claude analyzes source code and reproduction steps.
3. Claude examines available application API documentation.
4. Claude prepares a reproduction script (if the API supports it) or manual steps.
5. Claude proposes breakpoints.
6. **Developer reviews and approves the complete plan** — this is the one mandatory gate before any debugger action.
7. AutoDebug may launch or attach through an approved, supported native IDE integration.
8. Breakpoints are verified as bound before reproduction, wherever technically possible.
9. Developer executes the approved script through the application's existing mechanism (e.g. Fusion's Scripts and Add-Ins), or performs manual steps.
10. Claude investigates debugger observations one bounded operation at a time.
11. AutoDebug saves local, sanitized structured evidence.
12. Claude produces a concise root-cause report with evidence references and a justified `CONFIRMED` / `LIKELY` / `INCONCLUSIVE` confidence level.

Full normative detail for this flow lives in the `reproduction-and-approval` and `debugging-and-evidence` specs, not here.

## Local setup and tests

Use Python **3.11 or 3.12**, the versions configured in CI. The package declares
Python `>=3.11`; compatibility with an Autodesk enterprise toolchain still needs
review. Tests use the standard-library `unittest` runner; no package installation,
MCP SDK, `pytest`, or `ruff` is required. Run from the repository root:

```sh
# macOS / Linux
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

```powershell
# Windows PowerShell: contract-only subset, not the full workflow suite
$env:PYTHONPATH = "src"
python -m unittest tests.test_adapters tests.test_capability_probing tests.test_sessions tests.test_router tests.test_plans tests.test_workflow tests.test_approvals tests.test_cross_platform_certification tests.test_t15_contract_conformance tests.test_server.TestBinding tests.test_server.TestOfflinePackaging -v
```

CI is configured for the full suite on Linux/macOS and contract-only checks on
Windows on both Python versions. Secure evidence persistence currently requires
POSIX descriptor-relative no-follow opens; Windows evidence workflows fail
closed and are **BLOCKED**, not certified portable. A workflow
definition is **not** evidence of a successful CI run; see `docs/status.md` for
observed local results. Tests exercise fake/mock backends, not installed IDEs.
For an isolated, disposable demonstration (POSIX host, private evidence directory
outside this checkout):

```sh
PYTHONPATH=src python3 -m autodebug --evidence-dir /private/path/to/autodebug-evidence --demo
```

The command reads MCP JSON-RPC on stdin; it is not an interactive shell.
`--demo` locally seeds only `AUTODEBUG-DEMO` with synthetic approval and a
predetermined fake stop. It cannot authorize any real adapter. Without `--demo`,
mutating requests remain unapproved. See [installation and protocol smoke test](docs/installation.md).

No Autodesk-only runtime dependency, internal network service, Jira access,
installed IDE, or package installation is needed for generic source-tree tests.
An original stdlib-only PEP 517 backend builds local wheels/source archives
without third-party build dependencies. Offline archive/isolated-import tests
are not distribution authorization. No top-level license is assigned.

## Publication status

**BLOCKED pending four external decisions:**

1. Permission to publish or transfer this Autodesk-developed repository.
2. Approved copyright, license and required notices.
3. Approval of the exact public artifact, destination and history treatment.
4. Permission to develop transferred code using personal accounts/equipment;
   personal AI-service use also requires explicit permission, not an assumption.

No license is assigned or ownership transferred by this preparation.
Current-tree cleanup does not sanitize Git history. Do not push this checkout's
existing history as the public release. See the [approval request](docs/ossa-legal-approval-request.md)
and [publication steps](docs/installation.md#publication-after-permission).
Native-debugger authorization and unverified platform capabilities remain
unchanged limitations, not promises of this fake-only release.

## Contributor workflow

See [CONTRIBUTING.md](CONTRIBUTING.md) for the review-first, one-task workflow and
[SECURITY.md](SECURITY.md) for private vulnerability reporting.

### Using this repository with Claude Code

1. Open an authorized checkout as your Claude Code working directory. `CLAUDE.md` loads automatically — you don't need to paste every Markdown file into chat. No public repository location is designated here.
2. Confirm `claude --version` works; if missing, get it installed through your organization's approved channel.
3. Start a session in this folder and ask Claude to review the specs (see "Start here" below). **Do not authorize implementation** until you've reviewed and approved the proposal, design and tasks.
4. After approval, give Claude exactly one task ID from `openspec/changes/autodebug-foundation/tasks.md` and ask it to implement and test **only that task**.
5. Record what changed at the end of each session in `docs/status.md` (template included there) so a fresh session can resume from that file alone.

## Start here

1. Read **[CLAUDE.md](CLAUDE.md)** — instructions Claude Code automatically loads from the project root.
2. Open **[the foundation proposal](openspec/changes/autodebug-foundation/proposal.md)** — what we're asking to build, and why.
3. Review the four capability specs and [design](openspec/changes/autodebug-foundation/design.md) **before** approving any coding.
4. Check **[current status](docs/status.md)** for the live approval/blocker state.
5. Implement **one task at a time** from [tasks.md](openspec/changes/autodebug-foundation/tasks.md), with a test and review after each task.

## Key boundaries

- **Claude is the investigator.** AutoDebug is an MCP tool server, not a second autonomous agent.
- **Functional bugs first**; profiling/performance investigation is deferred.
- **Human approval before launch/attach, breakpoint setup, or script execution**, with review of the *full* proposed script — approval is independent of the AI agent's own tool-calling ability.
- **No new Fusion in-app helper.** The developer triggers execution through the existing Fusion Scripts and Add-Ins UI; if the API can't reproduce the issue, manual steps are used instead.
- **No copying of DebugMCP (or any third-party) source.** Integrate only through existing, permitted MCP/public APIs, after the required internal approvals.
- **No claim of working IDE support without proof.** Availability and capabilities are probed and tested per IDE/OS, never assumed.

## Documentation map

| File | Purpose |
|---|---|
| `CLAUDE.md` | Claude's project-specific guardrails and repeatable workflow |
| `openspec/README.md` | How the spec-driven workflow and document types fit together |
| `openspec/changes/autodebug-foundation/proposal.md` | Business/engineering intent, scope and non-goals |
| `openspec/changes/autodebug-foundation/specs/*/spec.md` | **Authoritative, observable requirements** — Given/When/Then acceptance scenarios |
| `openspec/changes/autodebug-foundation/design.md` | Design decisions and implementation approach |
| `openspec/changes/autodebug-foundation/tasks.md` | Ordered, small work items and approval gates |
| `docs/architecture.md` | Component ownership, sequence diagram, worked example, report format |
| `docs/ide-integrations.md` | Per-IDE adapter approach and the 11-target platform matrix |
| `docs/mcp-contract.md` | Tool names, request/response shapes, error codes, data models |
| `docs/security.md` | Threats, required controls, approval requirements, safe defaults |
| `docs/test-plan.md` | Test layers, deterministic test cases, compatibility ledger |
| `docs/decisions.md` | Architectural decision records (ADRs) and external references |
| `docs/traceability.md` | Requirement → implementation task → test-case mapping |
| `docs/risks.md` | Risk register, decision gates, and assumptions to verify |
| `docs/upgrade-rollback.md` | Source-tree upgrade/rollback, case-data handling across schema versions (T15) |
| `docs/license-and-dependency-review.md` | Dependency/license inventory and unresolved Autodesk approvals (T15) |
| `docs/release-readiness-checklist.md` | T15 acceptance-to-evidence mapping and pending release/publication gates |
| `docs/status.md` | Current milestone, approval state, blockers, next action |

Requirements and acceptance scenarios live **only** in `openspec/`; everything under `docs/` is reference material that links to those requirements rather than restating them.

## Source control and confidential data

Store debugging captures, generated reproduction scripts, session tokens, Jira exports
and confidential files **outside source control**, in a private location outside the
checkout. `.gitignore` is defense in depth, not a confidentiality boundary. Check
Autodesk AI/third-party approvals before connecting to source repositories, Jira,
production data or debuggers.

## Provenance and publication status

AutoDebug originated in an Autodesk-related development context. Fusion examples
record that historical context, not product integration or permission to use company
data: only the existing Fusion scripting UI or already-approved supported facilities
may be used; no new helper, embedded server, or undocumented injection is allowed.

**Publication preparation is authorized; publication is not.** No `LICENSE` file
has been assigned. Do not infer personal ownership, an open-source license, or legal
approval from this documentation or passing tests. Autodesk ownership/copyright,
OSSA/Legal, dependency/third-party, and full Git-history release approvals remain
required. Current-tree sanitization does not sanitize historical blobs, commit
identities, messages, or trailers. See
[license and dependency review](docs/license-and-dependency-review.md) and the
[release checklist](docs/release-readiness-checklist.md).
