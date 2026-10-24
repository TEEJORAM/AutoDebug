# AutoDebug Bridge

Lets the AutoDebug MCP server run this window's debugger for an AI agent, and
only after you click **Approve** in the dialog that lists the whole plan:
build task, launch configuration, breakpoints and limits.

- Listens on 127.0.0.1 only, with a random token kept in a private file.
- Never evaluates expressions or changes variables.
- Ends the debug session and removes its breakpoints when the case ends,
  the approval expires, or any approved file changes.

Install with `autodebug bridge install vscode` (or `cursor`).
Log: Command Palette → **AutoDebug Bridge: Show Log**.
