"""Which build a launch configuration runs: Debug, RelWithDebInfo, Release, ... (docs/design.md, "Build type").

The agent needs this before it debugs: an optimized build can show variables as "optimized away" and make steps
jump, and a build without debug symbols cannot bind breakpoints. The type is read, in order, from Visual Studio's
active configuration, the program's path (CMake's multi-config folders, Cargo's target/debug, .NET's bin/Release),
and the CMakeCache.txt of a single-config CMake build. Nothing here runs the build or the program.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: Known build types: (optimized, debug symbols) with the compilers' default flags (CMake, MSBuild, Cargo, .NET).
KNOWN = {
    "debug": ("Debug", False, True),
    "relwithdebinfo": ("RelWithDebInfo", True, True),
    "release": ("Release", True, False),
    "minsizerel": ("MinSizeRel", True, False),
}
#: Debuggers of interpreted languages: there is no build type.
INTERPRETED = {"debugpy", "python", "node", "pwa-node", "php", "ruby", "rdbg", "bashdb"}

NOTES = {
    "Debug": None,
    "RelWithDebInfo": ("Optimized build with debug symbols: some variables may show as optimized away and steps can "
                       "jump between lines. For exact values, ask the developer for a Debug build."),
    "Release": ("Optimized build, usually without debug symbols: breakpoints may not bind and variables may not be "
                "readable. Ask the developer to switch to Debug (or RelWithDebInfo) before debugging."),
    "MinSizeRel": ("Optimized for size, usually without debug symbols: breakpoints may not bind and variables may not "
                   "be readable. Ask the developer to switch to Debug (or RelWithDebInfo) before debugging."),
}


def _typed(name: str, source: str, platform: str | None = None) -> dict:
    known = KNOWN.get(name.lower())
    info = {"type": known[0] if known else name, "source": source}
    if platform:
        info["platform"] = platform
    if known:
        info["optimized"], info["debug_symbols"] = known[1], known[2]
        note = NOTES.get(known[0])
    else:
        info["optimized"] = info["debug_symbols"] = None
        note = f'"{name}" is not a standard build type; check its optimization and debug-symbol settings.'
    if note:
        info["note"] = note
    return info


def _cmake_cache(start: Path, stop: Path) -> Path | None:
    """The CMakeCache.txt of the build folder that holds `start`, looking up to `stop` (at most 6 levels)."""
    folder = start
    for _ in range(6):
        cache = folder / "CMakeCache.txt"
        if cache.is_file():
            return cache
        if folder == stop or folder.parent == folder:
            return None
        folder = folder.parent
    return None


def _cache_value(cache: Path, key: str) -> str | None:
    try:
        text = cache.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(rf"^{key}:[A-Z]+=(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def build_type(launch: dict, folder: str) -> dict:
    """What the agent should know about the build this configuration runs. `type` is None when unknown."""
    kind = launch.get("type")
    if kind in INTERPRETED:
        return {"type": None, "source": "interpreted language: no build type", "optimized": False,
                "debug_symbols": True}
    configuration = launch.get("configuration")
    if kind == "visualstudio" and isinstance(configuration, str) and configuration:
        name, _, platform = configuration.partition("|")
        return _typed(name, "Visual Studio's active configuration", platform or None)
    program = launch.get("program")
    if not isinstance(program, str) or not program.strip():
        return {"type": None, "source": "unknown: the configuration names no program"}
    for variable in ("${workspaceFolder}", "${workspaceRoot}"):
        program = program.replace(variable, folder)
    if "${" in program:
        return {"type": None, "source": "unknown: the program path uses a variable that is filled in at launch"}
    path = Path(program if os.path.isabs(program) else os.path.join(folder, program))
    parts = list(path.parent.parts)
    for part in reversed(parts):
        if part.lower() in KNOWN:
            return _typed(part, f"the program's folder ({part})")
    cache = _cmake_cache(path.parent, Path(folder))
    if cache is not None:
        configured = _cache_value(cache, "CMAKE_BUILD_TYPE")
        if configured:
            return _typed(configured, "CMAKE_BUILD_TYPE in CMakeCache.txt")
        return {"type": None, "source": "CMakeCache.txt sets no CMAKE_BUILD_TYPE (the compiler's defaults: no "
                                        "optimization and no debug symbols unless the project adds flags)",
                "note": "Breakpoints may not bind without debug symbols; ask the developer which build this is."}
    return {"type": None, "source": "unknown: not in the configuration, the program's folder or a CMake cache"}


def describe(info: dict | None) -> str:
    """One line for the report and the dialog notes, e.g. "Debug build (not optimized, with debug symbols)"."""
    if not info:
        return "unknown"
    if info.get("type") is None:
        return info.get("source") or "unknown"
    flags = []
    if info.get("optimized") is not None:
        flags.append("optimized" if info["optimized"] else "not optimized")
    if info.get("debug_symbols") is not None:
        flags.append("with debug symbols" if info["debug_symbols"] else "usually without debug symbols")
    platform = f" {info['platform']}" if info.get("platform") else ""
    return f"{info['type']}{platform} build" + (f" ({', '.join(flags)})" if flags else "")
