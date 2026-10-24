# CLI usability and getting started

Requested by the developer on 2026-10-24: installing, running and connecting
AutoDebug to an AI client was unclear, and the CLI should follow the shape of
common MCP server CLIs.

Scope:

- `autodebug serve | doctor | config` subcommands, `--version`, clear help.
- A private default evidence directory and one evidence folder per server run,
  so MCP clients can restart the server with a fixed configuration.
- Client configuration snippets for VS Code, Claude Code, Claude Desktop and
  Cursor, using an absolute interpreter path.
- `pip install .` and `pip install -e .` (PEP 660 editable hook).
- A getting-started guide that separates what works now (AI client → AutoDebug,
  synthetic backend) from what does not (AutoDebug → a real IDE debugger).

Out of scope: any native debugger integration, the T05 security gate, Windows
evidence storage, new dependencies, network transports.
