# AutoDebug

AutoDebug lets an AI agent debug your program with the debugger of **VS Code**,
**Cursor** or **Visual Studio 2022/2026**: it builds, sets breakpoints, runs,
steps, reads variables, and writes a root-cause report into your project.
Nothing runs until you click **Approve** in the IDE.

Agents: Cursor's agent, Claude Code, GitHub Copilot (VS Code and Visual
Studio), and any other agent that supports MCP or has a terminal.

**Documentation:** [teejoram.github.io/AutoDebug](https://teejoram.github.io/AutoDebug/)

## What you need

- **Python 3.11 or newer** and **Git**.
- One IDE, with the debugger for your language:

| IDE | C++ | Python |
|---|---|---|
| VS Code | **C/C++** or **CodeLLDB** extension | **Python** and **Python Debugger** extensions |
| Cursor | **CodeLLDB** extension (Microsoft's C/C++ debugger does not run in Cursor) | **Python** and **Python Debugger** extensions |
| Visual Studio 2022 or 2026 | the **Desktop development with C++** workload | not supported yet |

## Connect (about 2 minutes)

**1. Install AutoDebug.** If you use Visual Studio, close it first.

Windows (PowerShell):

```powershell
py -m pip install git+https://github.com/TEEJORAM/AutoDebug.git
py -m autodebug setup
```

macOS / Linux:

```sh
python3 -m venv ~/.autodebug
~/.autodebug/bin/python -m pip install git+https://github.com/TEEJORAM/AutoDebug.git
~/.autodebug/bin/python -m autodebug setup
```

`setup` finds every IDE and agent on the computer and connects each one: it
installs the AutoDebug extension (VS Code, Cursor, Visual Studio) and adds the
`autodebug` MCP server (VS Code, Visual Studio, Claude Code). In Cursor the
extension registers the server itself.

**2. Do the one step `setup` prints for your IDE:**

| IDE | Step |
|---|---|
| VS Code | Command Palette → **Developer: Reload Window**. If VS Code asks whether to trust or start the **autodebug** server, allow it. |
| Cursor | Command Palette → **Developer: Reload Window**, in every Cursor window. The extension registers the server with Cursor itself: **Cursor Settings → Customize → MCPs** shows **extension-autodebug**, already switched on. |
| Visual Studio | Start it and open your solution. Set the startup project and the **Debug** configuration. For Copilot in Visual Studio only: in the chat, **Tools** → tick **autodebug**. |
| Claude Code | Nothing. Start a new session. |

**3. Check:** `py -m autodebug doctor` (macOS / Linux: `~/.autodebug/bin/python -m autodebug doctor`).
It lists the connected IDEs, the open IDE windows and what to fix.

**Optional, per project:** `py -m autodebug setup C:\path\to\project` also
writes an AutoDebug section into the project's `AGENTS.md`. Agents read it and
use the terminal when their app hides the MCP tools (see below).

## Which agent debugs in which IDE

The agent and the IDE are separate. Any connected agent can debug in any IDE
window that runs the AutoDebug extension:

- **Cursor's agent** debugs in Cursor, VS Code or Visual Studio.
- **Claude Code** debugs in VS Code, Cursor or Visual Studio.
- **Copilot** debugs in VS Code (agent mode), or in Visual Studio (agent mode).

When windows of more than one IDE are open, name the IDE in the prompt, for
example "use the Visual Studio window".

## Debug

Open the project in the IDE and ask the agent, for example:

> The app crashes when I delete the last item in a list. Use the autodebug
> tools: build the Debug configuration, stop where the item is removed, find
> the root cause and write a report.

1. The IDE shows the **Approve** dialog with the goal, the build, the program,
   the breakpoints and the limits. Click **Approve** within 2 minutes.
2. The agent builds, stops at the breakpoints, steps and traces.
3. The report is written to `autodebug-reports/` in the project folder.

Try it first on [examples/AutoDebugDemo](https://github.com/TEEJORAM/AutoDebug/blob/main/examples/AutoDebugDemo/README.md):
the same bug in C++ and Python.

## When the agent cannot see the autodebug tools

Some apps drop MCP tools from a chat without an error. The agent can then run
the same tools in its terminal, in the same debug session:

```powershell
py -m autodebug run list_targets ide=visualstudio
py -m autodebug run help
```

`autodebug setup <project folder>` writes the exact command for your computer
into the project's `AGENTS.md`, so the agent finds it by itself.

## Troubleshooting

| What you see | What to do |
|---|---|
| The agent has no autodebug tools | Cursor: reload the window and start a new chat; **Settings → Customize → MCPs** should show **extension-autodebug** with a green dot. `autodebug doctor` flags an old `mcp.json` entry that gets in the way. Visual Studio Copilot: **Tools** → tick **autodebug**. Any agent: it can use `autodebug run` (above). |
| "No VS Code, Cursor or Visual Studio window is running the extension" | Open the project in the IDE. VS Code / Cursor: **Developer: Reload Window**; the status bar shows **AutoDebug**. Visual Studio: View → Output → **AutoDebug** says it is listening. |
| No Approve dialog | Switch to the IDE window: the dialog opens there (in Visual Studio it stays on top of other windows). The agent reports "no answer within 2 minutes" when nobody answered. |
| `NOT_BUILT` | The program has not been built. The agent retries with the build task it names. |
| Visual Studio is open during setup | Close every Visual Studio window, then run `setup` again. |
| No debugger for type "…" | Install that debugger extension in the IDE (table above) and reload the window. |

## Update

```powershell
py -m pip install --force-reinstall git+https://github.com/TEEJORAM/AutoDebug.git
py -m autodebug setup
```

## Commands

| Command | Does |
|---|---|
| `autodebug setup` | Connect every IDE and agent found. `setup cursor`, `vscode`, `visualstudio` or `claude` connects one; add a project folder for project-only entries and `AGENTS.md` |
| `autodebug doctor [folder]` | Check the setup, the open IDE windows and the AutoDebug service |
| `autodebug run <tool> key=value …` | Call a debugging tool from a terminal; `run help` lists them |
| `autodebug serve` | The MCP server; the IDE or agent starts it |

On Windows write `py -m autodebug`; on macOS / Linux `~/.autodebug/bin/python -m autodebug`.

## Agent tools

| Tool | What it does |
|---|---|
| `list_targets` | IDE windows, their launch configurations and build tasks |
| `start_session` | Approval, build, breakpoints, launch or attach; waits for the first stop |
| `wait` · `pause` · `stop_session` | Follow, interrupt or end the session. `wait` can `ask_developer` to reproduce a GUI step |
| `step` | Over, into or out, 1–20 times, with the variables that changed |
| `continue` | Run to the next stop, or past other breakpoints to a line |
| `inspect` · `stack` · `threads` | Variables (including nested paths), the call stack, and threads |
| `breakpoints` · `exceptions` | Source and function breakpoints; exception filters |
| `trace` | Collect variables every time a line runs |
| `write_report` | Root-cause report in `autodebug-reports/` with a timeline of the session |

The agent cannot evaluate expressions or change variables, and secret-looking
values are hidden from it. AutoDebug listens on 127.0.0.1 only, with a token.
How it works: [docs/design.md](https://github.com/TEEJORAM/AutoDebug/blob/main/docs/design.md).

AutoDebug is released under the [MIT License](https://github.com/TEEJORAM/AutoDebug/blob/main/LICENSE).

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
