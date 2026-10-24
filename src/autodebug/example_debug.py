"""Local trace of the bundled geometry sample.

This runs `polygon_area` inside the AutoDebug process and records each stop on
the area line. It does not set a breakpoint in an IDE, build a C++ target, or
start Debug in VS Code, Cursor, CLion, Visual Studio, or Xcode.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

CASE_ID = "AUTODEBUG-EXAMPLE"
_MAX_BYTES = 16 * 1024
_MAX_STOPS = 64
_ALLOWED_CALLS = frozenset({"len", "abs", "range"})
_ALLOWED_NODES = frozenset({
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.AnnAssign, ast.Assign,
    ast.Name, ast.Load, ast.Store, ast.Subscript, ast.BinOp, ast.Add, ast.Sub,
    ast.Mult, ast.Div, ast.Mod, ast.Return, ast.For, ast.If, ast.Compare, ast.Eq,
    ast.NotEq, ast.Call, ast.ListComp, ast.comprehension, ast.Tuple, ast.Constant,
    ast.Expr, ast.AugAssign, ast.UnaryOp, ast.USub, ast.List, ast.keyword,
})
_SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]


class ExampleDebugError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _locate(root: Path) -> Path:
    root = root.resolve()
    candidates = (root / "geometry.py", root / "examples" / "AutoDebugDemo" / "geometry.py")
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        if resolved.name == "geometry.py" and resolved.is_relative_to(root):
            return resolved
    raise ExampleDebugError(
        "geometry.py was not found. Open the AutoDebug folder or examples/AutoDebugDemo and run this again."
    )


def _validated_source(path: Path) -> tuple[str, int]:
    raw = path.read_bytes()
    if len(raw) > _MAX_BYTES:
        raise ExampleDebugError("geometry.py is larger than 16 KiB; this trace will not run it")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExampleDebugError("geometry.py is not UTF-8") from exc
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ExampleDebugError(f"geometry.py could not be parsed: {exc.msg}") from exc
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            raise ExampleDebugError(f"geometry.py uses {type(node).__name__}, which this trace will not run")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS
        ):
            raise ExampleDebugError("geometry.py calls a function this trace will not run")
    line = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "polygon_area":
            for child in ast.walk(node):
                if isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name) and child.target.id == "total":
                    line = child.lineno
    if line is None:
        raise ExampleDebugError("polygon_area with a total += line was not found")
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if "move" not in names:
        raise ExampleDebugError("move was not found in geometry.py")
    return source, line


def _trace(path: Path, source: str, line: int) -> tuple[list[dict], float, float]:
    namespace: dict = {"__name__": "autodebug_example_geometry"}
    exec(compile(source, str(path), "exec"), namespace, namespace)
    polygon_area = namespace["polygon_area"]
    move = namespace["move"]
    state: dict = {"call": -1, "stops": []}

    def tracer(frame, event, _arg):
        if frame.f_code.co_filename != str(path):
            return tracer
        if frame.f_code.co_name != "polygon_area":
            return tracer
        if event == "call":
            state["call"] += 1
        elif event == "line" and frame.f_lineno == line:
            if len(state["stops"]) >= _MAX_STOPS:
                raise ExampleDebugError("the area line was hit more times than this trace allows")
            points = frame.f_locals.get("points")
            state["stops"].append({
                "call": state["call"],
                "line": frame.f_lineno,
                "i": frame.f_locals.get("i"),
                "points_len": len(points) if isinstance(points, list) else None,
                "total": frame.f_locals.get("total"),
            })
        return tracer

    sys.settrace(tracer)
    try:
        before = polygon_area(list(_SQUARE))
        after = polygon_area(move(list(_SQUARE), 2, 1))
    finally:
        sys.settrace(None)
    return state["stops"], before, after


def _conclusion(stops: list[dict], before: float, after: float) -> tuple[str, str, str]:
    first = [stop for stop in stops if stop["call"] == 0]
    indexes = [stop["i"] for stop in first]
    count = first[0]["points_len"] if first else None
    if count == 4 and indexes == [0, 1, 2] and before == 1.0 and after == 2.0:
        cause = (
            "The area line ran 3 times for a 4-point square, so i was only 0, 1, and 2. "
            "The edge from the last point back to the first never ran. At the origin that "
            "missing term is 0, so the area stays 1. After a move of (2, 1) the same missing "
            "term is no longer 0, and the area becomes 2."
        )
        fix = (
            "Walk every edge, including the edge that returns to the first point:\n\n"
            "```python\n"
            "n = len(points)\n"
            "for i in range(n):\n"
            "    x1, y1 = points[i]\n"
            "    x2, y2 = points[(i + 1) % n]\n"
            "    total += x1 * y2 - x2 * y1\n"
            "```"
        )
        return "confirmed", cause, fix
    if count == 4 and indexes == [0, 1, 2, 3] and before == after == 1.0:
        return (
            "confirmed",
            "The area line ran once per point, including i = 3. That visit adds the edge from "
            "the last point back to the first. The unit square area stayed 1 after a move of (2, 1).",
            "No code change is required for this area check.",
        )
    return (
        "inconclusive",
        f"The trace recorded indexes {indexes} and areas {before} then {after}. "
        "That does not match the known missing-edge pattern or the fixed loop.",
        "Inspect the recorded stops before changing geometry.py.",
    )


def _markdown(path: Path, line: int, stops: list[dict], before: float, after: float, confidence: str, cause: str, fix: str) -> str:
    rows = "\n".join(
        f"| {stop['call'] + 1} | {stop['i']} | {stop['points_len']} | {stop['total']} |"
        for stop in stops
    )
    return (
        "# AutoDebug example investigation\n\n"
        "Program: `geometry.py`, function `polygon_area`, unit square `(0, 0), (1, 0), (1, 1), (0, 1)`, "
        "then the same square moved by `(2, 1)`.\n\n"
        "## IDE actions\n\n"
        "| Step | Result |\n"
        "|---|---|\n"
        "| Put a breakpoint in VS Code, Cursor, CLion, Visual Studio, or Xcode | Not done. No IDE debugger is connected. |\n"
        "| Build, compile, and press Debug | Not done. Python loaded this file in the AutoDebug process. There is no compile step. |\n"
        f"| Stop on the area line and record values | Done. Local trace stopped at `{path.name}:{line}` before `total +=` ran. |\n"
        "| Write this summary | Done. |\n\n"
        f"## Stops at line {line}\n\n"
        "Values are what a debugger would show on that line, before the addition.\n\n"
        "| Call | i | len(points) | total |\n"
        "|---|---|---|---|\n"
        f"{rows}\n\n"
        f"## Areas\n\n"
        f"- Before the move: {before}\n"
        f"- After the move: {after}\n\n"
        f"## Root cause\n\n"
        f"Confidence: {confidence}.\n\n"
        f"{cause}\n\n"
        f"## Solution\n\n"
        f"{fix}\n"
    )


def debug_example(root: Path) -> dict:
    """Trace the sample and write `investigation.md` beside `geometry.py`."""
    try:
        path = _locate(root)
        source, line = _validated_source(path)
        stops, before, after = _trace(path, source, line)
        confidence, cause, fix = _conclusion(stops, before, after)
        markdown = _markdown(path, line, stops, before, after, confidence, cause, fix)
        report = path.with_name("investigation.md")
        temporary = report.with_name(f".{report.name}.tmp")
        temporary.write_text(markdown, encoding="utf-8")
        temporary.replace(report)
    except ExampleDebugError as exc:
        return {"ok": False, "case_id": CASE_ID, "error": {
            "code": "BACKEND_UNAVAILABLE", "message": exc.message, "recoverable": True,
        }}
    return {"ok": True, "case_id": CASE_ID, "result": {
        "ide_debugger": "not_connected",
        "breakpoint": {"file": path.name, "line": line},
        "stops": stops,
        "area_before": before,
        "area_after": after,
        "confidence": confidence,
        "root_cause": cause,
        "report_path": str(report),
    }}
