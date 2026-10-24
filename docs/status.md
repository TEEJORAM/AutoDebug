# Project status

**As of 2026-10-24.** Fake-only foundation, implementation complete for this
iteration. Real-debugger control is disabled (T05 gate **OPEN / NOT
APPROVED**). Publication is **BLOCKED** pending the decisions in
[publication.md](publication.md).

## What works

- Native Windows, macOS and Linux, including evidence storage.
- `autodebug` CLI: `serve` (dependency-free MCP 2025-11-25 stdio server with 15
  tools), `doctor`, `guide` and `config` for VS Code, Claude Code, Claude
  Desktop and Cursor; installable with `pip install .` / `-e .` / `pipx`.
  Setup steps for Windows, macOS and Linux are in `site/index.html`.
- Isolated synthetic demo debugger (`serve --demo`).
- Case workflow: plan staging and digest, approval verification, arming,
  bounded stop/stack/variable inspection, step/continue, completion and
  cancellation, with redacted local evidence (`events.jsonl`, `case.json`,
  `report.md`).
- Five IDE adapters (VS Code, Cursor, CLion, Xcode, Visual Studio) sharing one
  client-backed implementation, tested against mock clients only.
- Offline stdlib-only wheel/sdist builder.
- Sample project for practice and future adapter tests:
  [examples/AutoDebugDemo](../examples/AutoDebugDemo/README.md). Moving a shape
  keeps its area.

## What does not work yet

- **No native IDE debugger is integrated or certified.** All 11 IDE/OS cells
  are `BLOCKED`, `UNSUPPORTED` or `NOT_TESTED`; see the
  [compatibility ledger](compatibility-ledger.md).
- **No trusted human approval.** `issue_approval`'s `human_presence_confirmed`
  flag cannot prove a person approved anything, and `verify_approval` refuses
  every backend except `"fake"`.

## Verification

| Date | Environment | Command | Result |
|---|---|---|---|
| 2026-10-24 | GitHub Actions run 40078110989: Windows, macOS and Ubuntu × Python 3.11, 3.12, 3.14 | full suite (`.github/run_tests.py`), `compileall` | all 9 jobs passed; 518 tests each (Windows skips 1 POSIX-only FIFO test; macOS/Ubuntu skip the 9 Windows-only tests) |
| 2026-10-24 | Linux, Python 3.13 | `PYTHONPATH=src python3 -m unittest discover -s tests` | 518 tests, OK (9 skipped) |
| 2026-10-24 | Linux, Python 3.12.3 | `PYTHONPATH=src python3 -m unittest discover -s tests` | 523 tests, OK (9 skipped) |
| 2026-10-24 | Linux, Python 3.12.3 | demo `report.py` and `python3 -m unittest discover -s examples/AutoDebugDemo` | areas stay `1.00` / `6.00` / `6.00` after move; 2 tests OK |

All tests use fake or mock backends.

## Open blockers

1. **Real-debugger gate (T05).** Needs an OS-level human-presence mechanism,
   broker isolation, verified device identity (the `DE-07` host check is a
   naming heuristic), a reviewed backend allowlist and signed approvals.
   Candidate designs: [security-gate-closure-proposal.md](security-gate-closure-proposal.md).
2. **Autodesk approvals** for Claude Code use with project data, any MCP SDK,
   DebugMCP or other bridge, and model/data routing.
3. **Native backends unavailable** on the development machine: DebugMCP not
   installed (VS Code), no Cursor debugger bridge, CLion not installed, Xcode
   26.0.1 without `mcpbridge`, no Windows host (Visual Studio) and no Linux host.
4. **Case-data retention policy** undecided ([security.md](security.md#case-data-policy)).
5. **Independent T15 sign-off** outstanding ([publication.md](publication.md)).

## Next action

Owner decides on the publication items and the repository's visibility. No
further implementation is authorized until a new task is approved in
`openspec/changes/autodebug-foundation/tasks.md`.

## Change log

- **2026-10-24 — demo area fix.** `polygon_area` in
  `examples/AutoDebugDemo` includes the closing edge in Python and C++.
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
