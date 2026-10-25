# AutoDebug design

AutoDebug lets an AI agent investigate a bug with the IDE's own debugger: build,
set breakpoints, run, step, read variables, and write a root-cause report. It
supports **VS Code and Cursor**, and any language they can debug.

## Parts

```text
AI agent (Cursor, VS Code Copilot, Claude, ...)
   │  MCP over stdio
   ▼
autodebug  (Python)  ── tools, launch checks, session state from debugger events,
   │                     stack and variables, limits, redaction, timeline, report
   │  JSON lines over 127.0.0.1, token
   ▼
AutoDebug extension  (in VS Code / Cursor)  ── a thin relay: Approve dialog, tasks,
   │                                           breakpoints, start/stop, DAP passthrough
   │  Debug Adapter Protocol
   ▼
the language debugger (CodeLLDB, C/C++, gdb, debugpy, ...) ── your program
```

- **`autodebug` (Python 3.11+, no dependencies).** The MCP server the agent's
  IDE starts. It holds all of AutoDebug's logic: the agent tools, the checks on
  launch configurations and tasks, the session state (built from the debugger's
  own events), stack, threads and variables, limits, redaction and the report.
- **AutoDebug extension (JavaScript, no dependencies).** Runs in each IDE window.
  IDE extensions can only be written in JavaScript, so it is kept to what needs
  the IDE: the Approve dialog, running the approved build task and launch
  configuration, placing breakpoints, relaying a short list of Debug Adapter
  Protocol requests, and reporting the session's events. It enforces the approval,
  the step and time limits, the approved folders and the request list on its own,
  so a fault in the server cannot widen what the developer approved.

## Agent tools

| Tool | Does |
|---|---|
| `list_targets` | IDE windows, their folders, launch configurations (program and module separately) and build tasks |
| `start_session` | Ask the developer to approve, then build, set breakpoints, launch or attach; waits for the first stop |
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
| `write_report` | Write the Markdown report: problem, root cause, solution, verification, timeline |

There is no tool that evaluates expressions or changes variables.
`start_session`, `step`, `continue`, `trace` and `pause` move the program; the
agent must not call them in parallel with `stack` or `inspect`.

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
without an answer refuse. One approval covers one debug session. Attach
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
`BAD_REQUEST`, `IDE_ERROR`.

The server lists windows whose extension speaks another protocol too. If the
only matching window is one of those, the tools fail with `OLD_EXTENSION`,
naming both versions and the fix: `autodebug setup`, then **Developer: Reload
Window** (restarting only the extension host keeps the old extension loaded), or
updating the server when the extension is newer. `autodebug doctor` reports the
same. The extension rewrites its connection file within 10 seconds if something
deletes it while the window is open.

## Report

`write_report` writes `<workspace>/autodebug-reports/<date>-<title>.md`, never
overwriting: summary table, problem, how it was run, debug timeline (every
session since the previous report, with each stop, step, inspection and trace,
numbered), root cause with confidence
(`confirmed` needs how it was confirmed), solution, verification (marked as
reported by the agent), open questions.

## Setup

`autodebug setup cursor|vscode [FOLDER]` builds the extension package, installs
it with the IDE's own `--install-extension`, and writes the MCP entry: Cursor's
global `~/.cursor/mcp.json`, VS Code's user `mcp.json`, or `FOLDER`'s project
file when a folder is given. `autodebug doctor` checks Python, the config files
and running extension windows.
