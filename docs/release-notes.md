# Release notes

AutoDebug 0.1.0 (evidence schema `0.2-draft`). **Unreleased:** publication,
licensing and native debugger access are blocked (see
[publication.md](publication.md)).

## 2026-10-24 — copy-and-paste setup

- `autodebug config <client> --write [PROJECT_FOLDER]` writes the client
  configuration file directly (UTF-8, keeps other servers). This replaces
  shell redirection, which produced UTF-16 files in Windows PowerShell 5.1.
- `doctor` and `config` hints show the exact command form you used
  (`py -m autodebug` on Windows).
- README and getting-started list only commands that can be pasted as-is.

## 2026-10-24 — native Windows support

- Evidence storage now works on Windows with the same protections as macOS
  and Linux (no links or junctions, pinned case folders, private access lists,
  atomic snapshots), using only the Python standard library.
- `autodebug doctor` and `serve --demo` work on Windows.
- CI runs the full suite on Windows, macOS and Ubuntu with Python 3.11, 3.12
  and 3.14, and reports failures as annotations.

## 2026-10-24 — CLI and getting started

- New `autodebug` subcommands: `serve`, `doctor` (machine check, `--json`) and
  `config` (VS Code, Claude Code, Claude Desktop, Cursor).
- Evidence defaults to a private per-user folder; each server run gets its own
  `run-*` folder, so clients can restart the server with `--demo` freely.
  `--evidence-dir` now selects the base, not the run folder.
- The demo approval lasts 30 minutes (was 60 seconds).
- `pip install -e .` works (PEP 660); the console entry point is
  `autodebug.cli:main`. The legacy `autodebug --evidence-dir DIR` still serves.
- New [getting-started.md](getting-started.md).

## 2026-10-24 — quick fixes

- `VisualStudioAdapter` now defaults to host `local-windows` instead of
  `local-mac`; every adapter's default can be overridden with `host_id=`.
- Offline packaging tests skip with a clear reason below Python 3.11.
- CI uses `actions/checkout@v7` and `actions/setup-python@v7`; first green runs
  on Ubuntu/macOS (full suite) and Windows (contract subset), Python 3.11/3.12.

## 2026-10-24 — readability and cleanup

- Five IDE adapters share one `ClientBackedAdapter`; adapter tests and fake
  clients are one parametrized suite. No behaviour change.
- Facade session tools share one error mapper and lock/re-check helpers; MCP
  tool bounds are declared once and drive both schema and validation (the
  published schema is unchanged).
- Removed dead code; `bind_breakpoints` now refuses cleanly without a plan.
- Documentation consolidated: publication and license material in
  `publication.md`, requirement status in `traceability.md`, upgrade steps in
  `installation.md`, DebugMCP mapping in `ide-integrations.md`.

## Foundation (technical closure)

### Added

- Dependency-free MCP 2025-11-25 stdio transport with strict schemas and
  bounded JSON-RPC parsing; `python -m autodebug` and the `autodebug` command.
- Isolated synthetic backend and `--demo`; no IDE required.
- Offline stdlib-only wheel/sdist builder.
- Full reproduction-script content with recomputed SHA-256, reviewed risks and
  sample-document description; launch configuration and process state in the
  plan digest.
- Process-start, stop and frame-generation identities; stored stop/stack
  evidence; execution-confidence and causal-validation fields.
- Bounded backend waits, prompt cancellation, quarantine and late-result cleanup.
- Integrity-checked append ledger, record-size cap, private evidence bases
  outside the repository, evidence-capacity checks before reads.

### Fixed

- Nested variable secrets no longer survive stringification.
- Session ownership survives unregister/re-register.
- Empty, partial or foreign breakpoint confirmations cannot arm reproduction.
- Non-finite, duplicate or tampered approvals fail closed; monotonic expiry
  stops wall-clock rollback from extending approval.
- Backend failures cannot reopen a case or accept late data; cancellation is
  not blocked by rendering, and in-flight targets are quarantined.

### Compatibility

- API-script plans need actual content with a matching digest; digest-only
  plans are rejected. Launch/attach arguments must match the reviewed plan.
- Conditional breakpoints are refused pending an evaluation policy.
- Existing case folders cannot be reopened; no evidence is migrated or deleted.
- Windows evidence storage is unavailable (fails closed).
