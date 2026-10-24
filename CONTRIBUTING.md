# Contributing to AutoDebug

**Publication and external contribution terms are pending authorization.** There is
no assigned `LICENSE`; this guide is not permission to redistribute code or submit
company-owned material publicly. Obtain Autodesk ownership/copyright, OSSA/Legal,
and applicable security approvals first. See
[the license review](docs/license-and-dependency-review.md).

## Frozen publication candidate

Implementation and security remediation are complete for this iteration.
The finalization pass is documentation-only; it does not authorize new features,
refactoring, native debugger access or another audit cycle. The workflow below
applies to future separately authorized changes, not a request to reopen them now.

Before public contributions or personal-account/equipment development, obtain
the four [publication authorizations](docs/ossa-legal-approval-request.md).
Use the [publication procedure](docs/installation.md#publication-after-permission)
only after permission. Preserve legitimate authorship and ownership records;
do not copy private history, evidence, credentials or local review artifacts.

## Review-first workflow

1. Read `README.md`, `CLAUDE.md`, and `docs/status.md`.
2. Read the foundation proposal, relevant complete capability specs, design, and
   task in `openspec/changes/autodebug-foundation/`. Requirements there are normative;
   `docs/` explains them.
3. Obtain explicit human approval for one named task before implementing it.
   A material behavior change needs a new reviewed proposal, requirements delta,
   design, and tasks before code.
4. State the linked requirement IDs and bounded approach. Add or update
   deterministic fake-backed tests alongside the change.
5. Run the standard-library test command in `README.md` on Python 3.11 or 3.12.
   Record the actual interpreter, command, result, and untested platforms; do not
   present configured CI jobs as completed runs.
6. Update directly related docs, `tasks.md`, and `docs/status.md`. Leave unchecked
   gates pending the required independent human/policy review. Submit changes
   only through an authorized review channel; do not publish or push by default.

## Safety and data boundaries

- All five IDE adapters are mock-validated only. MCP stdio and the standalone
  synthetic adapter are operational; no real native IDE support is certified.
  The T05 fake-backend gate remains
  **OPEN / NOT APPROVED** for real debugger control.
- AI tool calls and chat approval strings are not trusted human authorization.
  Do not launch/attach, arm breakpoints, step/continue, evaluate, or run a
  reproduction without the required reviewed authorization.
- Preserve the historical Fusion restriction: the developer uses the existing
  Scripts and Add-Ins UI or already-approved supported facilities. Do not add
  an in-app helper, embedded server, or undocumented injection.
- Use synthetic fixtures and disposable applications only. Do not submit Jira
  exports, customer data, debugger captures, tokens, employee identities,
  workstation paths, or internal repository/wiki/configuration details.
- Keep case data private and outside Git. Ignore rules do not remove already
  tracked content or history. Review staged content before submitting.
- Do not copy, fork, or vendor Microsoft DebugMCP or internal bridge code.
  Dependency installation, external MCP services, and model/data routing require
  applicable Autodesk approval; this guide grants none.

Report suspected vulnerabilities privately following [SECURITY.md](SECURITY.md),
not in public issues or pull requests.
