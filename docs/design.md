# AutoDebug design

AutoDebug lets an AI agent investigate a bug with the IDE's own debugger: build,
set breakpoints, run, step, read variables, and write a root-cause report. It
supports **VS Code and Cursor**, and any language they can debug.

## Parts

```text
AI agent (Cursor, VS Code Copilot, Claude, ...)
   │  MCP over stdio
   ▼
autodebug  (Python)  ── tools, step budget, secret redaction, session timeline, report
   │  JSON lines over 127.0.0.1, token
   ▼
AutoDebug extension  (in VS Code / Cursor)  ── approval dialog, tasks, debug API
   │  Debug Adapter Protocol
   ▼
the language debugger (debugpy, C/C++, Node, ...) ── your program
```

- **`autodebug` (Python 3.11+, no dependencies).** The MCP server the agent's
  IDE starts. It owns the agent-facing tools, limits, redaction and the report.
- **AutoDebug extension (JavaScript, no dependencies).** Runs in each IDE window.
  It owns the approval dialog and every call into the IDE.

## Agent tools

| Tool | Does |
|---|---|
| `list_targets` | IDE windows, their folders, launch configurations and build tasks |
| `start_session` | Ask the developer to approve, then build, set breakpoints, launch; waits for the first stop |
| `wait` | Wait for the session to change state (approval, build, stop, exit) |
| `step` | Step over, into or out (1–20 times); returns the new location and the variables that changed |
| `continue` | Run to the next stop and return it |
| `pause` | Stop a running program where it is |
| `inspect` | Variables of a frame: all names, types and short values, or full values of named ones |
| `stack` | Call stack, top frame first |
| `breakpoints` | Add or remove breakpoints during the session |
| `trace` | Run to a line repeatedly and collect the named variables at each hit |
| `stop_session` | End the debug session |
| `write_report` | Write the Markdown report: problem, root cause, solution, verification, timeline |

There is no tool that evaluates expressions or changes variables.

## Approval

Before asking, the extension checks that an installed extension provides the
launch configuration's debugger type; if not, `start_session` fails with
`NOT_FOUND` and names the extension to install.

`start_session` opens a modal dialog in the IDE window. It shows what will run:
the build task's command, the launch configuration (program, module, arguments),
the breakpoints, the step limit and the goal. Only **Approve** starts anything;
**Deny**, closing the dialog or two minutes without an answer refuse. One
approval covers one debug session. The extension runs exactly the configuration
it showed, read once at approval time.

## Limits and redaction

- One session per IDE window. Step limit per session (default 50, at most 500),
  enforced by both parts. Sessions end after `max_minutes` (default 30).
- Values whose name or content looks secret (password, token, key, credential,
  cookie; key-shaped strings) are replaced with `***REDACTED***` before the
  agent or the report sees them. Values are capped at 2,000 characters.
- Breakpoint files must be inside the workspace folder.

## Extension protocol

Connection file `<state>/bridges/<window>.json` (`%LOCALAPPDATA%\autodebug`,
`~/Library/Application Support/autodebug`, `~/.local/state/autodebug`), mode
0600 where the OS supports it:
`{"protocol": 2, "port", "token", "window", "ide", "folders", "version"}`.

AutoDebug connects to `127.0.0.1:<port>` and sends `{"hello": token}`; a wrong
token closes the connection. Then one JSON object per line:
`{"id", "op", "args"}` → `{"id", "ok", "result" | "error": {"code", "message"}}`.

| Op | Args | Result |
|---|---|---|
| `info` | – | window, ide, folders, versions |
| `targets` | `folder` | `launch` (name, type, request, program/module, args), `tasks` (label, command) |
| `start` | `folder`, `launch`, `task`, `breakpoints`, `goal`, `max_steps`, `max_minutes` | `state` |
| `state` | `since`, `wait_ms` | `state` (long poll: returns when `version` > `since` or after `wait_ms`) |
| `stack` | `levels` | `frames` |
| `variables` | `frame`, `names` (null = all) | `variables` |
| `step` | `kind` (`over`/`into`/`out`) | `state` after the step |
| `continue`, `pause`, `stop` | – | `state` |
| `breakpoints` | `add`, `remove` | `breakpoints` |

`state`: `{version, status, reason, location {file, line}, exit_code, message,
breakpoints [{file, line, verified, message}], steps_used, max_steps,
build {task, status, exit_code} | null}` where
`status` is `awaiting_approval`, `denied`, `building`, `build_failed`,
`starting`, `running`, `paused` or `ended`.

Error codes: `NO_WINDOW`, `AMBIGUOUS_WINDOW`, `NOT_FOUND`, `NOT_APPROVED`,
`BUSY`, `NOT_PAUSED`, `LIMIT`, `OUTSIDE_WORKSPACE`, `BAD_REQUEST`, `IDE_ERROR`.

## Report

`write_report` writes `<workspace>/autodebug-reports/<date>-<title>.md`, never
overwriting: summary table, problem, how it was run, debug timeline (every stop,
step, inspection and trace, numbered), root cause with confidence
(`confirmed` needs how it was confirmed), solution, verification (marked as
reported by the agent), open questions.

## Setup

`autodebug setup cursor|vscode [FOLDER]` builds the extension package, installs
it with the IDE's own `--install-extension`, and writes the MCP entry: Cursor's
global `~/.cursor/mcp.json`, VS Code's user `mcp.json`, or `FOLDER`'s project
file when a folder is given. `autodebug doctor` checks Python, the config files
and running extension windows.
