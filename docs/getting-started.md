# Getting started

AutoDebug is a **command-line MCP server**. You don't run it as an app; your AI
client (VS Code Copilot, Cursor, Claude Code or Claude Desktop) starts it in the
background and talks to it over stdin/stdout. A small VS Code extension, the
**AutoDebug Bridge**, lets it drive the debugger in your IDE window.

The same steps, with a Windows / macOS / Linux switch, are on
[GitHub Pages](https://teejoram.github.io/AutoDebug/) (`site/index.html` in
this repository). `autodebug guide` prints them for the OS you are using.

## What works today

```text
 AI client  ──MCP──▶  AutoDebug server  ──127.0.0.1──▶  AutoDebug Bridge  ──▶  IDE debugger  ──▶  your program
                       (plan, limits,                    (in VS Code or        (debugpy, ...)
                        redaction, report)                Cursor; Approve
                                                          dialog)
```

| Part | Status |
|---|---|
| AI client → AutoDebug | Works with any MCP client. |
| AutoDebug → **VS Code / Cursor** debugger | Works through the AutoDebug Bridge, after you click **Approve**. Verified with automated tests and the real Python debugger; the first run in a real IDE window is still to be recorded. |
| CLion, Visual Studio, Xcode | Not supported yet. |
| Practice debugger | `--demo`: a synthetic debugger with a fixed case, no IDE needed. |

## 1. Install

Requirements: **Python 3.11 or newer**, **Git**, and **VS Code** (or Cursor)
with the **Python extension** for Python programs. AutoDebug has no
dependencies to download.

Windows (PowerShell):

```powershell
git clone https://github.com/TEEJORAM/AutoDebug.git
cd AutoDebug
py -m pip install -e .
```

macOS / Linux:

```sh
git clone https://github.com/TEEJORAM/AutoDebug.git
cd AutoDebug
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Windows this guide uses `py -m autodebug`, which works even when Python's
`Scripts` folder is not on your PATH. On macOS/Linux, `autodebug` works while
the `.venv` is active. To update later: `git pull`, then the install line again.

## 2. Check your machine

Windows: `py -m autodebug doctor` · macOS / Linux: `autodebug doctor`

```text
AutoDebug doctor (autodebug 0.1.0)

  ✔ Python            3.14.8
  · Platform          Windows 11
  ✔ Evidence storage  supported
  ✔ Evidence folder   C:\Users\you\AppData\Local\autodebug (created on first run)
  ✔ Demo debugger     synthetic, ready for `serve --demo`
  · IDE bridge        no VS Code or Cursor window is running it; install with `py -m autodebug bridge install vscode`, then open your project
  · Other IDEs        clion, visual_studio target this OS; mock-only, no native debugger client yet
  · Real debuggers    VS Code and Cursor through the AutoDebug Bridge; each case needs your click on Approve

