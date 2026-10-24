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

Requirements: **Python 3.11 or newer** and **Git**. There are no dependencies
to download. Run these once, in a terminal opened where you keep projects.

Windows (PowerShell):

```powershell
git clone https://github.com/TEEJORAM/AutoDebug.git
cd AutoDebug
py -m pip install -e .
```

macOS / Linux:

```sh
git clone https://github.com/TEEJORAM/AutoDebug.git
cd AutoDebug
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Windows this guide uses `py -m autodebug`, which works even when Python's
`Scripts` folder is not on your PATH. On macOS/Linux, `autodebug` works while
the `.venv` is active (run `source .venv/bin/activate` in new terminals).

## 2. Check your machine

Windows (PowerShell):

```powershell
py -m autodebug doctor
```

macOS / Linux:

```sh
autodebug doctor
```

Example output (Windows):

```text
AutoDebug doctor (autodebug 0.1.0)

  ✔ Python            3.14.8
  · Platform          Windows 11
  ✔ Evidence storage  supported
  ✔ Evidence folder   C:\Users\you\AppData\Local\autodebug (created on first run)
  ✔ Demo debugger     synthetic, ready for `serve --demo`
  · IDE adapters      vscode, cursor, clion, visual_studio target this OS; mock-only, no native debugger client yet
  · Real debuggers    disabled until the T05 security gate is approved

Ready. Next: `py -m autodebug config vscode --demo --write PROJECT_FOLDER` to connect VS Code.
```

Fix anything marked `✘` before continuing. `doctor` never creates files.

## 3. Connect your AI client

Run these from the AutoDebug folder. `config ... --write` adds AutoDebug to the
client's configuration file, keeps any other servers in it, and saves it as
UTF-8. The entry uses the absolute path of your Python, so the client does not
depend on `PATH`. `--demo` arms the synthetic case `AUTODEBUG-DEMO` each time
the client starts the server.

Without `--write`, `config` only prints the entry so you can add it by hand.

### VS Code (GitHub Copilot)

Replace the folder with the project you open in VS Code; AutoDebug writes
`.vscode/mcp.json` there.

Windows (PowerShell):

```powershell
py -m autodebug config vscode --demo --write D:\Projects\MyApp
```

macOS / Linux:

```sh
autodebug config vscode --demo --write ~/Projects/MyApp
```

Then, in VS Code with that folder open:

1. Command Palette → **MCP: List Servers** → `autodebug` → **Start Server**.
2. Open Copilot Chat in **Agent** mode and check the tools list for the
   `autodebug_*` tools.

### Cursor

Windows (PowerShell):

```powershell
py -m autodebug config cursor --demo --write D:\Projects\MyApp
```

macOS / Linux:

```sh
autodebug config cursor --demo --write ~/Projects/MyApp
```

This writes `.cursor/mcp.json` in that project. Then open Cursor Settings and
enable `autodebug` under MCP.

### Claude Desktop

Windows (PowerShell):

```powershell
py -m autodebug config claude-desktop --demo --write
```

macOS:

```sh
autodebug config claude-desktop --demo --write
```

This updates `claude_desktop_config.json` (`%APPDATA%\Claude\` on Windows,
`~/Library/Application Support/Claude/` on macOS). Quit and restart Claude
Desktop.

### Claude Code

Windows (PowerShell):

```powershell
py -m autodebug config claude-code --demo
```

macOS / Linux:

```sh
autodebug config claude-code --demo
```

This prints a `claude mcp add ...` command. Run that command in your project
folder, then check with `claude mcp list` (or `/mcp` inside a session).

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

## Practise on a real bug

[examples/AutoDebugDemo](../examples/AutoDebugDemo/README.md) is a small Python
and C++ app with one deliberate bug. Debug it yourself in VS Code, Visual Studio
or CLion now; its `autodebug-plan.json` is the plan AutoDebug will use once it
can drive the VS Code debugger.

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
| The client doesn't list AutoDebug | Re-run the `config ... --write` command from the AutoDebug folder (macOS/Linux: with `.venv` active), then restart the server or client. |
| `... is not plain JSON` | Your existing config file has comments; add the entry printed by `config` (without `--write`) by hand. |
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
| `autodebug config {vscode,claude-code,claude-desktop,cursor} [--demo] [--write [PROJECT_FOLDER]] [--evidence-dir DIR] [--name NAME]` | Print client configuration, or write it into the client's config file |
| `autodebug --version` / `autodebug --help` | Version and help |

`python -m autodebug ...` works the same without installing the command.
