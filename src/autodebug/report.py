"""The root-cause report written into the project (docs/design.md, "Report")."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from autodebug.redact import clean_text

FOLDER = "autodebug-reports"
_CONFIDENCE = {"confirmed": "Confirmed", "likely": "Likely", "unconfirmed": "Unconfirmed"}


@dataclass
class Report:
    title: str
    problem: str
    root_cause: str
    solution: str
    confidence: str
    how_confirmed: str | None = None
    verification: str | None = None
    open_questions: list[str] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    timeline: list = field(default_factory=list)


def _cell(text: object) -> str:
    return " ".join(clean_text(text, 400).split()).replace("|", "\\|") or "—"


def _prose(text: object) -> str:
    return clean_text(text, 8000).strip()


def render(report: Report, now: float | None = None) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now or time.time()))
    plan = report.plan
    ide = {"cursor": "Cursor", "vscode": "VS Code"}.get(plan.get("ide"), "IDE")
    lines = [
        f"# {_prose(report.title)}",
        "",
        "| | |",
        "|---|---|",
        f"| Date | {stamp} |",
        f"| Root cause | **{_CONFIDENCE[report.confidence]}** |",
        f"| Debugged with | {ide}, launch configuration `{_cell(plan.get('launch'))}` |" if plan else "| Debugged with | — |",
        "",
        "## Problem",
        "",
        _prose(report.problem),
        "",
        "## How it was debugged",
        "",
    ]
    if plan:
        lines += [f"- Goal: {_cell(plan.get('goal'))}",
                  f"- Build task: `{_cell(plan['task'])}`" if plan.get("task") else "- Build task: none",
                  "- Breakpoints: " + (", ".join(f"`{_cell(b)}`" for b in plan.get("breakpoints", [])) or "none")]
    else:
        lines.append("- No debug session was recorded.")
    lines += ["", "### Timeline", ""]
    if report.timeline:
        lines += ["| # | What | Where | Details |", "|---|---|---|---|"]
        lines += [f"| {n} | {_cell(e.kind)} | {_cell(e.where)} | {_cell(e.detail)} |"
                  for n, e in enumerate(report.timeline, 1)]
    else:
        lines.append("_Nothing was recorded._")
    lines += ["", "## Root cause", "", _prose(report.root_cause)]
    if report.how_confirmed:
        lines += ["", f"**How it was confirmed:** {_prose(report.how_confirmed)}"]
    lines += ["", "## Solution", "", _prose(report.solution), "", "## Verification", ""]
    lines += ([_prose(report.verification), "", "_Reported by the AI agent._"] if report.verification
              else ["_Not verified yet._"])
    if report.open_questions:
        lines += ["", "## Open questions", ""] + [f"- {_cell(q)}" for q in report.open_questions]
    lines += ["", "---", "", "_Written by AutoDebug. Secret-looking values are shown as `***REDACTED***`._", ""]
    return "\n".join(lines)


def write(workspace_folder: str, report: Report) -> Path:
    """Write the report under `<workspace>/autodebug-reports/`, never overwriting."""
    workspace = Path(workspace_folder)
    if not workspace.is_dir():
        raise ValueError(f"workspace folder not found: {workspace}")
    folder = workspace / FOLDER
    if folder.is_symlink():
        raise ValueError(f"{folder} is a link; refusing to write there")
    folder.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", report.title.lower()).strip("-")[:60] or "report"
    base = f"{time.strftime('%Y%m%d-%H%M')}-{slug}"
    text = render(report).encode("utf-8")
    for number in range(1, 100):
        path = folder / (f"{base}.md" if number == 1 else f"{base}-{number}.md")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(text)
        return path
    raise ValueError("too many reports with this title in one minute")
