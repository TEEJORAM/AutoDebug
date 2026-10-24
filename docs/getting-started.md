# Getting started

AutoDebug is a **command-line MCP server**. You don't run it as an app; your AI
client (VS Code Copilot, Claude Code, Claude Desktop or Cursor) starts it in the
background and talks to it over stdin/stdout.

## First, what works today

There are two separate connections:

```text
 AI client  ──(1) MCP──▶  AutoDebug  ──(2) adapter──▶  IDE debugger  ──▶  your app
 (VS Code Copilot,         server                       (VS Code, CLion,
  Claude, Cursor)                                         Xcode, ...)
```

| Connection | Status |
|---|---|
| **(1) AI client → AutoDebug** | **Works.** Any MCP client can start AutoDebug and call its 15 tools. |
| **(2) AutoDebug → a real IDE debugger** | **Not available yet.** Only a built-in *synthetic* debugger works. AutoDebug cannot yet attach to the debugger in your VS Code window. |

So today you can install AutoDebug, connect your AI client, and walk through a
complete investigation against the synthetic demo debugger. Debugging your own
application needs the missing pieces listed in
[Connecting a real IDE debugger](#connecting-a-real-ide-debugger).

## 1. Install

Requirements: **Python 3.11+**. There are no dependencies to download.

Where each command runs:

| Command | Run it in | Why |
|---|---|---|
| `pip install -e .` | Your **AutoDebug folder** (the one containing `pyproject.toml`) | `.` means "this folder". Run it once. |
| `autodebug doctor` | Any folder | After installing, `autodebug` is a normal command. |
| `autodebug config vscode --demo` | The **project folder you open in VS Code** (e.g. `D:\Projects\MyApp`), not the AutoDebug folder | VS Code reads `.vscode/mcp.json` only from the folder it has open. |

### Linux / macOS

```sh
cd ~/Projects/AutoDebug              # your AutoDebug folder
python3 -m venv .venv
source .venv/bin/activate
pip install -e .                     # or, without a venv: pipx install .
autodebug --version                  # autodebug 0.1.0
```

### Windows (PowerShell)

```powershell
py --version                         # must be 3.11 or newer
cd D:\Projects\AutoDebug             # your AutoDebug folder
py -m pip install -e .
py -m autodebug --version            # autodebug 0.1.0
```

On Windows, use `py -m autodebug ...` in place of `autodebug ...` in the rest
of this guide; it works even if Python's `Scripts` folder is not on your PATH.

## 2. Check your machine

```sh
autodebug doctor
```

```text
AutoDebug doctor (autodebug 0.1.0)

  ✔ Python            3.12.3
  · Platform          Linux 6.8.0
  ✔ Evidence storage  supported
  ✔ Evidence folder   /home/you/.local/state/autodebug (created on first run)
  ✔ Demo debugger     synthetic, ready for `serve --demo`
  · IDE adapters      vscode, cursor, clion target this OS; mock-only, no native debugger client yet
  · Real debuggers    disabled until the T05 security gate is approved

Ready. Next: `autodebug serve --demo`, or `autodebug config vscode --demo` to connect a client.
```

Fix anything marked `✘` before continuing. `doctor` never creates files.

## 3. Connect your AI client

`autodebug config <client> --demo` prints the exact entry for your client. It
uses the absolute path of the Python you installed into, so the client doesn't
depend on your shell's `PATH`. `--demo` arms the synthetic case
`AUTODEBUG-DEMO` each time the client starts the server.

### VS Code (GitHub Copilot)

Run these in the **project folder you open in VS Code**.

Linux / macOS:

```sh
mkdir -p .vscode
autodebug config vscode --demo > .vscode/mcp.json
```

Windows (PowerShell):

```powershell
mkdir .vscode                                         # skip if it exists
py -m autodebug config vscode --demo | Set-Clipboard
code .vscode\mcp.json                                 # paste, then save
```

Copying and pasting avoids a Windows PowerShell 5.1 trap: `>` saves files as
UTF-16, which VS Code may not read as JSON. In PowerShell 7 (`pwsh`), `>` saves
UTF-8 and the Linux/macOS form works as-is.

If `.vscode/mcp.json` already exists, merge the `autodebug` entry into its
`servers` object instead of overwriting the file. Then, in VS Code:

1. Command Palette → **MCP: List Servers** → `autodebug` → **Start Server**.
2. Open Copilot Chat in **Agent** mode and check the tools list for the
   `autodebug_*` tools.

### Claude Code

```sh
autodebug config claude-code --demo   # prints a `claude mcp add ...` command
```

Run the printed command in your project folder, then check with
`claude mcp list` (or `/mcp` inside a session).

### Claude Desktop

```sh
autodebug config claude-desktop --demo
```

Merge the output into `claude_desktop_config.json` (Settings → Developer → Edit
Config), then quit and restart Claude Desktop.

### Cursor

```sh
autodebug config cursor --demo > .cursor/mcp.json
```

Or merge it into `~/.cursor/mcp.json` to use it in every project.

## 4. Try the demo investigation

Ask your AI client, for example:

> Use the autodebug tools. Show the status of case AUTODEBUG-DEMO, wait for the
> stop, then read the stack and the variables `local_var` and `password`. Step
> over once, then complete the case as inconclusive.

What happens behind the scenes:

| Step | Tool | You should see |
|---|---|---|
| Status | `autodebug_case_status` | State `paused`, one bound breakpoint at `/synthetic/demo.py:7` |
| Wait | `autodebug_wait_for_stop` | Stop confirmed (the demo recorded it at startup as `E0001`) |
| Stack | `autodebug_get_stack` | Up to three synthetic frames |
| Variables | `autodebug_get_variables` | `local_var = 42`; `password = ***REDACTED***` |
| Step | `autodebug_step` | `steps_taken: 1` (the demo allows 5) |
| Finish | `autodebug_complete_case` | Paths to `case.json`, `events.jsonl` and `report.md` |

The demo approval lasts 30 minutes from server start. After that, restart the
server (VS Code: **MCP: List Servers** → **Restart**).

Without `--demo`, the AI client can create cases and stage plans, but every
debugger action is refused with `NOT_APPROVED`: no tool can approve a plan.

## 5. Find the evidence

Each server start writes to a new private folder:

```text
<evidence base>\run-20261024T101500Z-a1b2c3\AUTODEBUG-DEMO\
  events.jsonl   one redacted observation per line (E0001, E0002, ...)
  case.json      final case state
  report.md      root-cause report citing evidence IDs
```

The default base is `%LOCALAPPDATA%\autodebug` on Windows,
`~/Library/Application Support/autodebug` on macOS and
`~/.local/state/autodebug` on Linux (or `$XDG_STATE_HOME/autodebug`). Change
it with `--evidence-dir DIR` or `AUTODEBUG_EVIDENCE_DIR`; it must be outside the
AutoDebug checkout and private to you.

## Connecting a real IDE debugger

Connection (2) is not built yet. For VS Code it needs all of:

1. The **Microsoft DebugMCP** extension installed, with Autodesk approval.
2. A real `DebugMCPClient` in AutoDebug that talks to that extension (today only
   a mock exists; see [ide-integrations.md](ide-integrations.md)).
3. The **T05 security gate**: a trusted way for you, not the AI, to approve a
   plan, replacing the demo's built-in approval
   ([security-gate-closure-proposal.md](security-gate-closure-proposal.md)).

Until then, `autodebug doctor` reports every IDE adapter as "mock-only".

## Troubleshooting

| Problem | Fix |
|---|---|
| The client doesn't list AutoDebug | Re-run `autodebug config ...` from the environment where AutoDebug is installed, so the absolute Python path is correct, then restart the server or client. |
| Where are the server's messages? | AutoDebug logs only to stderr. VS Code: **MCP: List Servers** → `autodebug` → **Show Output**. Claude Desktop: `mcp-server-autodebug.log` in its logs folder. |
| `serve` waits and prints nothing | That is normal: it waits for an MCP client on stdin. Press Ctrl+C. |
| `APPROVAL_EXPIRED` | The 30-minute demo approval ended; restart the server. |
| `NOT_APPROVED` | Expected without `--demo`; real approvals don't exist yet. |
| `evidence directory must be outside the AutoDebug checkout` | Choose a folder outside the repository. |

## Command reference

| Command | Purpose |
|---|---|
| `autodebug serve [--demo] [--evidence-dir DIR] [--log-level LEVEL]` | Run the MCP stdio server (clients run this for you) |
| `autodebug doctor [--evidence-dir DIR] [--json]` | Check the machine; exit 0 when ready |
| `autodebug config {vscode,claude-code,claude-desktop,cursor} [--demo] [--evidence-dir DIR] [--name NAME]` | Print client configuration |
| `autodebug --version` / `autodebug --help` | Version and help |

`python -m autodebug ...` works the same without installing the command.
