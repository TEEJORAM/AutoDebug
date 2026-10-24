# Contributing

There is no assigned license and external contributions are not yet
authorized; see [docs/publication.md](docs/publication.md).

## Workflow

1. Read `README.md`, `CLAUDE.md` and `docs/status.md`.
2. Read the relevant spec, design and task in
   `openspec/changes/autodebug-foundation/`. Requirements there are normative.
3. Get explicit human approval for one named task. A behaviour change needs a
   new reviewed proposal, requirements delta, design and tasks first.
4. State the linked requirement IDs, then add or update fake-backed tests with
   the change.
5. Run `PYTHONPATH=src python3 -m unittest discover -s tests` on Python 3.11+.
   Record the interpreter, command and result; a configured CI job is not a run.
6. Update the related docs, `tasks.md` and `docs/status.md`. Leave review gates
   unchecked until the required human review happens.

## Safety and data

- Real debugger control stays disabled until the T05 gate is approved. Agent
  tool calls and chat strings are never human authorization.
- Fusion and other applications: use only their existing script UI or already
  approved facilities; no in-app helper, embedded server or injection.
- Use synthetic fixtures and disposable applications only. Never commit Jira
  exports, customer data, debugger captures, tokens, employee identities or
  internal locations.
- Keep case data outside Git; ignore rules do not remove tracked history.
- Do not copy, fork or vendor DebugMCP or internal bridge code. Dependencies,
  external MCP services and model/data routing need Autodesk approval.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
