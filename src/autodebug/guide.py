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
    "py -m autodebug bridge install vscode",
    "autodebug bridge install vscode",
    "py -m autodebug config vscode --write examples\\AutoDebugDemo",
    "autodebug config vscode --write examples/AutoDebugDemo",
    "py -m autodebug config cursor --write",
    "py -m autodebug config vscode --demo --write",
    "autodebug config vscode --demo --write",
    "py -m autodebug config claude-desktop --demo --write",
    "autodebug config claude-code --demo",
    "Help to debug AutoDebugDemo",
    "click Approve",
    "AUTODEBUG-DEMO",
    "local_var",
    "password",
    "%LOCALAPPDATA%\\autodebug",
    "~/Library/Application Support/autodebug",
    "~/.local/state/autodebug",
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
    "Help to debug AutoDebugDemo using the autodebug tools. Bug: moving a shape changes its area "
    "(the \"Debug tests\" launch configuration shows it). Choose breakpoints in the code that computes "
    "the area, request my approval, then step through it to find the cause. Finish the case with the "
    "problem, root cause, solution and evidence, and tell me where the report is."
)
_DEMO_PROMPT = (
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
    sep = "\\" if windows else "/"
    return "\n".join((
        "AutoDebug guide",
        f"Full steps (GitHub Pages): {GUIDE_URL}",
        "Open site/index.html in this repository if that site is not published yet.",
        "",
        "AutoDebug drives the debugger in VS Code and Cursor through the AutoDebug Bridge.",
        "Nothing runs until you click Approve in the IDE.",
        f"This machine: {system}. Evidence folder: {evidence}",
        "",
        "1. Install once, from the AutoDebug folder",
        f"   {install}",
        "",
        "2. Check this machine",
        f"   {invocation} doctor",
        "",
        "3. Install the AutoDebug Bridge (then Developer: Reload Window in VS Code)",
        f"   {invocation} bridge install vscode     (Cursor: bridge install cursor)",
        "",
        "4. Connect a project (the sample first)",
        f"   {invocation} config vscode --write examples{sep}AutoDebugDemo",
        "",
        "5. Open that folder in VS Code, start the autodebug MCP server, and ask in Agent mode",
        f"   {_PROMPT}",
        "   Then click Approve in the dialog. The report goes to autodebug-reports/.",
        "",
        "Practice debugger instead (no extension, no approval):",
        f"   VS Code   {invocation} config vscode --demo --write PROJECT_FOLDER",
        f"   Cursor    {invocation} config cursor --demo --write PROJECT_FOLDER",
        f"   Desktop   {desktop}",
        f"   Claude Code prints a command: {invocation} config claude-code --demo",
        f"   Ask: {_DEMO_PROMPT}",
        "",
        "autodebug config does not write CLion, Visual Studio or Xcode files, and AutoDebug",
        "does not drive their debuggers yet.",
        "",
    ))
