# Install, run and upgrade

AutoDebug needs only Python 3.11+ and a POSIX host (Linux or macOS). There are
no runtime dependencies, and nothing here enables native debugger access.

## Run from the source tree

```sh
PYTHONPATH=src python3 -m autodebug --help
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src tests build_backend.py
```

Evidence goes to a private directory **outside the checkout**. An existing
base must be owned by you with mode `0700`; a new one is created that way.
Every case needs a fresh case ID, so use a fresh base for each demo run.

```sh
PYTHONPATH=src python3 -m autodebug --evidence-dir ~/autodebug-evidence/run1 --demo
```

`--demo` seeds the synthetic case `AUTODEBUG-DEMO` with a local 60-second
approval, five steps and a predetermined stop. It never touches a real
debugger. Without `--demo`, cases can be drafted but every debugger action is
refused for lack of approval.

## Talk to the server

The server reads one UTF-8 JSON-RPC message per line on stdin and writes
responses to stdout (diagnostics go to stderr). Request IDs must be unique.

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"local-review","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"autodebug_get_stack","arguments":{"case_id":"AUTODEBUG-DEMO","frame_limit":2}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"autodebug_complete_case","arguments":{"case_id":"AUTODEBUG-DEMO","root_cause_statement":"Synthetic demonstration only.","confidence":"inconclusive","evidence_ids":[],"reproduced":false}}}
```

Completion returns paths to `case.json`, `events.jsonl` and `report.md`
relative to the evidence directory. Closing stdin (EOF) cancels unfinished
cases without touching any application.

## Windows

Run contract tests with `$env:PYTHONPATH = "src"`. Evidence storage relies on
POSIX descriptor-relative, no-follow file opens, so on Windows it fails closed
by design. Do not replace it with ordinary path opens.

## Build offline packages

```sh
python3 -c "import build_backend; print(build_backend.build_wheel('dist')); print(build_backend.build_sdist('dist'))"
```

The wheel contains the package and metadata only. Install it locally with
`pip install --no-index --no-deps dist/autodebug-0.1.0-py3-none-any.whl`; this
provides the `autodebug` command. Building is not permission to distribute
(see [publication.md](publication.md)).

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
