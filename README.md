# AutoDebug

AutoDebug lets an AI agent debug your program with the debugger of **VS Code**,
**Cursor** or **Visual Studio 2022/2026**: it builds, sets breakpoints, runs,
steps, reads variables, and writes a root-cause report into your project.
Nothing runs until you click **Approve** in the IDE.

Agents: Cursor's agent, Claude Code, GitHub Copilot (VS Code and Visual
Studio), and any other agent that supports MCP or has a terminal.

**Documentation:** [teejoram.github.io/AutoDebug](https://teejoram.github.io/AutoDebug/)

## Where to get it

| Store | What | Status |
|---|---|---|
| [PyPI](https://pypi.org/project/autodebug/) | `autodebug`: the Python program and `autodebug setup` | **Available** |
| [Open VSX](https://open-vsx.org/extension/SwagatTeejoram/autodebug) | The extension `SwagatTeejoram.autodebug`; Cursor installs and updates from here | **Available** |
| VS Code Marketplace | The same extension for VS Code (until then, `autodebug setup` installs it) | Planned |
| Visual Studio Marketplace | The Visual Studio extension (until then, `autodebug setup` installs it from the GitHub release) | Planned |

## Install

You need Python 3.11 or newer. If you use Visual Studio, close it first.

Windows (PowerShell):

```powershell
py -m pip install --upgrade autodebug
py -m autodebug setup
```

macOS:

```sh
brew install pipx
pipx ensurepath
pipx install autodebug
autodebug setup
```

Linux:

```sh
sudo apt install pipx
pipx ensurepath
pipx install autodebug
autodebug setup
```

On Windows, `py` is the Python launcher, so nothing has to be added to your
PATH: write `py -m autodebug` wherever these docs say `autodebug`. On macOS and
Linux, open a new terminal after `pipx ensurepath`.
`autodebug setup` finds VS Code, Cursor, Visual Studio and Claude Code, connects
each one, and prints the few steps left for you (below). `autodebug doctor`
checks everything. To update: `py -m pip install --upgrade autodebug` (Windows) or
`pipx upgrade autodebug`, then run setup again.

## Connect and debug

**Before you start**, install the debugger for your language in the IDE:

| IDE | C++ | Python |
|---|---|---|
| VS Code | **C/C++** or **CodeLLDB** | **Python** and **Python Debugger** |
| Cursor | **CodeLLDB** (Microsoft's C/C++ debugger does not run in Cursor) | **Python** and **Python Debugger** |
| Visual Studio 2022 / 2026 | **Desktop development with C++** workload | not supported yet |

**After `autodebug setup`:**

| IDE | Steps |
|---|---|
| VS Code | Command Palette → **Developer: Reload Window**. In the Copilot chat (Agent mode) make sure **autodebug** is ticked in the tools; allow it if VS Code asks to trust the server. |
| Cursor | Command Palette → **Developer: Reload Window** in every window. Nothing to turn on: **Cursor Settings → Customize → MCPs** shows **extension-autodebug** with a green dot. Start a new chat. |
| Visual Studio | Open the solution; **View → Output → AutoDebug** says it is listening. Set the startup project and the **Debug** configuration. For Copilot in Visual Studio only: chat → **Tools** → tick **autodebug**. |
| Claude Code | Nothing. Start a new session. |

**Debug:** open the project and ask the agent, naming the IDE when more than one
is open, for example:

> Use the autodebug tools with the Visual Studio window (ide: visualstudio) and
> launch configuration "geometry (Debug|x64)". Build first, stop at
> geometry.cpp line 16, trace total, and write a report.

The IDE shows the **Approve** dialog with the goal, the build, the program, the
breakpoints and the limits. Read it and click **Approve** within 2 minutes. The
report is written to `autodebug-reports/` in the project. A chat message is
never an approval, and the agent cannot evaluate expressions or change
variables.

Try it on [examples/AutoDebugDemo](https://github.com/TEEJORAM/AutoDebug/blob/main/examples/AutoDebugDemo/README.md)
first. Step-by-step guides per IDE: [the documentation](https://teejoram.github.io/AutoDebug/).

**No tools in the chat?** Some apps drop MCP tools without an error. The agent
can run the same tools in its terminal, in the same session:
`autodebug run list_targets ide=visualstudio` (`autodebug run help` lists them).
`autodebug setup <project folder>` writes that into the project's `AGENTS.md`.

AutoDebug listens on 127.0.0.1 only, with a token, and collects no data. It is
released under the [MIT License](https://github.com/TEEJORAM/AutoDebug/blob/main/LICENSE).
How it works: [docs/design.md](https://github.com/TEEJORAM/AutoDebug/blob/main/docs/design.md).

## Large C++ programs

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
small JavaScript relay (`src/autodebug/extension/relay.js`) for VS Code and
Cursor, and a C# relay (`src/autodebug/visualstudio`) for Visual Studio. The
relays show the Approve dialog and pass debugger requests and events through.

To work on AutoDebug itself, clone the repository and install it editable:
`py -m pip install -e .` (Windows) or `python3 -m pip install -e .`.

Most tests run with Python alone. The relay tests need Node.js. The
real-debugger tests also need `pip install debugpy` (Python) and gdb 14 or later
with g++ (C++, Linux and macOS). See [CLAUDE.md](https://github.com/TEEJORAM/AutoDebug/blob/main/CLAUDE.md) for the rules.
