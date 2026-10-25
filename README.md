# AutoDebug

Let your AI agent debug for real. AutoDebug gives the agent in **Cursor** or
**VS Code** the IDE's own debugger: it builds, sets breakpoints, runs, steps
through the code, reads variables, and writes a root-cause report into your
project. Nothing runs until you click **Approve**.

It is built for large C++ applications, where the core and the user interface
are mostly C++: long builds, big binaries, many threads, deep call stacks, and
code spread across shared libraries. Python works too, including Python
embedded in a C++ application.

**Documentation:** [teejoram.github.io/AutoDebug](https://teejoram.github.io/AutoDebug/)

```text
You: "Help me debug this: moving a shape changes its area."

Agent: reads the code → start_session (you click Approve) → builds, paused at cpp/geometry.cpp:16
       → inspect points[3] → trace line 16: i = 0, 1, 2 → loop ends before the last edge
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
  `.vscode` folder: CodeLLDB, the C/C++ debugger, gdb, debugpy, or any other
  debugger your IDE runs.

## Set up (once)

You need **Python 3.11+** (AutoDebug's server runs on it), **Git**, and Cursor
or VS Code with a debugger extension:

- **C++ in Cursor:** **CodeLLDB**. Microsoft's C/C++ debugger does not run in Cursor.
- **C++ in VS Code:** **C/C++** (Visual Studio debugger or gdb) or **CodeLLDB**.
- **Python:** **Python** and **Python Debugger**.

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

`autodebug doctor` checks all of this, including the background AutoDebug
service that keeps the debug session (it starts by itself and stops when idle). To update later: `git pull`, then run
`setup` again.

### Visual Studio 2022 or 2026

Close Visual Studio, then:

```powershell
py -m autodebug setup visualstudio
```

This installs the AutoDebug extension in Visual Studio and adds the server to
`%USERPROFILE%\.mcp.json` for Visual Studio's own agent mode (Copilot). Start
Visual Studio, open your solution and set the startup project; View → Output →
**AutoDebug** shows it is listening. Any agent can then debug it: Copilot in
agent mode, or Cursor or Claude Code (`setup cursor` as above) with Visual
Studio open. The startup project's debug settings become the launch
configuration the agent picks, and **Approve** appears inside Visual Studio.
When another IDE is open too, name Visual Studio in the prompt ("use the Visual
Studio window", `ide: visualstudio`). For a CMake build such as Blender's, paths
are relative to the source folder, not the build folder.

## Use it

Open your project in the IDE and ask the agent (Agent mode), for example:

> The app crashes when I delete the last item in a list. Use the autodebug
> tools: build the Debug configuration, stop where the item is removed, find
> the root cause and write a report.

Click **Approve** when the IDE asks.

**When the agent cannot see the autodebug tools.** Some apps drop MCP tools from
a chat now and then (Cursor does this without an error). The agent can then use
the same tools, in the same session, from its terminal. Tell it once per project:

```powershell
py -m autodebug agents C:\path\to\your\project
```

This writes an AutoDebug section into the project's `AGENTS.md` (read by Cursor,
Copilot and Codex; for Claude Code add the line `@AGENTS.md` to `CLAUDE.md`) with
the exact command for your computer, for example:

```powershell
py -m autodebug run list_targets ide=visualstudio
py -m autodebug run help
```

Try it on the sample project first:
[examples/AutoDebugDemo](examples/AutoDebugDemo/README.md) has the same bug in
C++ (**Debug C++ (CodeLLDB)**) and Python (**Debug tests**).

## Agent tools

| Tool | What it does |
|---|---|
| `list_targets` | Launch configurations and build tasks in the open project |
| `start_session` | Approval, optional build, breakpoints, launch or attach; waits for the first stop |
| `wait` · `pause` · `stop_session` | Follow, interrupt or end the session. `wait` can `ask_developer` to reproduce a GUI step |
| `step` | Over, into or out, 1–20 times, with the variables that changed |
| `continue` | Run to the next stop and return it |
| `inspect` · `stack` · `threads` | Variables (including nested paths), the call stack, and threads |
| `breakpoints` · `exceptions` | Source and function breakpoints; exception filters |
| `trace` | Collect variables every time a line runs |
| `write_report` | Root-cause report in `autodebug-reports/` with an automatic timeline |

How it works, the protocol and the limits: [docs/design.md](docs/design.md).

## Large C++ applications

**Build with symbols.** Debug the `Debug` or `RelWithDebInfo` build; optimised
builds without debug info show wrong lines and missing variables. Let the
build run first through the launch configuration's `preLaunchTask` or the
agent's `build_task`. A long compile gets `build_minutes` (default 30, up to
600), separate from the debugging time limit.

**Launch configurations.** For example, in `.vscode/launch.json`:

```json
{
  "name": "Debug app (CodeLLDB)",
  "type": "lldb",
  "request": "launch",
  "program": "${workspaceFolder}/build/bin/app",
  "cwd": "${workspaceFolder}",
  "preLaunchTask": "build",
  "windows": { "program": "${workspaceFolder}/build/bin/Debug/app.exe" }
},
{
  "name": "Attach to app (CodeLLDB)",
  "type": "lldb",
  "request": "attach",
  "pid": "${command:pickMyProcess}"
}
```

The Approve dialog shows the whole configuration, the build commands with
everything they depend on, and the environment. Configurations that prompt for
input or debug another computer are refused.

**Attach to a running application.** Start the app yourself, get to the state
just before the bug, and have the agent attach with `process_id`. When the
session ends the debugger detaches and the app keeps running.

**What helps in a big codebase:**

- **Slow starts.** Loading symbols for a large binary can take minutes; the
  agent keeps calling `wait`.
- **Shared libraries and plugins.** Breakpoints in them bind when the library
  loads; until then they show as not bound yet, with the debugger's reason.
- **Code outside the workspace.** Pass `source_folders` for third-party
  libraries or an SDK that live outside the project folder.
- **Threads.** `threads` lists them and selects one for `stack`, `inspect` and
  `step`.
- **Deep stacks.** `stack` pages through up to 200 frames at a time.
- **Objects and containers.** `inspect` with `depth` 1–3 opens structs, pointers
  and containers. Names can be paths: `scene->objects[2].transform`.
- **Exceptions.** `exceptions` lists the debugger's exception filters (CodeLLDB
  offers C++ throw and catch) and turns them on. A stop on an exception reports
  which one.
- **GUI reproduction.** `wait` with `ask_developer` shows you a note such as
  "Click Delete on the last item". You do it, and the program stops at the
  breakpoint.
- **Embedded Python.** If the application embeds Python, start debugpy inside
  it and attach with a debugpy configuration (the sample has
  **Attach to Python (port 5678)**).
- **Function breakpoints.** Break on `Document::removeItem` without knowing the file.

Values the agent reads are sent to the AI model, like any other tool result.
Debug only programs and data you are allowed to share with it.

## Develop

```sh
PYTHONPATH=src python -m unittest discover -s tests
```

All of AutoDebug's logic is Python (`src/autodebug`). The IDE extension is a
small JavaScript relay (`src/autodebug/extension/relay.js`), because VS Code and
Cursor run extensions only in JavaScript; it shows the Approve dialog and passes
debugger requests and events through.

Most tests run with Python alone. The relay tests need Node.js. The
real-debugger tests also need `pip install debugpy` (Python) and gdb 14 or later
with g++ (C++, Linux and macOS). See [CLAUDE.md](CLAUDE.md) for the rules.
