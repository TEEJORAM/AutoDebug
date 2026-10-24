"""Pasteable setup text shared by `autodebug guide` and the static site.

The site is `site/index.html`. Tests require every string in
`SITE_MUST_CONTAIN` to appear there so the page cannot drift from these
commands.
"""

from __future__ import annotations

GUIDE_URL = "https://teejoram.github.io/AutoDebug/"

SITE_MUST_CONTAIN = (
    "https://github.com/TEEJORAM/AutoDebug.git",
    "py -m pip install -e .",
    "python3 -m venv .venv",
    "source .venv/bin/activate",
    "pip install -e .",
    "py -m autodebug doctor",
    "autodebug doctor",
    "py -m autodebug config vscode --demo --write",
    "autodebug config vscode --demo --write",
    "py -m autodebug config cursor --demo --write",
    "autodebug config cursor --demo --write",
    "py -m autodebug config claude-desktop --demo --write",
    "autodebug config claude-desktop --demo --write",
    "py -m autodebug config claude-code --demo",
    "autodebug config claude-code --demo",
    "AUTODEBUG-DEMO",
    "local_var",
    "password",
    "%LOCALAPPDATA%\\autodebug",
    "~/Library/Application Support/autodebug",
    "~/.local/state/autodebug",
    "Real debugger control is disabled",
    "VS Code",
    "Cursor",
    "CLion",
    "Visual Studio",
    "Xcode",
    "Windows",
    "macOS",
    "Linux",
    "examples/AutoDebugDemo",
    "geometry.py",
    "T05",
    "does not write CLion, Visual Studio or Xcode",
)

_PROMPT = (
    "Use the autodebug tools to investigate case AUTODEBUG-DEMO: show its "
    "status, the stack, and the variables local_var and password."
)


def render_guide(system: str, invocation: str) -> str:
    """Plain-text steps for `system` (`Windows`, `Darwin`, or anything else)."""
    windows = system == "Windows"
    install = "py -m pip install -e ." if windows else "pip install -e ."
    evidence = (
        "%LOCALAPPDATA%\\autodebug" if windows
        else "~/Library/Application Support/autodebug" if system == "Darwin"
        else "~/.local/state/autodebug"
    )
    desktop = (
        f"{invocation} config claude-desktop --demo --write"
        if system != "Linux"
        else "Claude Desktop has no known configuration path on Linux; use VS Code, Cursor or Claude Code."
    )
    return "\n".join((
        f"AutoDebug guide",
        f"Full steps (GitHub Pages): {GUIDE_URL}",
        "Open site/index.html in this repository if that site is not published yet.",
        "",
        "Real debugger control is disabled until the T05 security gate is approved.",
        "The commands below connect an AI client to the synthetic demo debugger.",
        f"This machine: {system}. Evidence folder: {evidence}",
        "",
        "1. Install once, from the AutoDebug folder",
        f"   {install}",
        "",
        "2. Check this machine",
        f"   {invocation} doctor",
        "",
        "3. Connect one AI client (replace PROJECT_FOLDER)",
        f"   VS Code   {invocation} config vscode --demo --write PROJECT_FOLDER",
        f"   Cursor    {invocation} config cursor --demo --write PROJECT_FOLDER",
        f"   Desktop   {desktop}",
        f"   Claude Code prints a command: {invocation} config claude-code --demo",
        "",
        "4. Ask the client",
        f"   {_PROMPT}",
        "",
        "autodebug config does not write CLion, Visual Studio or Xcode files.",
        "Use VS Code or Cursor as the AI client on every OS.",
        "You can still debug examples/AutoDebugDemo by hand in those IDEs;",
        "AutoDebug will not control their debuggers.",
        "",
    ))
