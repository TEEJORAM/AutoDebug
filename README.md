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
end with `Ready`. The same steps, switched by operating system, are at
<https://teejoram.github.io/AutoDebug/> (`site/index.html`). `autodebug guide`
prints them for the machine you are on.

### 2. Connect VS Code

Run this from the AutoDebug folder. Replace the last part with the project
folder you open in VS Code; AutoDebug writes `.vscode\mcp.json` there and keeps
any other servers already in it.

**Windows (PowerShell):**

```powershell
py -m autodebug config vscode --demo --write D:\Projects\MyApp
```

**macOS / Linux:**

```sh
autodebug config vscode --demo --write ~/Projects/MyApp
```

### 3. Try it

1. Open that project folder in VS Code.
2. Command Palette (`Ctrl+Shift+P`, macOS `Cmd+Shift+P`) → **MCP: List Servers**
   → **autodebug** → **Start Server**.
3. Open Copilot Chat in **Agent** mode and ask:

   > Use the autodebug tools to investigate case AUTODEBUG-DEMO: show its
   > status, the stack, and the variables local_var and password.

You should see a synthetic stack, `local_var = 42` and `password =
***REDACTED***`. This is a built-in demo debugger: AutoDebug cannot yet drive
your real IDE debugger. **[docs/getting-started.md](docs/getting-started.md)**
covers Cursor, Claude Desktop and Claude Code, the full demo walkthrough and
troubleshooting.

### 4. Try the demo project

[examples/AutoDebugDemo](examples/AutoDebugDemo/README.md) is a small Python app
(with a C++ twin) that has one deliberate bug: moving a shape changes its area.
It comes with the AutoDebug repository, so there is nothing extra to download.

**Get it.** If you cloned AutoDebug before the demo existed, update first. Run
from the AutoDebug folder:

```sh
git pull
```

**See the bug.** Still in the AutoDebug folder:

**Windows (PowerShell):**

```powershell
cd examples\AutoDebugDemo
py report.py
py -m unittest -v
```

**macOS / Linux** (with `.venv` active from step 1):

```sh
cd examples/AutoDebugDemo
python3 report.py
python3 -m unittest -v
```

`report.py` ends with `3 of 3 shapes change area when moved.` and one test
fails with `AssertionError: 2.0 != 1.0`. That is expected; it is the bug.

**Debug it in VS Code.**

1. **File → Open Folder** → the `examples/AutoDebugDemo` folder inside AutoDebug
   (for example `D:\Projects\AutoDebug\examples\AutoDebugDemo`). Install the
   recommended Python extensions if VS Code offers them.
2. Open `geometry.py` and click left of line 15 to set a breakpoint.
3. **Run and Debug** → choose **Debug tests** → press `F5`.
4. At each stop, watch `i`, `len(points)` and `total` in **Variables**.

The [demo walkthrough](examples/AutoDebugDemo/README.md) has the answer, the
C++ build steps (CMake, Visual Studio, CLion) and how to connect AutoDebug to
this folder.

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
