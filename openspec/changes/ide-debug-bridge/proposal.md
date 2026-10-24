# IDE debug bridge: real debugging in VS Code and Cursor

**Status: APPROVED by the developer on 2026-10-24** (decisions 1–3 below:
open the T05 gate for `vscode-bridge` with in-IDE approval; own bridge
extension; Python first, then C++). Decision 4 remains with Autodesk.

Requested by the developer on 2026-10-24. Given the prompt "Help to debug
AutoDebugDemo", an AI agent must be able to use AutoDebug to:

1. set breakpoints in the important part of the code;
2. build, compile and run the program under the IDE's own debugger;
3. when a breakpoint is hit, step in, over and out and read the stack and
   variables to find the fault;
4. write a well-organised Markdown report (problem, root cause, solution,
   evidence) into the project.

Today none of this works: AutoDebug only drives a synthetic debugger, has no
build or launch tool, and no plan can be approved for a real program (T05 gate).

## What changes

- **AutoDebug Bridge**, a small VS Code extension written for this project
  (plain JavaScript, no dependencies). It runs inside VS Code or Cursor and uses
  only the public VS Code extension API and the Debug Adapter Protocol (DAP) to
  run tasks, start debugging, set breakpoints, read stacks and variables, and
  step. It never copies Microsoft DebugMCP or any other third-party code.
- **Human approval inside the IDE.** The bridge shows the exact plan in a modal
  dialog; only a click on **Approve** in that window approves it. This replaces
  the synthetic approval for this one backend and is the T05 gate item 1
  "Option B" from [security-gate-closure-proposal.md](../../../docs/security-gate-closure-proposal.md).
- **Plan schema 0.3**: workspace folder, named launch configuration, optional
  build task, breakpoints and limits. The digest also covers the resolved launch
  and task definitions and the breakpoint files' contents, so editing any of them
  invalidates the approval.
- **New tools**: request/wait for approval, list variable names in a frame.
- **Report export**: `autodebug_complete_case` takes problem, root cause,
  solution and verification, and writes a structured report both to the
  evidence folder and to `<project>/autodebug-reports/<case>.md`.
- **Demo**: AutoDebugDemo gets a v0.3 plan and, in phase 2, a C++ build task and
  launch configurations.

## Phases

1. **Python in VS Code** on Windows, macOS and Linux (debugpy, through the
   Python extension the developer already has). Cursor: same extension, marked
   `NOT_TESTED` until run.
2. **C++ in VS Code**: CMake build task plus the C/C++ extension's debugger.
3. Later, separate proposals: CLion, Visual Studio, Xcode.

## Out of scope

Expression evaluation and setting variables (still denied); attaching to running
or production processes; changing breakpoints mid-session without a new
approval; any IDE other than VS Code and Cursor; new Python dependencies.

## Decisions needed before code

1. **Open the T05 gate for one backend, `vscode-bridge`**, with in-IDE modal
   approval as the human-presence mechanism. Accepted residual risk: a program
   that can inject mouse or keyboard input into your desktop could click
   Approve; a same-user process can read the bridge token but still cannot
   approve.
2. **Approach**: own bridge extension (recommended; the session is visible in
   the IDE and works for every language VS Code can debug) instead of AutoDebug
   launching `debugpy` itself (Python only, invisible to the IDE).
3. **Report location** `<project>/autodebug-reports/<case-id>.md`.
4. **Approval of AI use with project data** remains an Autodesk decision; the
   demo contains no company code.
