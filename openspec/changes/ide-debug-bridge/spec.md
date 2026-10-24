# Requirements delta

All requirements apply to the `vscode-bridge` backend only. The synthetic
`--demo` backend and the CLion, Visual Studio and Xcode adapters are unchanged.

### BR-01 Bridge extension
The AutoDebug Bridge extension is original JavaScript with no runtime
dependencies. When a workspace folder is open it listens on `127.0.0.1` only, on
an ephemeral port, and writes a connection file (port, 256-bit random token,
window ID, workspace folders, extension version) into a private per-user
`bridges` folder next to the evidence base. Every connection must present the
token first (constant-time comparison); otherwise it is closed. The listener and
connection file are removed when the window closes.

- Given a connection file in a folder that is not private to the user,
  AutoDebug refuses to use it.
- Given a wrong or missing token, the bridge answers nothing and closes.

### BR-02 Discovery and session identity
AutoDebug selects the bridge whose workspace folder equals the plan's
`workspace_folder` (normalised, case-insensitive on Windows). Zero matches is
`BACKEND_UNAVAILABLE`; two or more is `SESSION_AMBIGUOUS`. Session identity is
host, bridge window ID, DAP session ID and the debuggee PID reported by DAP's
`process` event; never a process name.

### BR-03 Plan schema 0.3
A plan adds `workspace_folder`, `launch_configuration_name`, optional
`build_task` (a task label) and `report_to_workspace` (default true).
Breakpoint files are relative to the workspace folder and must stay inside it.
Before approval the bridge resolves the named launch configuration and task and
hashes them together with each breakpoint file's bytes; these hashes are part of
the plan digest.

- Given a changed launch configuration, task or breakpoint file after approval,
  every later mutating call fails with `PLAN_CHANGED` and the case becomes
  `INCOMPLETE`.
- Given a launch configuration with `request: attach`, staging fails
  (launch only).

### BR-04 Human approval in the IDE
`autodebug_request_approval` sends the staged plan to the bridge, which shows a
modal dialog listing: workspace, build task and command, launch configuration
(program and arguments), every breakpoint, step limit and time limit.
Only a click on **Approve** approves. **Deny**, dismissing the dialog or 120
seconds without an answer gives `NOT_APPROVED`. `autodebug_wait_for_approval`
waits at most `max_operation_seconds` per call and reports `PENDING`,
`APPROVED` or `DENIED`.

An approval is bound to the case, plan digest, bridge window and expiry
(`max_inspection_seconds`, at most 1 hour). The bridge keeps its own record and
refuses any operation that the approval does not cover, even if AutoDebug asks.
No MCP tool, argument or environment variable can approve. `vscode-bridge` is
added to a hardcoded allowlist of backend kinds; nothing else is added.

### BR-05 Build
If the plan names `build_task`, arming runs it through the IDE's task system and
waits for the exit code, at most `policy.max_build_seconds` (default 300, at
most 900). A non-zero exit or timeout stops the case with a new error code,
`BUILD_FAILED`, and the program is not launched. The exit code and the last 50
lines of output, redacted and bounded, are recorded as evidence. *(B8 finding:
the VS Code extension API cannot read a task's terminal output, so the real
bridge records the exit code and points to the IDE terminal.)*

### BR-06 Launch and breakpoints
After the build, the bridge adds exactly the plan's breakpoints, then starts the
named launch configuration, so the session is visible in the IDE. Each
breakpoint's binding (verified, actual line or message) is recorded. If no
breakpoint binds, the case stops with `BREAKPOINT_UNBOUND`.

### BR-07 Stop, inspect and step
`autodebug_wait_for_stop` reports the stop reason, file and line from DAP's
`stopped` event. Stack and variables use DAP `stackTrace`, `scopes` and
`variables`. `autodebug_list_variables` returns names and types only, never
values. Step over, in and out and continue use DAP `next`, `stepIn`, `stepOut`
and `continue`; each counts toward `max_steps`. The bridge forwards no other
DAP request: no `evaluate`, `setVariable`, `setExpression` or custom requests.
Values pass through the existing redaction once, at the facade.

### BR-08 Ending
Completing or cancelling the case, approval expiry, an exhausted step budget, or
the program exiting ends the debug session and removes the breakpoints AutoDebug
added. Breakpoints the developer set are untouched.

### BR-09 Report
`autodebug_complete_case` accepts `problem`, `root_cause_statement`,
`solution`, `verification` and the existing fields. `report.md` contains, in
order: Summary (case, outcome, confidence), Problem, Reproduction (plan, build
result, launch), Debug timeline (one row per stop and step: evidence ID, reason,
file:line, selected redacted variables), Root cause, Solution, Verification
(labelled "reported by the AI agent" unless AutoDebug observed it), Uncertainties,
Next steps, Evidence index. With `report_to_workspace`, the same report is
written to `<workspace>/autodebug-reports/<case-id>.md`, never overwriting an
existing file. `CONFIRMED` still requires causal validation.

### BR-10 Agent guidance
The server's MCP `instructions` and tool descriptions describe the workflow in
order: read the code, stage a plan, request approval, wait for approval, arm,
wait for stop, inspect, step, complete. A prompt such as "Help to debug
AutoDebugDemo" must be enough for an agent to follow it.

### BR-11 Verification
A fake bridge written in Python and speaking the same protocol backs all
automated tests. The real extension is verified by hand against AutoDebugDemo
and each result is recorded in the compatibility ledger; CI makes no claim about
a real IDE.

### BR-12 Install
`autodebug bridge install vscode|cursor` builds the extension package with the
standard library and installs it with the IDE's own `--install-extension`
command, or prints that command if the IDE CLI is not on PATH. `doctor` reports
whether a bridge is running for each open workspace.
