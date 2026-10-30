# Autodebug design

Autodebug lets an AI agent investigate a bug with the IDE's own debugger: build,
set breakpoints, run, step, read variables, and write a root-cause report. It
supports **VS Code and Cursor**, and any language they can debug.

## Parts

```text
AI agent (Cursor, VS Code Copilot, Claude, Codex, ...)
   │  MCP tools (autodebug serve)          or   terminal: autodebug run <tool> key=value
   └──────────────────┬───────────────────────────────┘
                      │  JSON lines over 127.0.0.1, token (hub.json)
                      ▼
Autodebug service  (Python, one per user) ── tools, launch checks, session state from
   │                     debugger events, stack and variables, limits, redaction, timeline, report
   │  JSON lines over 127.0.0.1, token
   ▼
Autodebug extension  (VS Code / Cursor: JavaScript; Visual Studio: C#)
   │   a thin relay: Approve dialog, builds, breakpoints, start/stop, debugger passthrough
   │  Debug Adapter Protocol (VS Code, Cursor); Visual Studio's debugger automation
   ▼
the debugger (CodeLLDB, C/C++, gdb, debugpy, JavaScript, Visual Studio's native and .NET debuggers, ...) ── your program
```

- **`autodebug` (Python 3.11+, no dependencies).** It holds all of Autodebug's
  logic: the agent tools, the checks on launch configurations and tasks, the
  session state (built from the debugger's own events), stack, threads and
  variables, limits, redaction and the report. The logic runs in the **service**
  (below); the MCP server the agent's IDE starts and the `autodebug run` command
  are two thin ways to call it. The main modules: `tools.py` (the agent tools),
  `session.py` (one debug session: state from events, moving the program),
  `values.py` (reading variables), `launch.py` (checks on launch configurations,
  arguments and tasks), `checks.py` (conditions, hit counts and log messages),
  `mcp_server.py`, `hub.py` (the service) and `report.py`. The relays check
  the same rules again on their own, and `tests/test_consistency.py` checks the
  three copies are written alike.
- **Autodebug extension (JavaScript, no dependencies).** Runs in each IDE window.
  IDE extensions can only be written in JavaScript, so it is kept to what needs
  the IDE: the Approve dialog, running the approved build task and launch
  configuration, placing breakpoints, relaying a short list of Debug Adapter
  Protocol requests, and reporting the session's events. It enforces the approval,
  any step and time limits the agent asked for, the approved folders and the request list on its own,
  so a fault in the server cannot widen what the developer approved.
- **Autodebug for Visual Studio (C#, no runtime dependencies).** The same relay
  protocol for Visual Studio 2022 and 2026 (see "Visual Studio" below), for C,
  C++ and .NET programs. Its
  shared core (`visualstudio/Core`: connection, Approve gate, limits, events) has
  no Visual Studio references, so a test harness runs it with plain .NET; only
  the `Extension/VsBackend*.cs` files (one partial class) talk to Visual Studio.

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
  `run` command for this computer; do not search Autodebug's source for the tools;
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

## Opening the IDE

Agents used to start Visual Studio themselves when no window was open, and opened
several copies while the first was still loading the solution. `open_ide` does it
once. Visual Studio takes a `.sln`/`.slnx`, or a folder whose solution is found up
to three folders down (a CMake build folder); with none it names the `cmake`
command that generates one, with several it asks for the file. VS Code and Cursor
take the project folder. A window that already has the folder (for a CMake
solution: its source folder, `CMAKE_HOME_DIRECTORY`) is reused. Otherwise the IDE
starts, detached, with `devenv.exe` (found with `vswhere`, newest 2022/2026) or the
`code`/`cursor` launcher, and Autodebug waits up to 55 seconds for its extension.
`opening.json` in the state folder records the start: for 3 minutes, another call
for the same IDE and path waits instead of starting a second copy. Opening the
IDE runs nothing of the program; debugging still needs Approve. `NO_WINDOW`
errors point to `open_ide`, and `list_targets` reports `program_exists` so an
agent that sees an unbuilt program passes `build_task` instead of building it.

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
| `open_ide` | Open a solution or project folder in the IDE when no window has it, and wait until Autodebug answers there (see "Opening the IDE") |
| `start_session` | Ask the developer to approve, then build, set breakpoints, launch or attach; waits for the first stop. `ide` and `workspace_folder` pick the window when several are open. `args` replaces the program's arguments for this run; `ticket` names the issue it is for; `test` runs one test (see "One test") |
| `reproduce` | Before debugging a reported bug: one approved run with no breakpoints, to its end; returns the exit code and last output lines, and tells the agent to compare them with the ticket's `symptom` |
| `wait` | Wait for the session to change state. `ask_developer` shows an information message; it is not an approval |
| `step` | Step over, into or out (1–20 times). `wait_ms` waits for a slow step (default 15 s, max 60 s). `target` steps into one chosen call on the line (`stepInTargets`); `single_thread` keeps the other threads paused; `instruction` steps one machine instruction; kind `back` steps backwards (recording debuggers) |
| `continue` | Run to the next stop and return it; with `until`, run past other breakpoints to that line. `single_thread`; `reverse` runs backwards to the previous stop (recording debuggers) |
| `pause` | Stop a running program where it is |
| `inspect` | Frame variables (the frame's own scopes: Locals, Arguments; not globals or registers). `depth` 0–3 expands children. Names may be paths (`mesh.verts[2].co`, `items[5000]`). `scope` reads one scope by name, slow ones too (Globals, Registers); the result lists the frame's scopes. `start` and `count` (at most 200) page through one array or list; `hex` asks for hexadecimal values. A large list is read by index: the debugger's paging (`indexedVariables`, `start`, `count`), else debugpy's `more` child and its `[a:b]` ranges, reading only the range that holds the element |
| `stack` | Call stack, top frame first. `start_frame` pages; up to 200 frames |
| `threads` | List threads. `select` switches the paused thread |
| `exceptions` | List exception filters and enable them by id; an item `{id, condition}` passes a condition to a filter that takes one (`filterOptions`). `types` stops only for these exception types (`exceptionOptions`; debugpy gets the path `Python Exceptions` → types), `mode` `always` or `unhandled`. What a call leaves out stays: `types` alone keeps the enabled filters (at first the debugger's defaults) |
| `breakpoints` | Add or remove source or function breakpoints during the session. A source breakpoint can have `condition`, `hit_condition`, `log_message` and `column` (see "Breakpoint options"). `check {file, line, end_line}` lists the lines where a breakpoint binds (`breakpointLocations`) |
| `watch` | While paused: data breakpoints (watchpoints). `add [{name, access}]` (`write`, `read`, `readWrite`), `remove [names]`; at most 8. The name is a variable or path in the frame; `dataBreakpointInfo` gets its id from the container that holds it, so nothing is evaluated. A stop on one has the reason `data breakpoint: <what changed>` |
| `modules` | Loaded modules: name, path, version, symbol status, optimized (`modules` request, else the module events). `filter`; `sources` adds `loadedSources`, including code without a file |
| `source` | While paused: the code of a frame that has no file (`source` request with its `sourceReference`), 120 lines around the frame's line, redacted |
| `disassemble` | While paused: instructions around a frame's `instructionPointerReference` (`before`, `after`); the current one is marked. A debugger that cannot go backwards from an address (gdb 15) gets the current instruction and those after it |
| `memory` | While paused: at most 256 bytes of a variable (its `memoryReference`) or at a frame's instruction, as hex rows. A variable with a secret name, or bytes whose text looks like a key or token, come back as `***REDACTED***` |
| `trace` | Run to a line repeatedly; each row has the caller and each variable as `before → after` the line runs (one step per hit, counted in the step limit). Stops early at another breakpoint |
| `capture` | At the stop that shows the bug: a screenshot of the IDE (Visual Studio) with the agent's note for the report; returns the named variables to the agent; at most 5 per report |
| `stop_session` | End the debug session |
| `write_report` | Write the Markdown report (see "Report") |

There is no tool that evaluates expressions or changes variables. Conditions
(on breakpoints and on exception filters) may only compare values: variables,
paths, numbers, strings and true/false/null, joined by `==`, `!=`, `<`, `<=`,
`>`, `>=`, `is` (`not`), `not`/`!`, `and`/`&&`, `or`/`||`. No calls,
assignments, arithmetic or parentheses: the server, the VS Code relay and the
Visual Studio relay apply the same grammar, also to conditions added after
Approve. A log message may name only variables and paths (`{total}`,
`{mesh.verts[2].co}`), and a hit condition only a count. So nothing the agent
writes runs code the developer did not see.

**Breakpoint options.** `hit_condition` is a count with an optional comparison
(`5`, `>=5`, `%10`, ...); what it means is the debugger's: debugpy and Visual
Studio stop at that hit, gdb's own adapter skips that many hits, and Visual
Studio has no "fewer than". `log_message` makes a log point: the debugger prints
it (variables in braces) and does not stop; the lines reach the agent as program
output. `column` places the breakpoint at a column (a lambda, minified code).
The Approve dialog shows each option (`geometry.py:15 at hit >=2`, `logs "..."
without stopping`). An extension without `breakpoint_options` in its `info`
would drop them, so such breakpoints are refused there with `OLD_EXTENSION`
before anything is shown.

**What the debugger cannot do** is said plainly: a tool that needs a capability
the debugger does not report (`supportsDataBreakpoints`, `supportsStepBack`,
`supportsDisassembleRequest`, ...) fails with `NOT_SUPPORTED`, naming the
debugger type. Requests the extension does not know fail with `OLD_EXTENSION`
and the fix.

**Activity.** Debugger events about threads, processes, modules, sources
without a file and long debugger work (`progressStart`), and child sessions
starting and ending, are kept as short lines; each tool result shows the new
ones once as `activity`. The first 30 module loads are listed, then only
changes.

**One test.** `test` on `start_session` or `reproduce` sets the program
arguments that run one test with the launch configuration's runner: pytest
(`module: pytest` or a `pytest` program) and unittest get the id itself, go
(`mode: test`) gets `-test.run ^Name$`, jest `--runInBand -t name`, vitest
`run -t name`. Other configurations are refused with the hint to pass `args`.
`test` and `args` are not combined. The Approve dialog says that one test runs.
`start_session`, `reproduce`, `step`, `continue`, `trace` and `pause` move the program; the
agent must not call them in parallel with `stack` or `inspect`.

## Working from a ticket

A developer can hand the agent a GitHub issue, a Jira ticket or a pasted bug
report. Autodebug does not fetch tickets: the agent reads them with its own tools
(a GitHub or Jira connector, `gh`), so Autodebug needs no network access, logins
or libraries for it. Autodebug gives every agent the same path, in the MCP
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
"session"` for Autodebug's, `"editor"` for the developer's (left in place).
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
`cwd`, `env`, `envFile`, the breakpoints, `source_folders`, the limits (none unless asked for), the
goal, and the launch configuration as JSON exactly as it will be used (without
`name`). A configuration longer than 4000 characters is refused. `${input:…}`
and `${command:…}` are refused, except an attach `processId` or CodeLLDB `pid`
filled by `process_id`. A remote `host`, `pipeTransport`, or non-local address
is refused: Autodebug debugs only programs on this computer. The platform block
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

- One session per IDE window. **No step or time limit by default**: a session
  runs until the root cause is found, the program ends, or the agent or the
  developer stops it (the IDE's Stop button), so the agent is never cut off at an
  arbitrary point. The agent may still ask for `max_steps` (at most 100,000;
  enforced by both parts) or `max_minutes` (at most 1,440; enforced by the
  extension), and the dialog then shows them. One `step` call moves at most 20
  steps and one `trace` at most 50 hits; the agent calls again for more.
- Values whose name or content looks secret (password, token, key, credential,
  cookie; key-shaped strings) are replaced with `***REDACTED***` before the
  agent or the report sees them, including children of a secret-named parent.
  Values are capped at 2,000 characters.
- Breakpoint files must be inside the workspace folder or a `source_folders` path.
- `memory` reads at most 256 bytes at a time and hides secret-looking ones;
  `source` and `disassemble` text is redacted like values. At most 8 watched
  values at a time.

## Extension protocol

Connection file `<state>/bridges/<window>.json` (`%LOCALAPPDATA%\autodebug`,
`~/Library/Application Support/autodebug`, `~/.local/state/autodebug`), mode
0600 where the OS supports it:
`{"protocol": 4, "port", "token", "window", "ide", "folders", "version"}`.
Newer relays add `features` to `info`: `breakpoint_options` (hit counts, log
points, columns), `inspection` (the requests below) and, in VS Code and Cursor,
`child_sessions`.

Autodebug connects to `127.0.0.1:<port>` and sends `{"hello": token}`; a wrong
token closes the connection. Then one JSON object per line:
`{"id", "op", "args"}` → `{"id", "ok", "result" | "error": {"code", "message"}}`.

| Op | Args | Result |
|---|---|---|
| `info` | – | window, ide, versions, folders, `platform`, `debugger_types` (null if unknown), `features` |
| `workspace` | `folder` | `folder`, `launch` (configurations as written), `tasks` (definitions as written) |
| `approve` | `folder`, `launch` (the prepared configuration), `task`, `notes`, `label`, `breakpoints` [{file (absolute), line, condition, column, hit_condition, log_message}], `functions`, `source_folders`, `max_steps`, `max_minutes`, `build_minutes`, `screenshots` (Visual Studio) | `session`, `breakpoint_ids`, `function_ids`; the dialog opens |
| `events` | `since`, `wait_ms` (≤ 60000) | `events` (up to 500, oldest first), `next`, `latest`, `dropped` (long poll) |
| `dap` | `command`, `arguments`, `timeout_ms`, `session` | `body` of the debugger's response |
| `breakpoints` | `add`, `add_functions`, `remove` (ids) | `breakpoint_ids`, `function_ids` |
| `editor_breakpoints` | – | the developer's own enabled breakpoints: {file, line} or {function} |
| `notify` | `text` (≤ 300) | – (a non-modal note to the developer; never an approval) |
| `screenshot` | `file` (absolute `.png` under `<folder>/autodebug-reports/screenshots`) | `file`, `width`, `height`, `variables_window`. Visual Studio only, and only when the session was approved with `screenshots` (`NOT_APPROVED` otherwise) |
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
`stepIn`, `stepOut`, `continue`, `pause`, `exceptionInfo`,
`setExceptionBreakpoints`, `dataBreakpointInfo`, `setDataBreakpoints`,
`modules`, `loadedSources`, `source`, `stepInTargets`, `disassemble`,
`readMemory`, `breakpointLocations`, `stepBack` and `reverseContinue`, only while
the approved session runs. Each reads state or moves the program; none
evaluates an expression or changes a value (`evaluate`, `setVariable`,
`setExpression`, `writeMemory`, `goto`, `restartFrame` stay refused). Steps,
`stepBack` included, count against the approved limit (`LIMIT`). The relays
check a breakpoint's `hit_condition` and `log_message` the same way as the
server.

**Child sessions** (VS Code, Cursor). A program can run in debug sessions that
the approved one starts: the JavaScript debugger (Node.js, browsers) runs the
program in a child session, debugpy can follow subprocesses. The relay follows
every session whose `parentSession` chain leads to the approved one: their
messages are relayed with a `session` id, `child_started` and `child_ended`
{session, name} events say when they come and go, and `dap` goes to the session
that last stopped unless the server names one with `session`. A child that ends
does not end the session; the approved session ending does, and stopping it
stops its children.

Events: `{seq, kind, ...}` with `kind`:
`approval` {approved, reason}, `build` {task, status (`running`, `succeeded`,
`failed`, `timeout`, `unavailable`), exit_code, minutes}, `starting`, `started`,
`not_started`, `error` {message}, `ended` {reason, exit_code}, `child_started`,
`child_ended`, and `dap` {direction, message, session}: every event from the debugger, its responses to
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
output_note, activity [{seq, text}], watches [{name, access, verified, message}]}` where `status` is `awaiting_approval`, `denied`, `building`,
`build_failed`, `starting`, `running`, `paused` or `ended`. A breakpoint that is
not bound yet says it may bind when its module or library loads, with the
debugger's own message. Frames without source are `(no source)`; a stop in one
is at `(no file) <name>`, and `source` or `disassemble` shows its code.

Error codes: `NO_WINDOW`, `OLD_EXTENSION`, `AMBIGUOUS_WINDOW`, `NOT_FOUND`,
`NOT_APPROVED`, `BUSY`, `NOT_PAUSED`, `LIMIT`, `OUTSIDE_WORKSPACE`,
`BAD_REQUEST`, `IDE_ERROR`, `NOT_SUPPORTED` (the debugger lacks what the tool
needs), `NOT_BUILT` (the launch configuration's program is
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
  project, with `"type": "visualstudio"`, `engine`, `project` and
  `configuration`. C and C++ projects: their active configuration's debug
  settings (`LocalDebuggerCommand`, `LocalDebuggerCommandArguments`,
  `LocalDebuggerWorkingDirectory`, `LocalDebuggerEnvironment`, falling back to
  `TargetPath`), `"engine": "native"`. .NET projects (`.csproj`, `.vbproj`,
  `.fsproj`): the program is the build's `.exe`, else `dotnet` with the `.dll`;
  arguments, working folder and environment come from the
  `Properties/launchSettings.json` profile with `"commandName": "Project"`;
  `"engine"` is `managed` (.NET), `framework` (.NET Framework), or `mixed` /
  `mixed_framework` when the profile has `"nativeDebugging": true`. Plus
  **Attach to a process (native)** and **Attach to a process (.NET)**, which
  need `process_id`. Build "tasks" are `Build <project> (<configuration>)` and
  `Build solution (<configuration>)`.
- **Approve** is a modal Visual Studio dialog (Deny is the default button). After
  Approve the relay builds through Visual Studio's build, places the breakpoints
  and starts exactly the configuration shown (`IVsDebugger4.LaunchDebugTargets4`
  with the configuration's debug engines: native, .NET (CoreCLR), .NET Framework,
  or native and .NET together; attach uses the same call with the process ID).
- **Requests** map to Visual Studio's debugger automation: threads of every
  debugged process (named `<process>: <thread>` when there are several), stack
  frames (`StackFrame2`), each frame's locals and their members (paged with
  `start` and `count`; containers report `indexedVariables`; `hex` switches
  `HexDisplayMode` for the read and back), step over/into/out, go and break. No
  expression is ever evaluated for the agent, and values are never set. Frame
  and value references are valid until the program runs again.
- **The debug engine's view** of the stop (the program and thread of the last
  stopping event) gives what the automation does not: each frame's instruction
  address, a **Registers** scope (`guidFilterRegisters`, marked slow),
  disassembly (`IDebugDisassemblyStream2`), memory of a local or at an
  instruction (`IDebugMemoryBytes2`; locals carry their `memoryReference`), and
  one-instruction steps (`IDebugProgram2.Step` with `STEP_INSTRUCTION`).
- **Breakpoint options**: hit counts map to Visual Studio's =, >= and "multiple
  of"; a log point is a tracepoint (`Breakpoint2.Message`, `BreakWhenHit` off),
  whose lines the relay reads from the Output window's Debug pane at each stop
  and at the end (module loads, thread exits and lines the engine already
  reported are left out); a column is the breakpoint's column.
- **Data breakpoints**: `dataBreakpointInfo` takes the variable's plain path
  (`total`, `mesh.verts[2]`) from the locals and members listed, and
  `setDataBreakpoints` adds Visual Studio data breakpoints on it (write access,
  native code). One counts as bound when Visual Studio lists a location for it,
  as for other breakpoints. They are removed when the session ends.
- **Exception filters**: `cpp` (C++ Exceptions), `win32` (Win32 Exceptions) and
  `clr` (.NET) turn on "break when thrown" for the group's exceptions; `types`
  does it for named exceptions, adding a name that is not listed yet to the C++
  or .NET group. Visual Studio always stops on unhandled exceptions, so mode
  `unhandled` changes nothing. Every setting changed is put back when the
  session ends.
- **Single thread**: the other threads are frozen for the step or continue and
  thawed at the next stop or the end.
- **Console output**: a console program's own window is read for its output by
  a small Windows PowerShell script that ships with the extension
  (`ConsoleReader.ps1`, run with `-File`, readable, not an encoded command). It
  attaches to the program's console and prints each finished line until the
  program exits. Visual Studio itself never
  attaches to a console, so closing the program's window cannot close Visual
  Studio. Where PowerShell cannot run that helper, there is no console output,
  as before.
- **Modules, threads and processes**: the debug engine's module load and unload,
  thread create and destroy, and process create events become `module`, `thread`
  and `process` events; `modules` lists the loaded modules with symbol status.
- **Not available in Visual Studio** (`NOT_SUPPORTED`): stepping into a chosen
  call, stepping back, valid breakpoint lines, code without a file (use
  `disassemble`), read watchpoints, and globals (Visual Studio has no globals
  list; read them through a local or a member).
- **Events**: break mode becomes `stopped` (breakpoint, step, pause or
  exception), run mode `continued`, design mode `exited` and `terminated`; the
  debug engine's breakpoint-bound and binding-error events update which
  breakpoints are bound, and its output-string events become `output`
  (`OutputDebugString`; the console window is read separately, see above).
- **Debug windows.** At every stop of an Autodebug session the relay brings the
  Call Stack and a variables window forward and puts the code document back in
  front, so Visual Studio's debug layout (code on top, Autos/Locals bottom left,
  Call Stack bottom right) shows values from the first stop on. The variables
  window is Locals when the frame has locals or arguments, so it is never empty,
  else Autos. The developer's own window arrangement is not moved; after
  **Window → Reset Window Layout** it is the layout above.
- **Outdated extension.** Visual Studio's extension carries Autodebug's version.
  When it is older than the server (setup skips it while Visual Studio is open),
  it still speaks the protocol but lacks newer features, so `list_targets` and
  `start_session` return `extension_note`, `capture` explains a missing screenshot
  with it, and `doctor` flags it, each naming the fix: close Visual Studio, run
  setup, open the solution again.
- **Exit code.** The exit code comes from the debug engine's program-destroy event;
  when that arrives after design mode (or not at all), the relay reads it from the
  launched process, whose handle it opened at launch (`dwProcessId` from
  `LaunchDebugTargets4`).
- **Screenshots.** `start_session` asks for them by default in Visual Studio
  (`screenshots: false` turns them off; VS Code and Cursor cannot take them), and
  the Approve dialog says so, including that a screenshot shows whatever the window
  shows, values that look secret too. At each `capture`, the relay brings the debug
  windows forward, waits for them to paint, and saves Visual Studio's main window
  with `PrintWindow` (`PW_RENDERFULLCONTENT`, so it works when the window is
  covered) as a PNG under `autodebug-reports/screenshots`. Only that window is
  saved, never the screen, and only into that folder. The report shows it under the
  stop's note.
- **Not yet:** `launch.vs.json` ("Open Folder") projects.

## Report

`write_report` writes `<workspace>/autodebug-reports/<date>-<title>.md`, never
overwriting. It has exactly these sections, in this order, because developers asked
for a report they can read rather than a dump:

1. **Ticket**: a link when it is a URL, else the key; "none" without one.
2. **Problem.**
3. **Steps to reproduce**: "Reproducible: yes." and numbered steps
   (`steps_to_reproduce` is required then), plus the exit code of the run without
   breakpoints; or "Not reproducible." / "Not tried." with "Steps: NA".
4. **Debug sessions**: one line naming the IDE, the launch configuration and the
   build, the agent's `debug_findings`, then each captured stop: its one-sentence
   note and the screenshot of the IDE at that stop (or why there is none).
   Variables and call stacks are never written out as text: the screenshot shows
   them as the IDE does.
5. **Root cause**: "What went wrong" and "Why", then the confidence (`confirmed`
   needs `how_confirmed` and a reproduced bug).
6. **Solution**, the existing code it follows (`pattern`), then "Verified: ..." only
   when the agent applied the fix and saw the bug gone (`fix_verified` with
   `verification`), else "Not verified yet".
7. **AI usage**: the `model` the agent reports (required), `token_usage` only when
   the agent's app shows it (otherwise "not reported", never a guess), and
   Autodebug's own share: its tool calls since the previous report and the size of
   their arguments and results, at about 4 characters per token.

There is no timeline in the report; the service keeps it for the agent's tools.
Long dashes in the agent's text become commas, and the instructions ask for short,
plain sentences.

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
checkout folder when run from a source checkout. `setup` rewrites the Autodebug
section of every `AGENTS.md` it wrote before (recorded in
`agents-folders.json` in the state folder) and of the open IDE windows' folders,
so agents never run an older Autodebug; `doctor FOLDER` flags a stale one.

**Updates.** `setup` first asks PyPI for the newest version (one HTTPS request,
3 seconds at most, ignored when offline). When it is newer, setup installs
exactly that version into the Python it runs on (`pip install --upgrade
--force-reinstall --no-deps --no-cache-dir autodebug==X`, or `pipx install
--force` for a pipx copy), which replaces every file of the old copy and gets
past pip's cached package list, then runs `setup` again in a new process with
the new code (`AUTODEBUG_UPDATED=1` stops a second update). A failed update is
reported with the command to run, and setup goes on with the current version.
`--no-update` skips it; a source checkout is never changed. `doctor` prints which
Autodebug runs, from where and with which Python, and says when PyPI has a newer
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
