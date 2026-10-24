# AutoDebug

Let your AI agent debug for real. AutoDebug gives the agent in **Cursor** or
**VS Code** the IDE's own debugger: it builds, sets breakpoints, runs, steps
through the code, reads variables, and writes a root-cause report into your
project. Nothing runs until you click **Approve**.

```text
You: "Help me debug this: moving a shape changes its area."

Agent: reads the code → start_session (you click Approve) → paused at geometry.py:15
       → step: total 0.0 → -1.0 → trace line 15: i = 0, 1, 2 → loop ends at i = 2
       → root cause: the closing edge is never added → autodebug-reports/…-area-bug.md
```

## What makes it different

- **Investigates, then reports.** One call builds, launches and stops at the
  first breakpoint. Each step tells the agent which variables changed. `trace`
  collects values every time a line runs. `write_report` writes the problem, the
  root cause, the fix and a timeline of everything the debugger showed.
- **You stay in control.** Every debug session needs your click on **Approve**
  in a dialog that shows the build command, the program, the breakpoints and the
  limits. Step and time limits apply. The agent cannot evaluate code or change
  variables, and secret-looking values are hidden from it.
- **Local and locked.** The extension listens on 127.0.0.1 only, behind a
  random token. No accounts, no cloud service, no dependencies.
- **Your existing setup.** It uses the launch configurations and tasks in your
  `.vscode` folder and works with any language your IDE can debug.

## Set up (once)

You need **Python 3.11+**, **Git**, and Cursor or VS Code with the debugger
extension for your language (for Python: **Python** and **Python Debugger**).

**Windows (PowerShell):**

```powershell
git clone https://github.com/TEEJORAM/AutoDebug.git
cd AutoDebug
py -m pip install -e .
py -m autodebug setup cursor
```

**macOS / Linux:**

```sh
git clone https://github.com/TEEJORAM/AutoDebug.git
cd AutoDebug
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m autodebug setup cursor
```

Use `setup vscode` for VS Code. `setup` installs the AutoDebug extension and
adds the `autodebug` MCP server to the IDE for all your projects. It then says
what to do next:

1. In the IDE: Command Palette → **Developer: Reload Window**. The status bar shows **AutoDebug**.
2. Cursor: **Cursor Settings → MCP** → turn on **autodebug**.
   VS Code: Command Palette → **MCP: List Servers** → **autodebug** → **Start Server**.

`autodebug doctor` checks all of this. To update later: `git pull`, then run
`setup` again.

## Use it

Open your project in the IDE and ask the agent (Agent mode), for example:

> Help me debug AutoDebugDemo: moving a shape changes its area. Use the
> autodebug tools to find the root cause and write a report.

Click **Approve** when the IDE asks. Try it on the sample project first:
[examples/AutoDebugDemo](examples/AutoDebugDemo/README.md).

## Agent tools

| Tool | What it does |
|---|---|
| `list_targets` | Launch configurations and build tasks in the open project |
| `start_session` | Approval, optional build, breakpoints, launch; waits for the first stop |
| `wait` · `pause` · `stop_session` | Follow, interrupt or end the session |
| `step` | Over, into or out, 1–20 times, with the variables that changed |
| `continue` | Run to the next stop and return it |
| `inspect` · `stack` | Variables of a frame; the call stack |
| `breakpoints` | Add or remove breakpoints during the session |
| `trace` | Collect variables every time a line runs |
| `write_report` | Root-cause report in `autodebug-reports/` with an automatic timeline |

How it works, the protocol and the limits: [docs/design.md](docs/design.md).

## Develop

```sh
PYTHONPATH=src python -m unittest discover -s tests
```

The extension tests need Node.js; the real-debugger test also needs
`pip install debugpy`. See [CLAUDE.md](CLAUDE.md) for the rules.
