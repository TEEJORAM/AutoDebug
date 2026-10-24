# AutoDebug

A local MCP tool server that lets an AI client (such as Claude) investigate
bugs through a developer's **existing native IDE debugger**, behind explicit,
plan-bound human approval.

> **Status: fake-only foundation.** The MCP server, case workflow, approval
> checks and evidence store work against a synthetic debugger. The five IDE
> adapters are tested only against mocks, and real debugger control is
> disabled (security gate **OPEN / NOT APPROVED**). Publication is **BLOCKED**
> pending Autodesk approvals; see [docs/publication.md](docs/publication.md).

## Quick start

AutoDebug is a command-line MCP server: your AI client starts it for you.
Requires Python 3.11+.

```sh
# 1. In your AutoDebug folder (the one containing pyproject.toml):
pip install -e .                                    # Windows: py -m pip install -e .

# 2. Anywhere:
autodebug doctor                                    # Windows: py -m autodebug doctor

# 3. In the project folder you open in VS Code:
autodebug config vscode --demo > .vscode/mcp.json   # or claude-code, claude-desktop, cursor
```

Then start `autodebug` from your client and ask it to investigate the synthetic
case `AUTODEBUG-DEMO`. **[docs/getting-started.md](docs/getting-started.md)**
gives exact steps for Windows, macOS and Linux, and explains what works today:
clients can connect now, but AutoDebug cannot yet drive your real IDE debugger.

## How it works

```text
Developer → AI client (reads bug, source, API docs; proposes a plan)
          → AutoDebug MCP server (plan, approval, session and evidence checks)
          → IDE adapter → the IDE's own running debugger → application
```

1. The developer gives the AI client a bug report.
2. The client stages a plan: target, breakpoints, and a reproduction script or
   manual steps.
3. **The developer approves that exact plan** through a trusted local surface
   (not built yet; only `--demo` issues a synthetic approval). The approval is
   bound to the plan digest, target, scope and expiry.
4. AutoDebug launches or attaches through a supported adapter and confirms
   every breakpoint is bound.
5. The developer reproduces the bug (scripts run in the application's own UI;
   AutoDebug never runs them).
6. The client inspects stop, stack and selected variables one bounded step at
   a time. AutoDebug redacts and records evidence locally.
7. The client writes a root-cause report citing evidence IDs, labelled
   `CONFIRMED`, `LIKELY` or `INCONCLUSIVE`.

## Targets

| IDE | Windows | macOS | Linux |
|---|---|---|---|
| VS Code | target | target | target |
| Cursor | target | target | target |
| CLion | target | target | target |
| Visual Studio | target | — | — |
| Xcode | — | target | — |

These are design targets. None is certified yet; current results are in the
[compatibility ledger](docs/compatibility-ledger.md).

## Boundaries

- The AI client is the investigator; AutoDebug is a tool server with no LLM.
- No approval tool is exposed to the agent, and agent chat is never treated as
  human approval.
- No expression evaluation, shell, script execution or network listener.
- Never a second, hidden debugger; unsupported operations report `UNSUPPORTED`.
- No copied third-party code (for example Microsoft DebugMCP); integrations
  only through approved, public interfaces.
- Functional bugs first; performance profiling is out of scope.

## Documentation

| Read | For |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | Install, connect a client, run the demo |
| [docs/status.md](docs/status.md) | What works, open blockers, verification |
| [docs/architecture.md](docs/architecture.md) | Components, source layout, investigation flow |
| [docs/mcp-contract.md](docs/mcp-contract.md) | Tools, data model, approval binding, error codes |
| [docs/security.md](docs/security.md) | Threats, controls, case-data policy |
| [docs/ide-integrations.md](docs/ide-integrations.md) | Per-IDE approach and adapter mapping |
| [docs/compatibility-ledger.md](docs/compatibility-ledger.md) | Per-IDE/OS test results |
| [docs/test-plan.md](docs/test-plan.md) | Test layers, test cases, certification steps |
| [docs/traceability.md](docs/traceability.md) | Requirement status and tests |
| [docs/installation.md](docs/installation.md) | Raw protocol use, packaging, upgrades |
| [docs/publication.md](docs/publication.md) | Approvals needed to publish or license |
| [docs/decisions.md](docs/decisions.md), [docs/risks.md](docs/risks.md) | Design decisions, risk register |
| [docs/release-notes.md](docs/release-notes.md) | Changes |
| `openspec/` | Normative requirements, design and tasks |

Requirements live only in `openspec/`; `docs/` explains them.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (one approved task at a time, tests with
every change) and [SECURITY.md](SECURITY.md) for private vulnerability reports.
Keep debugger captures, tokens and Jira exports out of the repository.
