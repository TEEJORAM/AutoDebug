"""The root-cause report written into the project (docs/design.md, "Report").

Exactly these sections, in this order: ticket, problem, steps to reproduce, debug
sessions (a screenshot of the IDE at each stop that shows the bug), root cause (what
went wrong, why), solution, and AI usage. No call stacks or variable dumps as text,
and no timeline: developers asked for a report they can read.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from autodebug.connection import IDE_NAMES
from autodebug.redact import clean_text

FOLDER = "autodebug-reports"
_CONFIDENCE = {"confirmed": "Confirmed", "likely": "Likely", "unconfirmed": "Unconfirmed"}
CHARS_PER_TOKEN = 4  # a common rule of thumb for English text and code


@dataclass
class Report:
    title: str
    problem: str
    what_went_wrong: str
    why: str
    solution: str
    confidence: str
    model: str
    how_confirmed: str | None = None
    verification: str | None = None
    fix_verified: bool = False  # the agent applied the fix and saw the bug gone
    plan: dict = field(default_factory=dict)
    ticket: str | None = None
    steps_to_reproduce: list[str] = field(default_factory=list)
    reproduced: str | None = None  # yes, no or not_tried
    runs: list = field(default_factory=list)  # reproduction runs: launch, args, exit_code
    debug_findings: str | None = None
    captures: list = field(default_factory=list)  # stops that show the bug (tools.capture)
    pattern: str | None = None  # the existing code the fix follows
    token_usage: str | None = None  # as the agent's app reports it
    tool_calls: int = 0  # AutoDebug tool calls since the last report
    tool_characters: int = 0  # characters of their arguments and results


_DASH = re.compile(r"\s+[—–]\s+|—")


def _plain(text: str) -> str:
    """No long dashes: developers asked for plain sentences."""
    return _DASH.sub(", ", text)


def _line(text: object, limit: int = 400) -> str:
    return _plain(" ".join(clean_text(text, limit).split()))


def _prose(text: object) -> str:
    return _plain(clean_text(text, 8000).strip())


def _code(text: object) -> str:
    return " ".join(clean_text(text, 400).split()).replace("`", "'")


def _ticket(ticket: str) -> str:
    text = _line(ticket)
    return f"[{text}]({ticket.strip()})" if re.fullmatch(r"https?://\S+", ticket.strip()) else text


def render(report: Report) -> str:
    plan = report.plan
    ide = IDE_NAMES.get(plan.get("ide"), "the IDE")
    lines = [f"# {_prose(report.title)}", "",
             f"**Ticket:** {_ticket(report.ticket) if report.ticket else 'none'}", "",
             "## Problem", "", _prose(report.problem), "",
             "## Steps to reproduce", ""]
    if report.reproduced == "yes":
        lines += ["Reproducible: yes.", ""]
        lines += [f"{n}. {_line(step)}" for n, step in enumerate(report.steps_to_reproduce, 1)]
        for run in report.runs:
            if run.get("exit_code") is not None:
                lines += ["", f"The run without breakpoints ended with exit code {run['exit_code']}."]
    elif report.reproduced == "no":
        lines += ["Not reproducible.", "", "Steps: NA"]
    else:
        lines += ["Not tried.", "", "Steps: NA"]

    lines += ["", "## Debug sessions", ""]
    if plan:
        build = f", {_line(plan['build'])}" if plan.get("build") else ""
        lines += [f"Debugged in {ide} with `{_code(plan.get('launch'))}`{build}.", ""]
    if report.debug_findings:
        lines += [_prose(report.debug_findings), ""]
    for n, capture in enumerate(report.captures, 1):
        lines += [f"### Stop {n}: {_line(capture.get('note'))}", ""]
        if capture.get("screenshot"):
            lines += [f"![Stop {n}: {ide} at {_code(capture.get('location'))}]({capture['screenshot']})", ""]
        else:
            lines += [f"No screenshot: {_line(capture.get('screenshot_note') or 'none was taken')}", ""]

    lines += ["## Root cause", "", "### What went wrong", "", _prose(report.what_went_wrong), "",
              "### Why", "", _prose(report.why), "",
              f"Confidence: {_CONFIDENCE[report.confidence]}."
              + (f" {_line(report.how_confirmed, 1000)}" if report.how_confirmed else ""), ""]

    lines += ["## Solution", "", _prose(report.solution), ""]
    if report.pattern:
        lines += [f"Follows the existing pattern: {_line(report.pattern, 1000)}", ""]
    if report.fix_verified and report.verification:
        lines += [f"Verified: {_line(report.verification, 1000)} (reported by the AI agent)", ""]
    else:
        lines += ["Not verified yet: the fix has not been applied and tested.", ""]

    estimate = round(report.tool_characters / CHARS_PER_TOKEN)
    lines += ["## AI usage", "",
              f"- Model: {_line(report.model, 200)} (as the agent reported it)",
              f"- Tokens: {_line(report.token_usage, 300)}" if report.token_usage
              else "- Tokens: not reported by the agent. Your AI app's usage page shows the exact count.",
              f"- AutoDebug: {report.tool_calls} tool calls, about {estimate:,} tokens of tool input and output "
              f"(estimated at {CHARS_PER_TOKEN} characters per token, part of the total above).",
              ""]
    return "\n".join(lines)


def write(workspace_folder: str, report: Report) -> Path:
    """Write the report under `<workspace>/autodebug-reports/`, never overwriting. Screenshots are already in
    `autodebug-reports/screenshots/`, saved by the IDE at each capture."""
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
