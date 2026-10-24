# Installation and protocol reference

AutoDebug needs only Python 3.11+ on Windows, macOS or Linux. There are no
runtime dependencies, and nothing here enables native debugger access.

Start with [getting-started.md](getting-started.md). This page covers the
details behind it.

## Install options

| Method | Command | Use when |
|---|---|---|
| Editable (developers) | `pip install -e .` | You change the code |
| Regular | `pip install .` | You only run it |
| Isolated tool | `pipx install .` | You want `autodebug` on your `PATH` without a venv |
| No install | `PYTHONPATH=src python3 -m autodebug ...` | Quick checks from the checkout |

Run the checks with `PYTHONPATH=src python3 -m unittest discover -s tests`.

## Evidence folders

`serve` stores evidence under `--evidence-dir`, else `$AUTODEBUG_EVIDENCE_DIR`,
else `~/.local/state/autodebug` (Linux, or `$XDG_STATE_HOME/autodebug`),
`~/Library/Application Support/autodebug` (macOS) or `%LOCALAPPDATA%\autodebug`
(Windows). Each run creates a new private `run-<UTC time>-<random>` folder there,
so clients can restart the server freely. The base must be outside the
AutoDebug checkout; folders are created owner-only (`0700` on macOS/Linux, a
protected owner-only access list on Windows).

`--demo` seeds the synthetic case `AUTODEBUG-DEMO` with a local 30-minute
approval, five steps and a predetermined stop. It never touches a real
debugger. Without `--demo`, cases can be drafted but every debugger action is
refused for lack of approval.

## Talk to the server

The server reads one UTF-8 JSON-RPC message per line on stdin and writes
responses to stdout. Diagnostics go to stderr: one startup line, the evidence
folder, and warnings (`--log-level` adjusts them). Request IDs must be unique.

```sh
autodebug serve --demo
```

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"local-review","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"autodebug_get_stack","arguments":{"case_id":"AUTODEBUG-DEMO","frame_limit":2}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"autodebug_complete_case","arguments":{"case_id":"AUTODEBUG-DEMO","root_cause_statement":"Synthetic demonstration only.","confidence":"inconclusive","evidence_ids":[],"reproduced":false}}}
```

Completion returns paths to `case.json`, `events.jsonl` and `report.md`
relative to the run folder. Closing stdin (EOF) cancels unfinished
cases without touching any application.

## Windows

Everything works natively: use `py -m autodebug ...` if Python's `Scripts`
folder is not on your PATH. Evidence storage uses Windows handles instead of
POSIX file descriptors, with the same protections (see
[security.md](security.md#case-data-policy)).

## Build offline packages

```sh
python3 -c "import build_backend; print(build_backend.build_wheel('dist')); print(build_backend.build_sdist('dist'))"
```

The wheel contains the package and metadata only. Install it locally with
`pip install --no-index --no-deps dist/autodebug-0.1.0-py3-none-any.whl`.
Building is not permission to distribute (see [publication.md](publication.md)).

## Upgrade and roll back

1. `git pull` (or `git revert` / check out a known-good commit to roll back).
2. Re-run the test suite; it is the upgrade check.
3. Re-read [status.md](status.md); an upgrade never changes the security gate.

AutoDebug has no configuration file, service or database, so there is nothing
else to migrate. Evidence carries schema versions (current output `0.2-draft`;
`0.1-draft` plan input is still accepted). Older code may not understand newer
evidence, so back up case folders before switching versions. Old case
folders are never reopened or migrated, and nothing deletes evidence
automatically.
