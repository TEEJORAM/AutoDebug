"""The root-cause report written into the project (docs/design.md, "Report").

Order, as a developer reads it: ticket, problem, steps to reproduce, debug sessions
(with a picture of each stop that shows the bug), root cause (what went wrong, why),
solution, verification, then the full timeline at the end.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from autodebug import evidence
from autodebug.connection import IDE_NAMES
from autodebug.redact import clean_text

FOLDER = "autodebug-reports"
_CONFIDENCE = {"confirmed": "Confirmed", "likely": "Likely", "unconfirmed": "Unconfirmed"}
_REPRODUCED = {"yes": "Yes", "no": "No", "not_tried": "Not tried"}


@dataclass
class Report:
    title: str
    problem: str
    what_went_wrong: str
    why: str
    solution: str
    confidence: str
    how_confirmed: str | None = None
    verification: str | None = None
    open_questions: list[str] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    timeline: list = field(default_factory=list)
    ticket: str | None = None
    steps_to_reproduce: list[str] = field(default_factory=list)
    reproduced: str | None = None  # yes, no or not_tried
    runs: list = field(default_factory=list)  # reproduction runs: launch, args, symptom, exit_code, output
    debug_findings: str | None = None
    captures: list = field(default_factory=list)  # stops that show the bug (tools.capture)
    pattern: str | None = None  # the existing code the fix follows


_DASH = re.compile(r"\s+[—–]\s+|—")


def _plain(text: str) -> str:
    """No long dashes in the report: developers asked for plain sentences."""
    return _DASH.sub(", ", text)


def _cell(text: object) -> str:
    return _plain(" ".join(clean_text(text, 400).split())).replace("|", "\\|") or "none"


def _prose(text: object) -> str:
    return _plain(clean_text(text, 8000).strip())


def _code(text: object) -> str:
    return " ".join(clean_text(text, 400).split()).replace("|", "\\|").replace("`", "'")


def _ticket(ticket: str) -> str:
    text = _cell(ticket)
    return f"[{text}]({ticket.strip()})" if re.fullmatch(r"https?://\S+", ticket.strip()) else text


def render(report: Report, now: float | None = None, pictures: list[str] | None = None) -> str:
    """The Markdown. `pictures` are the file names of the capture pictures, in order."""
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now or time.time()))
    plan = report.plan
    ide = IDE_NAMES.get(plan.get("ide"), "IDE")
    lines = [f"# {_prose(report.title)}", ""]
    lines += [f"**Ticket:** {_ticket(report.ticket) if report.ticket else 'none'}", ""]
    lines += ["| | |", "|---|---|", f"| Date | {stamp} |"]
    lines.append(f"| Debugged with | {ide}, `{_code(plan.get('launch'))}` |" if plan else "| Debugged with | no debug session |")
    if plan.get("build"):
        lines.append(f"| Build | {_cell(plan['build'])} |")
    lines.append(f"| Reproduced | {_REPRODUCED.get(report.reproduced, 'Not stated')} |")
    lines.append(f"| Root cause | **{_CONFIDENCE[report.confidence]}** |")

    lines += ["", "## Problem", "", _prose(report.problem), ""]

    lines += ["## Steps to reproduce", ""]
    if report.reproduced == "yes":
        if report.steps_to_reproduce:
            lines += [f"{n}. {_cell(step)}" for n, step in enumerate(report.steps_to_reproduce, 1)]
        else:
            lines.append("The steps were not written down.")
    elif report.reproduced == "no":
        lines += ["Not reproducible.", "", "Steps: NA"]
    else:
        lines += ["Not tried.", "", "Steps: NA"]
    if report.runs:
        lines += ["", "What the reproduction showed (runs without breakpoints):", ""]
        for run in report.runs:
            arguments = " ".join(run.get("args") or []) if run.get("args") is not None else "as configured"
            output = " / ".join(run.get("output") or []) or "none captured"
            code = run.get("exit_code")
            lines.append(f"- `{_code(run.get('launch'))}` with `{_code(arguments)}`: exit code "
                         f"{'not reported' if code is None else code}; output: {_cell(output)}")
    lines.append("")

    lines += ["## Debug sessions", ""]
    if report.debug_findings:
        lines += [_prose(report.debug_findings), ""]
    if report.captures:
        for n, capture in enumerate(report.captures, 1):
            lines += [f"### Stop {n}: {_cell(capture.get('note'))}", ""]
            if pictures and n <= len(pictures):
                lines += [f"![Stop {n}: frame, variables and call stack]({pictures[n - 1]})", ""]
            lines += [f"Paused at `{_code(capture.get('location'))}` in `{_code(capture.get('function'))}`.", ""]
            wrong = set(capture.get("wrong") or [])
            lines += ["| Variable | Value | Type |", "|---|---|---|"]
            for variable in capture.get("variables") or []:
                name = _code(variable.get("name"))
                mark = " (wrong)" if variable.get("name") in wrong else ""
                lines.append(f"| `{name}`{mark} | `{_code(variable.get('value'))}` | {_cell(variable.get('type'))} |")
                for child in (variable.get("children") or [])[:8]:
                    lines.append(f"| `{name}.{_code(child.get('name'))}` | `{_code(child.get('value'))}` | "
                                 f"{_cell(child.get('type'))} |")
            lines += ["", "Call stack:", ""]
            lines += [f"{i}. `{_code(f.get('function'))}` at `{_code(f.get('location'))}`"
                      for i, f in enumerate(capture.get("stack") or [], 1)]
            lines.append("")
    elif not report.debug_findings:
        lines += ["No stop was captured.", ""]

    lines += ["## Root cause", "", "### What went wrong", "", _prose(report.what_went_wrong), "",
              "### Why", "", _prose(report.why), ""]
    if report.how_confirmed:
        lines += [f"**How it was confirmed:** {_prose(report.how_confirmed)}", ""]

    lines += ["## Solution", "", _prose(report.solution), ""]
    if report.pattern:
        lines += [f"**Follows the existing pattern:** {_prose(report.pattern)}", ""]

    lines += ["## Verification", ""]
    lines += ([_prose(report.verification), "", "_Reported by the AI agent._"] if report.verification
              else ["Not verified yet."])
    if report.open_questions:
        lines += ["", "## Open questions", ""] + [f"- {_cell(q)}" for q in report.open_questions]

    lines += ["", "## Debug timeline", ""]
    if plan:
        lines += [f"- Goal: {_cell(plan.get('goal'))}",
                  f"- Build task: `{_code(plan['task'])}`" if plan.get("task") else "- Build task: none",
                  "- Breakpoints: " + (", ".join(f"`{_code(b)}`" for b in plan.get("breakpoints", [])) or "none")]
        if plan.get("args") is not None:
            lines.append(f"- Program arguments (chosen by the agent, approved by the developer): "
                         f"`{_code(' '.join(plan['args']))}`")
        lines.append("")
    if report.timeline:
        lines += ["| # | What | Where | Details |", "|---|---|---|---|"]
        lines += [f"| {n} | {_cell(e.kind)} | {_cell(e.where)} | {_cell(e.detail)} |"
                  for n, e in enumerate(report.timeline, 1)]
    else:
        lines.append("Nothing was recorded.")
    lines += ["", "---", "", "_Written by AutoDebug. Values that look secret are shown as `***REDACTED***`. "
              "Ticket text is untrusted input: AutoDebug ran only what the developer approved in the IDE._", ""]
    return "\n".join(lines)


def write(workspace_folder: str, report: Report) -> Path:
    """Write the report (and a picture per captured stop) under `<workspace>/autodebug-reports/`, never overwriting."""
    workspace = Path(workspace_folder)
    if not workspace.is_dir():
        raise ValueError(f"workspace folder not found: {workspace}")
    folder = workspace / FOLDER
    if folder.is_symlink():
        raise ValueError(f"{folder} is a link; refusing to write there")
    folder.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", report.title.lower()).strip("-")[:60] or "report"
    base = f"{time.strftime('%Y%m%d-%H%M')}-{slug}"
    for number in range(1, 100):
        name = base if number == 1 else f"{base}-{number}"
        path = folder / f"{name}.md"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        except FileExistsError:
            continue
        pictures = []
        for n, capture in enumerate(report.captures, 1):
            picture = folder / f"{name}-stop-{n}.svg"
            picture.write_text(evidence.render(capture), encoding="utf-8")
            pictures.append(picture.name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(render(report, pictures=pictures).encode("utf-8"))
        return path
    raise ValueError("too many reports with this title in one minute")