Ready. Guide: https://teejoram.github.io/AutoDebug/
```

Fix anything marked `✘` before continuing. `doctor` never creates files.

## 3. Install the AutoDebug Bridge

From the AutoDebug folder:

Windows (PowerShell):

```powershell
py -m autodebug bridge install vscode
```

macOS / Linux:

```sh
autodebug bridge install vscode
```

Use `cursor` instead of `vscode` for Cursor. This builds the extension package
and installs it with the IDE's own `code --install-extension` (or `cursor
--install-extension`). Then run **Developer: Reload Window** in the IDE; the
status bar shows **AutoDebug**.

If the IDE command is not on your PATH, AutoDebug prints the path of the
`.vsix` file instead: in the IDE open **Extensions** → **···** → **Install from
VSIX…** and choose it. `py -m autodebug bridge status` lists the windows that
are running the bridge.

## 4. Connect your AI client

Run these from the AutoDebug folder, with the folder you will debug.
`config ... --write` adds AutoDebug to the client's configuration, keeps any
other servers and saves it as UTF-8. Without `--write`, `config` only prints
the entry.

**VS Code (Copilot):** writes `.vscode/mcp.json` in the project.

```powershell
py -m autodebug config vscode --write D:\Projects\AutoDebug\examples\AutoDebugDemo
```

```sh
autodebug config vscode --write ~/Projects/AutoDebug/examples/AutoDebugDemo
```

Then in VS Code, with that folder open: Command Palette → **MCP: List Servers**
→ `autodebug` → **Start Server** (or **Restart Server**).

**Cursor:** `config cursor --write FOLDER` writes `.cursor/mcp.json`; enable
`autodebug` under MCP in Cursor Settings.

**Claude Code:** `config claude-code` prints a `claude mcp add ...` command; run
it in your project folder. **Claude Desktop:** `config claude-desktop --write`,
then restart Claude Desktop. Both drive the bridge in the VS Code or Cursor
window that has the project open.

## 5. Debug a program

Open the project in VS Code (the bridge needs the folder open there) and ask the
agent, for example for the sample project:

> Help to debug AutoDebugDemo using the autodebug tools. Bug: moving a shape
> changes its area (the "Debug tests" launch configuration shows it). Choose
> breakpoints in the code that computes the area, request my approval, then
> step through it to find the cause. Finish the case with the problem, root
> cause, solution and evidence, and tell me where the report is.

For your own project, name its launch configuration from `.vscode/launch.json`
(and a build task from `.vscode/tasks.json`, if it needs one).

What happens:

| Step | Tool | You see |
|---|---|---|
| Plan | `autodebug_create_case`, `autodebug_stage_plan` | The agent explains its breakpoints |
| Approval | `autodebug_request_approval`, `autodebug_wait_for_approval` | **A dialog in VS Code** listing the build task, launch configuration, breakpoints and limits. Click **Approve** or **Deny**. |
| Build | `autodebug_run_build`, `autodebug_wait_for_build` | The task runs in the IDE terminal (only if the plan has one) |
| Run | `autodebug_arm_case` | The debug session starts in VS Code with the breakpoints set |
| Inspect | `autodebug_wait_for_stop`, `autodebug_get_stack`, `autodebug_list_variables`, `autodebug_get_variables` | The program stops at a breakpoint; secret-looking values show as `***REDACTED***` |
| Step | `autodebug_step` (`step_over`, `step_in`, `step_out`), `autodebug_continue` | Execution moves in the editor |
| Finish | `autodebug_complete_case` | The debug session ends; the report path is given |

Nothing runs before you click **Approve**. If the launch configuration, build
task or a breakpoint file changes after you approve, the case stops with
`PLAN_CHANGED`. The agent can't evaluate expressions or change variables.

## 6. Find the report

The report is written into the project:

```text
<project>/autodebug-reports/<case-id>.md
```

It has the problem, how it was reproduced, a timeline of every stop and step
with evidence IDs, the root cause and its confidence, the solution, and how it
was verified (marked as reported by the agent). AutoDebug also keeps a private
copy with the raw evidence, outside the project:

```text
<evidence base>\run-<time>-<id>\<case-id>\   events.jsonl, case.json, report.md
```

The evidence base is `%LOCALAPPDATA%\autodebug` on Windows,
`~/Library/Application Support/autodebug` on macOS and
`~/.local/state/autodebug` on Linux. Change it with `--evidence-dir DIR` or
`AUTODEBUG_EVIDENCE_DIR` (the bridge then needs the same folder in its
`autodebug.bridgesFolder` setting, as `<folder>/bridges`).

## Practice debugger (`--demo`)

`config vscode --demo --write FOLDER` connects a built-in synthetic debugger
with a fixed, pre-approved case `AUTODEBUG-DEMO`, no extension needed. Ask:

> Use the autodebug tools to investigate case AUTODEBUG-DEMO: show its status,
> the stack, and the variables local_var and password, step over once, then
> complete the case as inconclusive citing the evidence IDs.

The demo approval lasts 30 minutes from server start.

## Troubleshooting

| Problem | Fix |
|---|---|
| `BACKEND_UNAVAILABLE`: no AutoDebug Bridge is running for … | Open exactly that folder in VS Code with the extension installed; check for **AutoDebug** in the status bar (`bridge status` lists windows). |
| `SESSION_AMBIGUOUS`: two windows have the folder open | Close one of them. |
| No dialog appears | It may be behind another window; the agent's wait times out as `pending`. **AutoDebug Bridge: Show Log** shows each request. |
| `TIMEOUT` while starting | Starting the debugger took longer than `policy.max_operation_seconds`; ask the agent to use 20–30 seconds. |
| `PLAN_CHANGED` | A file the plan names changed after approval; ask the agent for a new case. |
| `BUILD_FAILED` | The build task failed; its output is in the IDE terminal. |
| "is still active in this window" | A previous case did not finish; ask the agent to cancel it, or reload the window. |
| The client doesn't list AutoDebug | Re-run the `config ... --write` command from the AutoDebug folder, then restart the server. |
| Where are the server's messages? | VS Code: **MCP: List Servers** → `autodebug` → **Show Output**. |
| `serve` waits and prints nothing | Normal: it waits for an MCP client on stdin. Press Ctrl+C. |

## Command reference

| Command | Purpose |
|---|---|
| `autodebug serve [--demo] [--evidence-dir DIR] [--log-level LEVEL]` | Run the MCP stdio server (clients run this for you) |
| `autodebug doctor [--evidence-dir DIR] [--json]` | Check the machine and running bridges; exit 0 when ready |
| `autodebug bridge install {vscode,cursor} [--vsix-only]` | Build and install the AutoDebug Bridge extension |
| `autodebug bridge status` | List IDE windows running the bridge |
| `autodebug config {vscode,claude-code,claude-desktop,cursor} [--demo] [--write [PROJECT_FOLDER]] [--evidence-dir DIR] [--name NAME]` | Print client configuration, or write it into the client's config file |
| `autodebug guide` | Print setup steps for this OS and the GitHub Pages URL |
| `autodebug --version` / `autodebug --help` | Version and help |

`python -m autodebug ...` works the same without installing the command.
