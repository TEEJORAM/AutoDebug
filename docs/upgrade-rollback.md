# AutoDebug — Upgrade, configuration recovery, and rollback (T15)

AutoDebug has an offline wheel/source builder and a fake-only stdio entry point,
but no authorized published package, standing service or native deployment.
Upgrades refer to an authorized source checkout or explicitly reviewed local
archive. Evidence lives under a caller-supplied private base outside the source
Git checkout; current code enforces this location and owner/private permissions.
See [installation](installation.md) and [release notes](release-notes.md).

## Upgrading the source tree

The package version is `0.1.0` and evidence output is `0.2-draft`; neither denotes
a public release. In an independently authorized upgrade workflow:

1. `git fetch` / `git pull` the approved remote branch, same as any other change to this repository.
2. Re-run the full test suite (`PYTHONPATH=src python3 -m unittest discover -s tests -v`) before trusting the new checkout — there is no separate "verify the upgrade" step; the test suite **is** the verification.
3. Re-check `docs/status.md` for the current milestone, approval state, and the real-debugger security gate status (`OPEN / NOT APPROVED` as of T15) — an upgrade never implicitly changes gate state; only an explicit, separately reviewed approval does.
4. `pyproject.toml` declares zero runtime dependencies as of T15 — there is nothing to `pip install` for an upgrade to break. If a future task adds a pinned dependency (per `docs/security.md`'s "keep dependency versions pinned and routinely reviewed"), this section must be revised to include a dependency-upgrade step, with Autodesk approval recorded per `docs/decisions.md`/`docs/status.md`'s blockers list.

## Rolling back the source tree

Standard Git rollback applies — `git revert` the offending commit(s), or check out a known-good prior commit/tag. Nothing in AutoDebug's own code performs a destructive action that outlives the process (no database, no persistent daemon, no installed system service), so a source rollback has no special cleanup step beyond the evidence-data considerations below.

## Case/evidence data across versions

- `CasePlan`, `EvidenceRecord` and `case.json` carry schema versions.
  Current output is `0.2-draft`; `0.1-draft` is historical.
- `events.jsonl` is **append-only** (`EvidenceStore.record_evidence`) and `case.json`/`report.md` are rewritten by `EvidenceStore.finalize`. A source rollback does not automatically alter case data, but older code is not guaranteed to understand or preserve data written by a newer schema; back up case folders before using them with a different version.
- No in-place migration or cross-process case resume is provided. A new
  investigation requires a fresh case ID and exclusive directory; existing
  historical JSONL/Markdown may be reviewed offline but is not imported as
  newly trusted evidence. No old artifacts are silently rewritten.
- A source-tree rollback does not remove evidence. Owner-approved retention
  and deletion remain explicit policy decisions, not an automatic cleanup job.

## Configuration recovery

AutoDebug has no persistent configuration file of its own as of T15 — every `AutoDebugFacade` is constructed in-process by its caller with explicit parameters (`registry`, `broker`, `evidence_base_dir`, clock/sleep injections). There is nothing to "recover" at the AutoDebug layer; if a future task adds a configuration file (e.g., for adapter discovery or policy defaults), this section must be revised to cover its own backup/recovery procedure.

## What this section does not cover

This document does not cover IDE-side configuration (VS Code/Cursor/CLion/Xcode/Visual Studio extension or bridge installation/removal) — that is each IDE's own upgrade/rollback surface, outside AutoDebug's control, and no adapter in this repository has ever been exercised against a real one (see `docs/compatibility-ledger.md`).
