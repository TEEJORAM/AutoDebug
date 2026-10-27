"""A picture of the problematic stop for the report: where the program was, the call stack and the
variables that show the bug (docs/design.md, "Report").

It is drawn from what the debugger returned, not a screen capture: other windows, other
variables and secrets on the screen never end up in the report, and values are already
redacted. Plain SVG, so it needs no library and shows on GitHub and in any browser.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

WIDTH = 820
ROW = 24
FONT = "Consolas, Menlo, 'DejaVu Sans Mono', monospace"
COLORS = {"ink": "#1f2328", "dim": "#59636e", "rule": "#d1d9e0", "head": "#f6f8fa", "here": "#fff5b1",
          "wrong": "#ffebe9", "wrong_ink": "#cf222e", "frame": "#ffffff"}


def _cut(text: object, limit: int) -> str:
    value = " ".join(str(text if text is not None else "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _rows(variables: list[dict], level: int = 0) -> list[tuple[int, dict]]:
    rows = []
    for variable in variables:
        rows.append((level, variable))
        if level < 1:
            rows += _rows(variable.get("children") or [], level + 1)[:8]
    return rows


def render(capture: dict) -> str:
    """The SVG for one capture: {location, function, note, variables [{name, value, type, children}],
    wrong [names], stack [{function, location}]}."""
    wrong = set(capture.get("wrong") or [])
    rows = _rows(capture.get("variables") or [])[:24]
    stack = (capture.get("stack") or [])[:8]
    height = 56 + 30 + ROW * (len(rows) + 1) + 30 + ROW * max(len(stack), 1) + 24
    c = COLORS
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" '
           f'font-family="{FONT}" font-size="13">',
           f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="6" fill="{c["frame"]}" stroke="{c["rule"]}"/>',
           f'<rect x="1" y="1" width="{WIDTH - 2}" height="44" rx="6" fill="{c["head"]}"/>',
           f'<circle cx="22" cy="23" r="6" fill="{c["wrong_ink"]}"/>',
           f'<text x="38" y="20" fill="{c["ink"]}" font-weight="bold">{escape(_cut("Paused at " + str(capture.get("location") or "(no source)"), 90))}</text>',
           f'<text x="38" y="37" fill="{c["dim"]}">{escape(_cut(capture.get("function") or "", 96))}</text>']
    y = 56
    if capture.get("note"):
        out.append(f'<text x="16" y="{y + 14}" fill="{c["ink"]}">{escape(_cut(capture["note"], 104))}</text>')
    y += 30
    # Variables: name, value, type; the values that are wrong are marked.
    out += [f'<text x="16" y="{y + 16}" fill="{c["dim"]}" font-weight="bold">Variable</text>',
            f'<text x="250" y="{y + 16}" fill="{c["dim"]}" font-weight="bold">Value</text>',
            f'<text x="640" y="{y + 16}" fill="{c["dim"]}" font-weight="bold">Type</text>',
            f'<line x1="12" y1="{y + ROW}" x2="{WIDTH - 12}" y2="{y + ROW}" stroke="{c["rule"]}"/>']
    y += ROW
    for level, variable in rows:
        name = str(variable.get("name") or "")
        bad = name in wrong
        if bad:
            out.append(f'<rect x="12" y="{y + 2}" width="{WIDTH - 24}" height="{ROW - 4}" rx="3" fill="{c["wrong"]}"/>')
            out.append(f'<text x="18" y="{y + 17}" fill="{c["wrong_ink"]}" font-weight="bold">!</text>')
        ink = c["wrong_ink"] if bad else c["ink"]
        weight = ' font-weight="bold"' if bad else ""
        out += [f'<text x="{30 + 16 * level}" y="{y + 17}" fill="{ink}"{weight}>'
                f'{escape(_cut(name, 26 - 2 * level))}</text>',
                f'<text x="250" y="{y + 17}" fill="{ink}">{escape(_cut(variable.get("value"), 52))}</text>',
                f'<text x="640" y="{y + 17}" fill="{c["dim"]}">{escape(_cut(variable.get("type"), 22))}</text>']
        y += ROW
    y += 8
    out += [f'<text x="16" y="{y + 16}" fill="{c["dim"]}" font-weight="bold">Call stack</text>',
            f'<line x1="12" y1="{y + 22}" x2="{WIDTH - 12}" y2="{y + 22}" stroke="{c["rule"]}"/>']
    y += 24
    for index, frame in enumerate(stack or [{"function": "(not captured)", "location": ""}]):
        if index == 0:
            out.append(f'<rect x="12" y="{y + 2}" width="{WIDTH - 24}" height="{ROW - 4}" rx="3" fill="{c["here"]}"/>')
        out += [f'<text x="30" y="{y + 17}" fill="{c["ink"]}">{escape(_cut(frame.get("function"), 46))}</text>',
                f'<text x="440" y="{y + 17}" fill="{c["dim"]}">{escape(_cut(frame.get("location"), 48))}</text>']
        y += ROW
    out.append("</svg>")
    return "\n".join(out) + "\n"
