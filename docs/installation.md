# Local installation and synthetic MCP use

This is an authorized-checkout workflow, not permission to distribute AutoDebug.
Python 3.11+ is declared; see [status](status.md) for interpreters actually tested.
No runtime dependency, MCP SDK, IDE, Jira connection or company infrastructure is
needed. No command here enables native debugger access.

## Source-tree use

From the checkout on a POSIX host:

```sh
PYTHONPATH=src python3 -m autodebug --help
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests build_backend.py
git diff --check
```

Create or select a private directory outside this checkout. Existing evidence
bases must belong to the current user with no group/other permissions (0700).
New bases are created privately. Every investigation needs a fresh case ID;
restarting a demo with an existing `AUTODEBUG-DEMO` directory is refused rather
than silently accepting old evidence. Choose a fresh base for a new demo.

```sh
PYTHONPATH=src python3 -m autodebug --evidence-dir /private/path/to/new-evidence --demo
```

The process reads one UTF-8 JSON-RPC object per line on stdin and writes only
protocol responses to stdout. Diagnostics use stderr. Send initialization,
then the initialized notification:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"local-review","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"autodebug_get_stack","arguments":{"case_id":"AUTODEBUG-DEMO","frame_limit":2}}}
```

Wait for each requested response when sequencing dependent operations. Request
IDs must be unique. The fixed demo has a 60-second lifetime, five steps and a
synthetic predetermined stop. `--demo` is an explicit local synthetic fixture;
it is not an OS-trusted human-presence broker. No tool can issue approval,
select a native backend, run a script, evaluate an expression or execute a shell.
Without `--demo`, cases can be drafted, but debugger actions remain unapproved.

To finish an inconclusive demonstration:

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"autodebug_complete_case","arguments":{"case_id":"AUTODEBUG-DEMO","root_cause_statement":"Synthetic demonstration only; no application defect established.","confidence":"inconclusive","evidence_ids":[],"reproduced":false}}}
```

The result gives relative paths to `case.json`, `events.jsonl` and `report.md`.
These paths are relative to the selected evidence base, never a remote URL.
EOF cancels unfinished cases without killing an application.

## Offline package artifacts

An original stdlib-only PEP 517 backend is declared with an empty build
requirement list. In an approved local build workflow:

```sh
python3 -c "import build_backend; print(build_backend.build_wheel('dist')); print(build_backend.build_sdist('dist'))"
```

This writes local candidate archives only, without downloading dependencies.
A wheel contains package source and distribution metadata, not tests, Git
history, evidence or developer configuration. A source archive contains the
build inputs, README and package source; repository documentation remains in
the authorized source checkout. An authorized local installer can consume the
wheel with `--no-index --no-deps`; no package-index publication is authorized.
The `autodebug` console entry point and `python -m autodebug` call the same main.
Offline tests verify archive hashes, metadata, isolated import and source rebuild.
They do not establish a public license or enterprise installation approval.

## Windows and unavailable environments

PowerShell source imports/contract checks use `$env:PYTHONPATH = "src"`.
Protocol parsing, schemas and offline package checks are platform-neutral.
Secure evidence uses POSIX descriptor-relative no-follow opens; Windows evidence
initialization explicitly fails closed. Do not substitute ordinary path opens
to make a Windows workflow appear green. Actual Linux/Windows/Python 3.11 results
require those environments; configured CI is not execution evidence.

## Publication after permission

These are future steps, not authorization or commands executed by finalization:

1. Obtain the four written decisions in the [approval request](ossa-legal-approval-request.md):
   publish/transfer permission; copyright/license; exact artifact/destination/
   history treatment; and personal-account/equipment development permission.
   Do not upload code to personal GitHub or a personal AI service beforehand.
2. Apply only authorized copyright/license/notices, then freeze and approve the
   exact release tree/archive and its digest. The current candidate has no
   assigned license. Exclude credentials, generated evidence, logs, temporary
   patches/archives and private operational files.
3. Follow the approved history treatment. Existing history is not a public-safe
   artifact. If a clean snapshot export is approved, export only the approved
   tracked tree into a separate authorized release location without copying
   `.git`, private refs or local session files. Preserve required provenance and
   notices and retain the original private repository untouched. Do not push
   the current checkout, mirror its refs or initialize replacement history
   without the explicit history decision.
4. Only then create the repository at the approved GitHub destination and publish
   the approved artifact/history from the authorized release location. Run the
   existing CI there, record actual outcomes, and use the [release summary](release-notes.md)
   with the fake-only/native limitations intact.

No repository, remote, export, upload, license or history change is created by
this guide. Missing native certifications remain documented capability limits;
publication of a fake-only foundation does not authorize native debugger use.
