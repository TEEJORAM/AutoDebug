# Requirements delta

### CLI-01 Subcommands
`autodebug serve` runs the MCP stdio server; `autodebug doctor` checks the
environment; `autodebug config <client>` prints client configuration;
`autodebug --version` prints the version. Running `autodebug` with no
subcommand prints usage to stderr and exits 2. The legacy form
`autodebug --evidence-dir DIR [--demo]` still serves.

- Given `serve`, stdout carries only JSON-RPC messages; all diagnostics go to
  stderr, including one startup line naming the version and evidence folder.
- Given `serve` from an interactive terminal, stderr explains that it waits for
  an MCP client and is not a shell.

### CLI-02 Evidence location
`--evidence-dir`, else `AUTODEBUG_EVIDENCE_DIR`, else a per-user default
(`$XDG_STATE_HOME/autodebug` or `~/.local/state/autodebug` on Linux,
`~/Library/Application Support/autodebug` on macOS, `%LOCALAPPDATA%\autodebug`
on Windows). Each `serve` run creates a new private `run-<UTC time>-<random>`
folder inside it and uses that as the evidence base, so repeated starts with
`--demo` never collide. All existing evidence rules (outside the repository,
owner-only, exclusive case folders) still apply.

### CLI-03 Doctor
`doctor` reports Python version, platform, secure evidence storage support,
the evidence location and whether it is usable, each adapter's applicability
and connection state, and the security-gate state. It never creates files. It
exits 0 when `serve --demo` can run, 1 otherwise; `--json` gives machine output.

### CLI-04 Client configuration
`config vscode | claude-code | claude-desktop | cursor` prints a ready-to-use
entry in that client's documented format. The command is the absolute path of
the running interpreter with `-m autodebug serve`; a source checkout adds
`PYTHONPATH`. On a platform without secure evidence storage it also warns on
stderr that cases will fail.

### CLI-06 Writing client configuration
`config <client> --write [PROJECT_FOLDER]` adds or replaces the AutoDebug entry
in the client's configuration file (VS Code `PROJECT_FOLDER/.vscode/mcp.json`,
Cursor `PROJECT_FOLDER/.cursor/mcp.json`, Claude Desktop's global file; Claude
Code is refused because it is configured by command). Other entries and
settings are kept; the file is written atomically as UTF-8, converting an
existing UTF-16/BOM file. A file that is not plain JSON is left untouched and
the command fails. Printed hints use the same invocation the user ran
(`py -m autodebug`, `python3 -m autodebug` or `autodebug`).

### CLI-05 Installation
`pip install .` installs the `autodebug` command; `pip install -e .` installs an
editable copy. No dependencies are added.
