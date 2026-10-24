# Project status

**As of 2026-10-24.** Fake-only foundation, implementation complete for this
iteration. Real-debugger control is disabled (T05 gate **OPEN / NOT
APPROVED**). Publication is **BLOCKED** pending the decisions in
[publication.md](publication.md).

## What works

- Dependency-free MCP 2025-11-25 stdio server with 15 `autodebug_*` tools
  (`python -m autodebug`), plus an isolated synthetic demo (`--demo`).
- Case workflow: plan staging and digest, approval verification, arming,
  bounded stop/stack/variable inspection, step/continue, completion and
  cancellation, with redacted local evidence (`events.jsonl`, `case.json`,
  `report.md`).
- Five IDE adapters (VS Code, Cursor, CLion, Xcode, Visual Studio) sharing one
  client-backed implementation, tested against mock clients only.
- Offline stdlib-only wheel/sdist builder.

## What does not work yet

- **No native IDE debugger is integrated or certified.** All 11 IDE/OS cells
  are `BLOCKED`, `UNSUPPORTED` or `NOT_TESTED`; see the
  [compatibility ledger](compatibility-ledger.md).
- **No trusted human approval.** `issue_approval`'s `human_presence_confirmed`
  flag cannot prove a person approved anything, and `verify_approval` refuses
  every backend except `"fake"`.
- **Evidence storage is POSIX-only.** On Windows it fails closed: `--demo`
  exits with a startup error and arming any case returns a storage error.

## Verification

| Date | Environment | Command | Result |
|---|---|---|---|
| 2026-10-24 | GitHub Actions run 40074228400 (commit `847c08a`): Ubuntu and macOS, Python 3.11 and 3.12 | full suite, `compileall`, whitespace check | all 4 jobs passed |
| 2026-10-24 | GitHub Actions, same run: Windows, Python 3.11 and 3.12 | contract-only subset (evidence storage is POSIX-only) | both jobs passed |
| 2026-10-24 | Linux, Python 3.13 | `PYTHONPATH=src python3 -m unittest discover -s tests` | 481 tests, OK |
| 2026-10-24 | Linux, Python 3.10 (user machine VM) | same | 481 tests, OK (2 packaging tests skipped: need 3.11) |

Not run: the full suite on Windows (it cannot pass until evidence storage
supports Windows). All tests use fake or mock backends.

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
