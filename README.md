# AutoDebug

A local MCP tool server that lets an AI client (such as Claude) investigate
bugs through a developer's **existing native IDE debugger**, behind explicit,
plan-bound human approval.

> **Status:** AutoDebug runs the real debugger in **VS Code and Cursor**
> through the AutoDebug Bridge extension, and only after you click **Approve**
> in the IDE. It is verified by automated tests, including the real Python
> debugger (debugpy); the first run in a real VS Code window is still to be
> recorded. CLion, Visual Studio and Xcode are not supported yet. Publication is
> **BLOCKED** pending Autodesk approvals; see [docs/publication.md](docs/publication.md).

## Quick start

Requires **Python 3.11 or newer** and **Git**. AutoDebug is a command-line MCP
server: you install it once, and your AI client starts it for you.

### 1. Install

**Windows (PowerShell):**

```powershell
git clone https://github.com/TEEJORAM/AutoDebug.git
cd AutoDebug
py -m pip install -e .
py -m autodebug doctor
```

**macOS / Linux:**

```sh
git clone https://github.com/TEEJORAM/AutoDebug.git
cd AutoDebug
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
autodebug doctor
```

`doctor` should show `✔` for Python, Evidence storage and Evidence folder, and
end with `Ready`. **Already have AutoDebug?** Run `git pull` in its folder, then
the `pip install -e .` line again. The same steps, switched by operating system, are at
<https://teejoram.github.io/AutoDebug/> (`site/index.html`). `autodebug guide`
prints them for the machine you are on.

### 2. Install the AutoDebug Bridge in VS Code

You need VS Code with the Python extension. From the AutoDebug folder:

**Windows (PowerShell):**

```powershell
py -m autodebug bridge install vscode
```

**macOS / Linux:**

```sh
autodebug bridge install vscode
```

Then in VS Code run **Developer: Reload Window**; the status bar shows
**AutoDebug**. If the command says `code` is not on PATH, it prints the path of
a `.vsix` file: in VS Code open **Extensions** → **···** → **Install from
VSIX…** and choose it. For Cursor, use `bridge install cursor`.

### 3. Connect a project

The sample project [examples/AutoDebugDemo](examples/AutoDebugDemo/README.md)
has one deliberate bug: moving a shape changes its area. Still in the AutoDebug
folder (use your own project folder later):

**Windows (PowerShell):**

```powershell
py -m autodebug config vscode --write examples\AutoDebugDemo
```

**macOS / Linux:**

```sh
autodebug config vscode --write examples/AutoDebugDemo
```

This writes `.vscode/mcp.json` in that folder and keeps any other servers in it.

### 4. Debug with the AI agent

1. In VS Code, **File → Open Folder** → `examples/AutoDebugDemo` inside AutoDebug.
2. Command Palette (`Ctrl+Shift+P`, macOS `Cmd+Shift+P`) → **MCP: List Servers**
   → **autodebug** → **Start Server** (or **Restart Server**).
3. Open Copilot Chat in **Agent** mode and ask:

   > Help to debug AutoDebugDemo using the autodebug tools. Bug: moving a shape
   > changes its area (the "Debug tests" launch configuration shows it). Choose
   > breakpoints in the code that computes the area, request my approval, then
   > step through it to find the cause. Finish the case with the problem, root
   > cause, solution and evidence, and tell me where the report is.

4. VS Code shows a dialog with exactly what will run: launch configuration,
   breakpoints, step and time limits. Click **Approve**.

The agent stops at its breakpoints, reads the stack and variables, steps
through the loop and writes `autodebug-reports/DEMO-AREA-MOVE.md`: problem,
timeline of every stop and step, root cause and fix.

**Practice without a debugger:** `config vscode --demo --write FOLDER` connects
a built-in synthetic debugger instead (case `AUTODEBUG-DEMO`; ask *"Use the
autodebug tools to investigate case AUTODEBUG-DEMO"*). It needs no extension
and no approval. **[docs/getting-started.md](docs/getting-started.md)** covers
Cursor, Claude Desktop and Claude Code, and troubleshooting.

## How it works

```text
Developer → AI client (reads bug, source, API docs; proposes a plan)
          → AutoDebug MCP server (plan, approval, session and evidence checks)
          → AutoDebug Bridge extension → the IDE's own debugger → application
```

1. The developer gives the AI client a bug report.
2. The client reads the code and stages a plan: launch configuration, optional
   build task, breakpoints and limits.
3. **The developer approves that exact plan** by clicking **Approve** in the
   IDE's dialog. The approval is bound to the plan digest, the launch and task
   definitions, the breakpoint files, the IDE window and an expiry; editing any
   of them stops the case.
4. AutoDebug runs the build task, starts the launch configuration under the
   IDE's debugger and confirms every breakpoint is bound.
5. The client inspects stop, stack and selected variables and steps in, over
   or out within the step budget. AutoDebug redacts and records evidence locally.
6. The client completes the case; AutoDebug writes a report citing evidence
   IDs, labelled `CONFIRMED`, `LIKELY` or `INCONCLUSIVE`, into the project.

## Targets

| IDE | Windows | macOS | Linux |
|---|---|---|---|
| VS Code | bridge | bridge | bridge |
| Cursor | bridge | bridge | bridge |
| CLion | target | target | target |
| Visual Studio | target | — | — |
| Xcode | — | target | — |

"bridge" works through the AutoDebug Bridge (tested with automated tests and
the real Python debugger; not yet certified in a real IDE window). "target" is
design scope only. Results are in the [compatibility ledger](docs/compatibility-ledger.md).

## Boundaries

- The AI client is the investigator; AutoDebug is a tool server with no LLM.
- No tool lets the agent approve, and agent chat is never treated as human
  approval: only a click on **Approve** in the IDE counts.
- No expression evaluation, variable changes, shell or script execution. The
  only listener is the bridge's token-protected port on 127.0.0.1.
- Never a second, hidden debugger; unsupported operations report `UNSUPPORTED`.
- No copied third-party code (for example Microsoft DebugMCP); integrations
  only through approved, public interfaces.
- Functional bugs first; performance profiling is out of scope.

## Documentation

| Read | For |
|---|---|
| [site/index.html](site/index.html) | Setup page for Windows, macOS and Linux (published to GitHub Pages) |
| [docs/getting-started.md](docs/getting-started.md) | Install, connect a client, run the demo |
| [examples/AutoDebugDemo](examples/AutoDebugDemo/README.md) | Sample buggy app (Python and C++) to practise on |
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
