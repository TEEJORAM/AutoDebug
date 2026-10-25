# CLAUDE.md — working on AutoDebug

AutoDebug: an MCP server (Python, `src/autodebug`) plus a VS Code / Cursor
extension (`src/autodebug/extension`) that let an AI agent debug a program with
the IDE's own debugger and write a root-cause report. All logic is in Python;
the extension is a thin JavaScript relay (IDE extensions can only be JavaScript):
the Approve dialog, tasks, breakpoints, start/stop and Debug Adapter Protocol
passthrough. Add new behaviour in Python; change the relay only when the IDE
API itself is needed.
Read `docs/design.md` first; it is the contract between the two parts.

## Process
- Keep `docs/design.md` true. A change to tools, protocol, approval or limits
  updates it in the same change.
- Every change comes with tests; run them before pushing:
  `PYTHONPATH=src python -m unittest discover -s tests` (Node.js runs the
  relay tests; debugpy and gdb 14+ enable the real-debugger tests).
- Report what you actually ran and its result. Never claim a test, IDE run or
  debugger capability that did not happen.

## Rules
- Supported IDEs: VS Code and Cursor. Use only the public VS Code extension API
  and the Debug Adapter Protocol. Write original code; do not copy other
  projects.
- Nothing runs without the developer's click on **Approve**; an agent message is
  never an approval. Approval covers one debug session and exactly what the
  dialog showed.
- No expression evaluation or variable writes. Redact secret-looking values.
  Listen on 127.0.0.1 only, with a token.
- No runtime dependencies in either part. Ask before adding any.
- Never point the debugger at production systems or real customer data; use
  `examples/` or disposable test programs.
