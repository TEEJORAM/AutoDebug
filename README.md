<p align="center">
  <img src="https://autodebug-tool.github.io/logo.svg" width="96" height="96" alt="Autodebug logo">
</p>

<h1 align="center">Autodebug</h1>

Autodebug lets an AI agent debug and find the real root cause of a bug in your
IDE's debugger, from what the program actually does, not from assumptions the
agent makes by reading the code. Then it writes a report with the actual correct
fix. Nothing runs until you click **Approve**.

- **IDEs:** VS Code, Cursor, Visual Studio 2022 and 2026
- **Agents:** Cursor's agent, Claude Code, GitHub Copilot, and any agent with MCP or a terminal
- **Documentation:** [autodebug-tool.github.io](https://autodebug-tool.github.io/), with step-by-step guides for each IDE and five real case studies

## Install

You need Python 3.11 or newer. If you use Visual Studio, close it first.

Windows (PowerShell):

```powershell
py -m pip install --upgrade autodebug
py -m autodebug setup
```

macOS:

```sh
brew install pipx
pipx ensurepath
pipx install autodebug
autodebug setup
```

Linux:

```sh
sudo apt install pipx
pipx ensurepath
pipx install autodebug
autodebug setup
```

`autodebug setup` connects every IDE it finds and prints the steps left for you.
`autodebug doctor` checks the whole setup. To update, run setup again.

## Use

Open your project in the IDE and ask the agent, for example:

> Use the autodebug tools in Visual Studio with "geometry (Debug|x64)". Stop at
> geometry.cpp line 16, trace total, and write a report.

The IDE shows the **Approve** dialog with the build, the program and the
breakpoints. After you approve, the agent builds, runs, steps and reads the real
values. It writes the report to `autodebug-reports/` in your project.

Try it first on `examples/AutoDebugDemo`.

## Safe by design

- A chat message is never an approval. Only your click on **Approve** starts a session.
- The agent cannot evaluate code or change variables. Conditions and log points only read values.
- Secret-looking values are hidden. Autodebug listens on 127.0.0.1 only, with a token, and collects no data.

## Develop

```sh
PYTHONPATH=src python -m unittest discover -s tests
```

The logic is Python (`src/autodebug`). The IDE extensions are thin relays: JavaScript
for VS Code and Cursor, C# for Visual Studio. How it works: `docs/design.md`. The rules
for contributors: `CLAUDE.md`. Released under the MIT License.
