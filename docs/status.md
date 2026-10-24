# Project status

**As of 2026-10-24.** Real debugging in VS Code and Cursor through the
AutoDebug Bridge (T05 gate approved for `vscode-bridge` only); every case needs
the developer's click on Approve in the IDE. Publication is **BLOCKED** pending
the decisions in [publication.md](publication.md).

## What works

- Native Windows, macOS and Linux, including evidence storage.
- `autodebug` CLI: `serve` (dependency-free MCP 2025-11-25 stdio server with 20
  tools), `doctor`, `guide`, `bridge install|status` and `config` for VS Code,
  Claude Code, Claude Desktop and Cursor; installable with `pip install .` /
  `-e .` / `pipx`.
- **AutoDebug Bridge** for VS Code and Cursor: in-IDE approval dialog, build
  task, launch, breakpoints, stack, variables, step in/over/out, continue, and a
  structured report written into the project (`autodebug-reports/`).
  Setup steps for Windows, macOS and Linux are in `site/index.html`.
- Isolated synthetic demo debugger (`serve --demo`).
- Case workflow: plan staging and digest, approval verification, arming,
  bounded stop/stack/variable inspection, step/continue, completion and
  cancellation, with redacted local evidence (`events.jsonl`, `case.json`,
  `report.md`).
- CLion, Xcode and Visual Studio adapters (and the older DebugMCP-based VS Code
  adapter) share one client-backed implementation, tested against mocks only.
- Offline stdlib-only wheel/sdist builder.
- Sample buggy project for practice and future adapter tests:
  [examples/AutoDebugDemo](../examples/AutoDebugDemo/README.md).

## What does not work yet

- **The bridge has not yet run in a real VS Code or Cursor window.** It is
  verified by automated tests, including the real Python debugger (debugpy)
  behind a stand-in IDE API; see the [compatibility ledger](compatibility-ledger.md).
- **C++ through the bridge** (phase 2, task B10) and **CLion, Visual Studio,
  Xcode** are not supported.
- **Build output**: the VS Code API cannot read a task's terminal output, so
  only the build's exit code is recorded.

## Verification

| Date | Environment | Command | Result |
|---|---|---|---|
| 2026-10-24 | GitHub Actions (PR #17): Windows, macOS and Ubuntu × Python 3.11, 3.12, 3.14, with Node | full suite (`.github/run_tests.py`) | all 9 jobs passed; 625 tests each |
| 2026-10-24 | Linux, Python 3.13, Node 22, debugpy 1.8.11 | `tests/test_bridge_debugpy.py` | Pass: AutoDebugDemo bug found through the extension core and real debugpy |
| 2026-10-24 | GitHub Actions run 40078110989: Windows, macOS and Ubuntu × Python 3.11, 3.12, 3.14 | full suite (`.github/run_tests.py`), `compileall` | all 9 jobs passed; 518 tests each (Windows skips 1 POSIX-only FIFO test; macOS/Ubuntu skip the 9 Windows-only tests) |
| 2026-10-24 | Linux, Python 3.13 | `PYTHONPATH=src python3 -m unittest discover -s tests` | 518 tests, OK (9 skipped) |
| 2026-10-24 | Linux, Python 3.12.3 | `PYTHONPATH=src python3 -m unittest discover -s tests` | 523 tests, OK (9 skipped) |

Automated tests use fake bridges, a stand-in IDE API or mocks; one test uses
the real debugpy when it is installed.

## Open blockers

1. **Real-debugger gate (T05)** is approved for `vscode-bridge` only, with the
   in-IDE dialog as the human-presence mechanism and the residual risks listed in
   [security.md](security.md#ide-bridge-vscode-bridge-approved-2026-10-24). Other
   backends still need the items in [security-gate-closure-proposal.md](security-gate-closure-proposal.md).
2. **Autodesk approvals** for AI use with project data and model/data routing;
   AutoDebugDemo contains no company code.
3. **First real-IDE run** of the bridge on AutoDebugDemo, to be recorded in the
   compatibility ledger. CLion, Visual Studio and Xcode backends do not exist.
4. **Case-data retention policy** undecided ([security.md](security.md#case-data-policy)).
5. **Independent T15 sign-off** outstanding ([publication.md](publication.md)).

## Next action

Owner decides on the publication items and the repository's visibility.

**Phase 1 of [ide-debug-bridge](../openspec/changes/ide-debug-bridge/proposal.md)
is built** (B1–B9): real debugging in VS Code and Cursor through the AutoDebug
Bridge. Next: the developer's first run in a real VS Code window on
AutoDebugDemo, recorded in the compatibility ledger; then phase 2 (C++, B10).

## Change log

- **2026-10-24 — ide-debug-bridge B2–B9.** Bridge protocol and discovery,
  `VSCodeBridgeAdapter`, in-IDE approval (`vscode-bridge` allowlisted),
  build step, structured report exported to the project, agent guidance and
  `list_variables`, the AutoDebug Bridge extension and `bridge install`, and
  AutoDebugDemo in plan schema 0.3. Plain `serve` is now bridge mode.
- **2026-10-24 — ide-debug-bridge B1.** Plan schema 0.3 (workspace folder,
  named launch configuration, build task, report export) with resolved-input
  hashes in the digest. Validation only; nothing contacts an IDE yet.
- **2026-10-24 — user guide.** `autodebug guide`, `site/index.html`, and
  `.github/workflows/pages.yml` (`openspec/changes/user-guide/`). Setup steps
  for Windows, macOS and Linux. Real debugger control stays disabled.
- **2026-10-24 — AutoDebugDemo sample project.** `examples/AutoDebugDemo`
  (Python + C++, one deliberate bug, VS Code launch configs, sample plan) and
  `tests/test_examples.py`. Documentation and examples only; no behaviour change.
- **2026-10-24 — copy-and-paste setup.** `config --write`, invocation-aware
  hints, README rewritten with pasteable Windows/macOS/Linux commands.
- **2026-10-24 — native Windows evidence storage**
  (`openspec/changes/windows-evidence-storage/`). Handle-based backend with the
  POSIX guarantees; full suite now runs on Windows CI.
- **2026-10-24 — CLI and getting started** (`openspec/changes/cli-usability/`).
  `serve`/`doctor`/`config` subcommands, default private evidence location with
  one folder per run, 30-minute demo, editable installs, client snippets, and
  [getting-started.md](getting-started.md).
- **2026-10-24 — quick fixes.** `VisualStudioAdapter` defaults to host
  `local-windows` (was `local-mac`); packaging tests skip below Python 3.11; CI
  actions moved to v7 (Node 24); first green CI runs recorded above.
- **2026-10-24 — readability pass.** Facade session tools share one error
  mapper and lock/recheck helpers; server tool bounds are declared once; task-
  history docstrings replaced; docs consolidated (see release notes).
- **2026-10-24 — strict review.** Five adapters share `ClientBackedAdapter`;
  adapter tests and fake clients consolidated; dead code removed;
  `bind_breakpoints` fails closed without a plan.
- **2026-10-24 — technical closure.** MCP stdio transport, script integrity,
  stop identity, bounded operations and offline packaging (commit
  `736cc154` in the original private history).

Earlier per-task logs (T01–T15) are in `tasks.md` and in Git history
(commit `435df13`).

## Session update template

```text
Date:
Task ID:
Files changed:
Tests run (command + result):
Review / approval:
Blockers:
Next approved task:
```
