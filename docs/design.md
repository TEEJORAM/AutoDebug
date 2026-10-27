# AutoDebug design

AutoDebug lets an AI agent investigate a bug with the IDE's own debugger: build,
set breakpoints, run, step, read variables, and write a root-cause report. It
supports **VS Code and Cursor**, and any language they can debug.

## Parts

```text
AI agent (Cursor, VS Code Copilot, Claude, Codex, ...)
   │  MCP tools (autodebug serve)          or   terminal: autodebug run <tool> key=value
   └──────────────────┬───────────────────────────────┘
                      │  JSON lines over 127.0.0.1, token (hub.json)
                      ▼
AutoDebug service  (Python, one per user) ── tools, launch checks, session state from
   │                     debugger events, stack and variables, limits, redaction, timeline, report
   │  JSON lines over 127.0.0.1, token
   ▼
AutoDebug extension  (VS Code / Cursor: JavaScript; Visual Studio: C#)
   │   a thin relay: Approve dialog, builds, breakpoints, start/stop, debugger passthrough
   │  Debug Adapter Protocol (VS Code, Cursor); Visual Studio's debugger automation
   ▼
the debugger (CodeLLDB, C/C++, gdb, debugpy, Visual Studio's native debugger, ...) ── your program
```

- **`autodebug` (Python 3.11+, no dependencies).** It holds all of AutoDebug's
  logic: the agent tools, the checks on launch configurations and tasks, the
  session state (built from the debugger's own events), stack, threads and
  variables, limits, redaction and the report. The logic runs in the **service**
  (below); the MCP server the agent's IDE starts and the `autodebug run` command
  are two thin ways to call it.
- **AutoDebug extension (JavaScript, no dependencies).** Runs in each IDE window.
  IDE extensions can only be written in JavaScript, so it is kept to what needs
  the IDE: the Approve dialog, running the approved build task and launch
  configuration, placing breakpoints, relaying a short list of Debug Adapter
  Protocol requests, and reporting the session's events. It enforces the approval,
  the step and time limits, the approved folders and the request list on its own,
  so a fault in the server cannot widen what the developer approved.
- **AutoDebug for Visual Studio (C#, no runtime dependencies).** The same relay
  protocol for Visual Studio 2022 and 2026 (see "Visual Studio" below). Its
  shared core (`visualstudio/Core`: connection, Approve gate, limits, events) has
  no Visual Studio references, so a test harness runs it with plain .NET; only
  `Extension/VsBackend.cs` talks to Visual Studio.

## The service

AI apps do not reliably keep an MCP server's tools in the chat: Cursor, for
example, can drop a connected server from the agent's tool list without an error.
So the session does not live in the MCP server process.

- **One service per user** (`autodebug hub`, `hub.py`) owns the `Debugger`: the
  session, its timeline and the report. It listens on 127.0.0.1 on a free port and
  writes `hub.json` (port, token, process id, version) to the state folder, readable
  only by the user. Every request carries the token. Tool calls run one at a time.
- **Started on demand.** The first client that finds no service starts one in the
  background, detached from the caller (on Windows it leaves the IDE's job object
  when allowed), and waits up to 15 s for `hub.json`. A service of another version
  (or of other code, after an update with the same version number: `ping` reports a
  fingerprint of the Python files) is replaced only when no session is open. It exits after 30 minutes without
  calls while no session is open.
- **Clients.** `autodebug serve` (MCP over stdio) forwards each tool call to the
  service; if the service cannot be started it runs the tools in its own process,
  as before (`serve --direct` forces that). `autodebug run <tool> key=value ...`
  calls the same tools from any terminal and prints the JSON result (exit code 0,
  1 for a tool error, 2 for a usage error). Values are read by the tool's schema,
  so no JSON quoting is needed: `breakpoints=geometry.cpp:16,b.cpp:4`,
  `variables=total,i`, `until=geometry.cpp:20`, `after=false`; a value starting
  with `[` or `{` is JSON. `run help` lists the tools and the workflow.
  `python <checkout>/src/autodebug ...` runs from a checkout without installing.
- **Agent instructions.** `autodebug agents FOLDER` (also done by `setup` with a
  folder) writes a marked section into `FOLDER/AGENTS.md`, read by Cursor, Copilot,
  Codex and others: use the MCP tools when present, otherwise the exact
  `run` command for this computer; do not search AutoDebug's source for the tools;
  the developer approves in the IDE. The MCP `instructions` name the same command.

An agent can therefore start a session over MCP and finish it in the terminal (or
the reverse), and the report keeps the whole timeline. Approval is unchanged: the
service is just another client of the extension, and only the IDE dialog approves.

## Choosing the window

`start_session` debugs in one IDE window. With `ide` and `workspace_folder` it
takes the window they name. When the developer named neither and several
windows match (Cursor, where they chat, and Visual Studio, where they debug, both
with the project open), it takes: (1) the IDE set with `autodebug setup
--debug-in <ide>` (`preferences.json` in the state folder), else (2) the only
window whose project has a launch configuration of that name (Visual Studio's
`geometry (Debug|x64)` exists only there), else it fails with `AMBIGUOUS_WINDOW`,
naming the windows and both ways out. `list_targets` reports the preferred IDE
(`debug_in`) when windows of several IDEs are open.

## Which IDE and which build

The agent must not guess where it debugs or what it debugs. `list_targets` gives
every launch configuration a `start_with` (the `ide`, the name and, when several
windows are open, the folder: pass them as they are) and a `build`:
`{type, platform, optimized, debug_symbols, source, note}`. The type is read, in
order, from Visual Studio's active configuration (`Debug|x64`), the program's
folder (`build/RelWithDebInfo/`, Cargo's `target/debug`, .NET's `bin/Release`),
then `CMAKE_BUILD_TYPE` in the `CMakeCache.txt` of a single-config CMake build;
`source` says which. Optimization and symbols follow the default flags of CMake,
MSBuild, Cargo and .NET: Debug is not optimized and has symbols; RelWithDebInfo
is optimized with symbols (the `note` warns that values can be optimized away);
Release and MinSizeRel are optimized and usually have no symbols (the `note`
says breakpoints may not bind and to ask for Debug). Interpreted languages have
no build type. An unknown or custom type is reported as such, never guessed.

`start_session` and `reproduce` return `debugging` once: the IDE, folder, launch
configuration and build, so the agent can tell the developer, plus `build_note`
for an optimized build. The Approve dialog shows the build line, and the report's
summary table has a Build row.

## Agent tools

Arguments are checked against each tool's schema before anything runs (MCP, the
service and `autodebug run` share one check). A rejected call names the argument,
what is allowed and what to do instead, for example `start_session: wait_seconds
must be between 0 and 55; got 120; call wait to keep waiting`, so an agent fixes
the call instead of looking for other causes. One call waits at most 55 seconds;
an agent waits longer for the Approve click by calling `wait` again.

| Tool | Does |
|---|---|
| `list_targets` | IDE windows (with `ide`: cursor, vscode or visualstudio), their folders, launch configurations (program and module separately, each with its `build` type and `start_with`: the exact `ide`, name and folder to pass) and build tasks. `ide` limits it to one IDE |
| `start_session` | Ask the developer to approve, then build, set breakpoints, launch or attach; waits for the first stop. `ide` and `workspace_folder` pick the window when several are open. `args` replaces the program's arguments for this run; `ticket` names the issue it is for |
| `reproduce` | Before debugging a reported bug: one approved run with no breakpoints, to its end; returns the exit code and last output lines, and tells the agent to compare them with the ticket's `symptom` |
| `wait` | Wait for the session to change state. `ask_developer` shows an information message; it is not an approval |
| `step` | Step over, into or out (1–20 times). `wait_ms` waits for a slow step (default 15 s, max 60 s) |
| `continue` | Run to the next stop and return it; with `until`, run past other breakpoints to that line |
| `pause` | Stop a running program where it is |
| `inspect` | Frame variables. `depth` 0–3 expands children. Names may be paths (`mesh.verts[2].co`) |
| `stack` | Call stack, top frame first. `start_frame` pages; up to 200 frames |
| `threads` | List threads. `select` switches the paused thread |
| `exceptions` | List exception filters and enable them by id |
| `breakpoints` | Add or remove source or function breakpoints during the session |
| `trace` | Run to a line repeatedly; each row has the caller and each variable as `before → after` the line runs (one step per hit, counted in the step limit). Stops early at another breakpoint |
| `stop_session` | End the debug session |
| `write_report` | Write the Markdown report: problem, reproduction (`ticket`, `reproduction`, `reproduced`), root cause, solution, verification, timeline |

There is no tool that evaluates expressions or changes variables.
`start_session`, `reproduce`, `step`, `continue`, `trace` and `pause` move the program; the
agent must not call them in parallel with `stack` or `inspect`.

## Working from a ticket

A developer can hand the agent a GitHub issue, a Jira ticket or a pasted bug
report. AutoDebug does not fetch tickets: the agent reads them with its own tools
(a GitHub or Jira connector, `gh`), so AutoDebug needs no network access, logins
or libraries for it. AutoDebug gives every agent the same path, in the MCP
instructions, `run help`, the `AGENTS.md` section and the MCP prompt
`debug_ticket` (a slash command in Cursor and VS Code; argument `ticket`):

1. Read the ticket; write down expected and actual behaviour and the steps.
2. Write the smallest reproduction in the workspace (a script, an input file, a
   test) that a launch configuration runs.
3. `reproduce` it: one approved run without breakpoints. Debug only a bug that
   showed; otherwise refine the reproduction or ask the developer.
4. `start_session` with the same `args` and `ticket`, then debug from evidence.
5. `write_report` with `ticket`, `reproduction` and `reproduced` (`yes`, `no`,
   `not_tried`). `confirmed` is refused when the bug was not reproduced.

**Program arguments.** `args` (at most 32, each at most 1000 characters)
replaces the launch configuration's arguments for that run, so a new
reproduction needs no change to the developer's configuration. Launch
configurations only. Visual Studio takes one command line, so the arguments are
joined with Windows quoting. Refused before the dialog: line breaks and control
characters (multi-line input goes in a file), `${...}` variables, and values that
look like keys or tokens. The dialog names them as the agent's choice, besides
showing them in the configuration JSON.

**Ticket text is untrusted.** Anyone can write anything in an issue, including
"run this command". The workflow tells agents to treat it as data, never to run
commands, scripts or links from it, and to build their own reproduction. The
dialog shows the ticket and says that its text can come from anyone, so the
developer checks the program, arguments and breakpoints before approving. Only
the dialog approves, as always.

**Test data only.** Tickets, Jira's in particular, often contain customer data.
The workflow tells agents to use made-up values and never to copy names, emails,
account numbers, logs or attachments into a reproduction, its arguments or the
report, and never to point the debugger at production systems. Secret-shaped
arguments are refused, and the report is redacted as before.

Every state lists all breakpoints that can stop the program: `source:
"session"` for AutoDebug's, `"editor"` for the developer's (left in place).
When the program ends, the state carries the last lines it printed (redacted);
launch configurations that print to the terminal (`"console":
"integratedTerminal"`) cannot be captured.

## Approval

Before asking, the server checks that an installed extension provides the
launch configuration's debugger type; if not, `start_session` fails with
`NOT_FOUND` and names the extension to install. The server also prepares the
configuration and refuses the unsafe ones (below); the extension renders the
dialog from the exact objects it will run.

`start_session` opens a modal dialog in the IDE window. It shows what will run:
the build task and its `dependsOn` chain, `preLaunchTask`, `postDebugTask`,
`cwd`, `env`, `envFile`, the breakpoints, `source_folders`, the step limit, the
goal, and the launch configuration as JSON exactly as it will be used (without
`name`). A configuration longer than 4000 characters is refused. `${input:…}`
and `${command:…}` are refused, except an attach `processId` or CodeLLDB `pid`
filled by `process_id`. A remote `host`, `pipeTransport`, or non-local address
is refused: AutoDebug debugs only programs on this computer. The platform block
(`windows`, `osx`, `linux`) is applied before the dialog, then removed, so the
dialog and the debugger see the same object.

Only **Approve** starts anything; **Deny**, closing the dialog or two minutes
without an answer refuse. The `denied` status carries the reason, and the
server's `next` text tells the agent when nobody answered (reason `no answer
within 2 minutes`) rather than Deny, so it can say the dialog was probably
hidden. In Visual Studio the dialog stays above other windows, Visual Studio
is restored and brought forward when it opens (Windows may flash its taskbar
button instead), and the dialog is closed when the two minutes run out, so a
late click cannot look like an answer. VS Code and Cursor cannot close a modal
dialog from an extension; a click after the timeout is ignored. One approval covers one debug session. Attach
sessions detach when they end and the program keeps running. Launch sessions
stop the program. The session timer starts when debugging starts, not at
approval. A build that exceeds `build_minutes` (default 30, max 600) is
terminated.

## Limits and redaction

- One session per IDE window. Step limit per session (default 100, at most 1000),
  enforced by both parts. Sessions end after `max_minutes` (default 30, at most 480),
  enforced by the extension.
- Values whose name or content looks secret (password, token, key, credential,
  cookie; key-shaped strings) are replaced with `***REDACTED***` before the
  agent or the report sees them, including children of a secret-named parent.
  Values are capped at 2,000 characters.
- Breakpoint files must be inside the workspace folder or a `source_folders` path.

## Extension protocol

Connection file `<state>/bridges/<window>.json` (`%LOCALAPPDATA%\autodebug`,
`~/Library/Application Support/autodebug`, `~/.local/state/autodebug`), mode
0600 where the OS supports it:
`{"protocol": 4, "port", "token", "window", "ide", "folders", "version"}`.

AutoDebug connects to `127.0.0.1:<port>` and sends `{"hello": token}`; a wrong
token closes the connection. Then one JSON object per line:
`{"id", "op", "args"}` → `{"id", "ok", "result" | "error": {"code", "message"}}`.

| Op | Args | Result |
|---|---|---|
| `info` | – | window, ide, versions, folders, `platform`, `debugger_types` (null if unknown) |
| `workspace` | `folder` | `folder`, `launch` (configurations as written), `tasks` (definitions as written) |
| `approve` | `folder`, `launch` (the prepared configuration), `task`, `notes`, `label`, `breakpoints` [{file (absolute), line, condition}], `functions`, `source_folders`, `max_steps`, `max_minutes`, `build_minutes` | `session`, `breakpoint_ids`, `function_ids`; the dialog opens |
| `events` | `since`, `wait_ms` (≤ 60000) | `events` (up to 500, oldest first), `next`, `latest`, `dropped` (long poll) |
| `dap` | `command`, `arguments`, `timeout_ms` | `body` of the debugger's response |
| `breakpoints` | `add`, `add_functions`, `remove` (ids) | `breakpoint_ids`, `function_ids` |
| `editor_breakpoints` | – | the developer's own enabled breakpoints: {file, line} or {function} |
| `notify` | `text` (≤ 300) | – (a non-modal note to the developer; never an approval) |
| `stop` | `reason` | – (ends the session; attach sessions detach first) |

The server puts the agent's `args` into the prepared configuration and adds the
ticket and argument lines to `notes`, so neither relay needs to know about them.

`approve` checks that every breakpoint is inside the folder or `source_folders`
(`OUTSIDE_WORKSPACE`) and that the configuration fits the dialog (4000
characters). The dialog shows the server's `notes` (goal, attach target), then
what the extension itself will run: the build task and its `dependsOn` chain,
`preLaunchTask`, `postDebugTask`, the program and arguments, the breakpoints,
`source_folders`, the limits, what happens at the end, and the configuration as
JSON. Only after **Approve** does it build, place the breakpoints and call
`startDebugging` with that configuration.

`dap` accepts only `threads`, `stackTrace`, `scopes`, `variables`, `next`,
`stepIn`, `stepOut`, `continue`, `pause`, `exceptionInfo` and
`setExceptionBreakpoints`, only while the approved session runs. Steps count
against the approved limit (`LIMIT`).

Events: `{seq, kind, ...}` with `kind`:
`approval` {approved, reason}, `build` {task, status (`running`, `succeeded`,
`failed`, `timeout`, `unavailable`), exit_code, minutes}, `starting`, `started`,
`not_started`, `error` {message}, `ended` {reason, exit_code}, and `dap`
{direction, message}: every event from the debugger, its responses to
`initialize`, `setBreakpoints` and `setFunctionBreakpoints`, and the IDE's
`setBreakpoints` / `setFunctionBreakpoints` requests (so the server can tell
which breakpoints are bound). Output longer than 4000 characters is cut. The
extension keeps the last 5000 events; when it must drop some, it drops program
output first (`dropped_output` counts them), so a stop or the end is never lost.

The server turns these into the state the tools return:
`{version, status, reason, location {file, line}, exit_code, message,
thread {id, name}, exception {id, description} | null,
breakpoints [{file, line} or {function}, source, verified, message],
steps_used, max_steps, build {task, status, exit_code} | null, output [last lines],
output_note}` where `status` is `awaiting_approval`, `denied`, `building`,
`build_failed`, `starting`, `running`, `paused` or `ended`. A breakpoint that is
not bound yet says it may bind when its module or library loads, with the
debugger's own message. Frames without source are `(no source)`.

Error codes: `NO_WINDOW`, `OLD_EXTENSION`, `AMBIGUOUS_WINDOW`, `NOT_FOUND`,
`NOT_APPROVED`, `BUSY`, `NOT_PAUSED`, `LIMIT`, `OUTSIDE_WORKSPACE`,
`BAD_REQUEST`, `IDE_ERROR`, `NOT_BUILT` (the launch configuration's program is
not on disk and no build task or `preLaunchTask` will build it; checked before the
dialog, so the developer is not asked to approve a launch that cannot start).

The server lists windows whose extension speaks another protocol too. If the
only matching window is one of those, the tools fail with `OLD_EXTENSION`,
naming both versions and the fix: `autodebug setup`, then **Developer: Reload
Window** (restarting only the extension host keeps the old extension loaded), or
updating the server when the extension is newer. `autodebug doctor` reports the
same. The extension rewrites its connection file within 10 seconds if something
deletes it while the window is open.

## Visual Studio

The C# relay answers the same operations as the JavaScript one, so the server
treats Visual Studio like any other window (`ide: "visualstudio"`).

- **The workspace folder** is the solution's folder, except for a CMake build
  folder (a `CMakeCache.txt` beside the solution, as with Blender): then it is
  the source folder CMake recorded (`CMAKE_HOME_DIRECTORY`), so breakpoints and
  locations use source paths.

- **Launch configurations** come from the solution's startup projects: one per
  project, from its active configuration's debug settings (`LocalDebuggerCommand`,
  `LocalDebuggerCommandArguments`, `LocalDebuggerWorkingDirectory`,
  `LocalDebuggerEnvironment`, falling back to `TargetPath`), with `"type":
  "visualstudio"`, `"engine": "native"`, `project` and `configuration`. Plus
  **Attach to a process (native)**, which needs `process_id`. Build "tasks" are
  `Build <project> (<configuration>)` and `Build solution (<configuration>)`.
- **Approve** is a modal Visual Studio dialog (Deny is the default button). After
  Approve the relay builds through Visual Studio's build, places the breakpoints
  and starts exactly the configuration shown (`IVsDebugger4.LaunchDebugTargets4`
  with the native engine; attach uses the same call with the process ID).
- **Requests** map to Visual Studio's debugger automation: threads, stack frames
  (`StackFrame2`), each frame's locals and their members (no expression is ever
  evaluated, and values are never set), step over/into/out, go and break.
  Frame and value references are valid until the program runs again.
- **Events**: break mode becomes `stopped` (breakpoint, step, pause or
  exception), run mode `continued`, design mode `exited` and `terminated`; the
  debug engine's breakpoint-bound and binding-error events update which
  breakpoints are bound, and its output-string events become `output`
  (`OutputDebugString` only: a console program's own window is not captured).
- **Not yet:** exception filters (none are offered) and `launch.vs.json` ("Open
  Folder") projects.

## Report

`write_report` writes `<workspace>/autodebug-reports/<date>-<title>.md`, never
overwriting: summary table (with the build, the ticket and whether the bug was reproduced),
problem, reproduction (the agent's description and every `reproduce` run with its
arguments, exit code and telling output lines), how it was run, debug timeline (every
session since the previous report, with each stop, step, inspection and trace,
numbered), root cause with confidence
(`confirmed` needs how it was confirmed), solution, verification (marked as
reported by the agent), open questions.

## Setup

Install: `pipx install autodebug` from PyPI (the release workflow publishes a
`v<version>` tag there with trusted publishing; the extension goes to Open VSX as
`SwagatTeejoram.autodebug`; the VS Code and Visual Studio Marketplaces are planned).
`autodebug setup [FOLDER]`
with no IDE named detects VS Code and Cursor (their command-line launchers),
Visual Studio 2022/2026 (vswhere) and Claude Code (`claude` or its home files),
connects each one as below, and ends with the one manual step per IDE that no
file can do: reloading the VS Code / Cursor window, and ticking the tools for
Copilot in Visual Studio (which starts MCP tools switched off).

**The extension registers the server.** `setup` writes `server.json` in the
state folder (the command, arguments and environment that start `autodebug
serve`). On activation the extension registers it with the IDE: in Cursor with
`vscode.cursor.mcp.registerServer` (listed as `extension-autodebug`; tried in
Cursor 3: switched on, all the tools, unlike an `mcp.json` entry, which Cursor 3
starts switched off), in VS Code 1.101+ with
`vscode.lm.registerMcpServerDefinitionProvider` (`contributes.mcpServerDefinitionProviders`).
A window whose `mcp.json` files already name `autodebug` is left alone, so the
tools never appear twice. For Cursor, `setup` therefore writes no `mcp.json`
entry and removes the one older versions wrote; `doctor` flags one that is left.
VS Code still gets its `mcp.json` entry until the provider is tried there. A
FOLDER that is not an IDE name is the project folder. Claude Code gets the
entry in `~/.claude.json` (or `FOLDER/.mcp.json`) under `mcpServers`, keeping
its other settings.

**Commands on this computer.** Messages from `setup` and `doctor` name the
command that works in the developer's terminal: `autodebug` when it is on PATH,
`py -m autodebug` on Windows when the `py` launcher starts the same Python (pip
puts `autodebug.exe` in a folder that is usually not on PATH), else this Python
with `-m autodebug`. The command written for agents (`AGENTS.md`, the MCP
instructions) is `autodebug` on PATH or `<this python> -m autodebug`, and the
checkout folder when run from a source checkout. `setup` rewrites the AutoDebug
section of every `AGENTS.md` it wrote before (recorded in
`agents-folders.json` in the state folder) and of the open IDE windows' folders,
so agents never run an older AutoDebug; `doctor FOLDER` flags a stale one.

**Updates.** `setup` first asks PyPI for the newest version (one HTTPS request,
3 seconds at most, ignored when offline). When it is newer, setup installs
exactly that version into the Python it runs on (`pip install --upgrade
--force-reinstall --no-deps --no-cache-dir autodebug==X`, or `pipx install
--force` for a pipx copy), which replaces every file of the old copy and gets
past pip's cached package list, then runs `setup` again in a new process with
the new code (`AUTODEBUG_UPDATED=1` stops a second update). A failed update is
reported with the command to run, and setup goes on with the current version.
`--no-update` skips it; a source checkout is never changed. `doctor` prints which
AutoDebug runs, from where and with which Python, and says when PyPI has a newer
one.

`autodebug setup cursor|vscode [FOLDER]` builds the extension package, installs
it with the IDE's own `--install-extension`, and writes the MCP entry: Cursor's
global `~/.cursor/mcp.json`, VS Code's user `mcp.json`, or `FOLDER`'s project
file when a folder is given.

`autodebug setup visualstudio [FOLDER] [--vsix FILE]` finds Visual Studio with
`vswhere`, installs the extension package with Visual Studio's `VSIXInstaller`
(downloaded from the `visualstudio-v<version>` GitHub release that CI builds, or
`--vsix`), and writes `%USERPROFILE%\.mcp.json` (or `FOLDER\.mcp.json`) for
Visual Studio's own agent mode. It removes an installed copy before installing,
because `VSIXInstaller` refuses a package whose version is already installed.
With `FOLDER`, setup also writes the agent instructions (`AGENTS.md`).
`autodebug doctor [FOLDER]` checks Python, the config files, running extension
windows, the service, the terminal command and `FOLDER/AGENTS.md`.
