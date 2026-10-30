"""Open the project in an IDE for the agent, once (docs/design.md, "Opening the IDE").

Agents used to start Visual Studio themselves and opened it three times while the
first copy was still loading. `open_ide` finds the solution (or folder), reuses a
window that already has it, otherwise starts the IDE once and waits for the
Autodebug extension in it. A second call while that IDE is still loading waits
instead of starting another copy. Opening the IDE runs nothing of the program:
debugging still needs the developer's Approve click.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from autodebug.connection import IDE_NAMES, DebugError, same_folder, state_folder

SOLUTIONS = (".sln", ".slnx")
_SKIP = {".git", "node_modules", ".vs", "out", "__pycache__"}
#: How long a start counts as "still loading": no second copy of the IDE before this.
LOADING_SECONDS = 180


def visual_studio() -> str | None:
    """devenv.exe of the newest Visual Studio 2022/2026, found with vswhere."""
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return None
    result = subprocess.run([str(vswhere), "-latest", "-prerelease", "-version", "[17.0,19.0)", "-property", "productPath"],
                            capture_output=True, text=True, timeout=60, check=False)
    found = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    return found if found and Path(found).is_file() else None


def find_solutions(folder: Path, depth: int = 3) -> list[Path]:
    """Solution files in `folder` and up to `depth` levels below it (a CMake build folder, for example)."""
    found: list[Path] = []

    def walk(current: Path, level: int) -> None:
        try:
            entries = sorted(current.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_file() and entry.suffix.lower() in SOLUTIONS:
                found.append(entry)
            elif entry.is_dir() and level < depth and entry.name not in _SKIP and not entry.is_symlink():
                walk(entry, level + 1)

    walk(folder, 0)
    return found


def cmake_source(solution: Path) -> Path | None:
    """The source folder of a CMake-generated solution (CMAKE_HOME_DIRECTORY beside it), else None."""
    cache = solution.parent / "CMakeCache.txt"
    try:
        match = re.search(r"^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$", cache.read_text(encoding="utf-8", errors="replace"),
                          re.MULTILINE)
    except OSError:
        return None
    return Path(match.group(1).strip()) if match else None


def target(ide: str, path: str) -> tuple[Path, Path]:
    """(what to open, the folder the IDE window will report) for `path`, or a DebugError saying what to do."""
    given = Path(path).expanduser()
    if not given.is_absolute():
        raise DebugError("BAD_REQUEST", "path must be absolute")
    if not given.exists():
        raise DebugError("NOT_FOUND", f"{given} does not exist")
    if ide != "visualstudio":
        if not given.is_dir():
            raise DebugError("BAD_REQUEST", f"{IDE_NAMES[ide]} opens a folder; pass the project folder")
        return given, given
    if given.is_file():
        if given.suffix.lower() not in SOLUTIONS:
            raise DebugError("BAD_REQUEST", "pass a .sln or .slnx file, or the folder that contains one")
        solution = given
    else:
        solutions = find_solutions(given)
        if not solutions:
            raise DebugError("NOT_FOUND", f"no .sln file in {given} or the 3 folders below it. For a CMake project, "
                                          "generate one first, for example: cmake -S . -B build -G \"Visual Studio 18 "
                                          "2026\" -A x64 (\"Visual Studio 17 2022\" for 2022), then call open_ide with "
                                          "the build folder")
        if len(solutions) > 1:
            listed = ", ".join(str(s) for s in solutions[:10])
            raise DebugError("AMBIGUOUS_WINDOW", f"several solutions: {listed}. Ask the developer which one, then pass "
                                                 "that file as path")
        solution = solutions[0]
    return solution, cmake_source(solution) or solution.parent


def _record() -> Path:
    return state_folder() / "opening.json"


def recently_started(ide: str, opened: Path) -> float | None:
    """Seconds since Autodebug started this IDE with this path, if that was less than LOADING_SECONDS ago."""
    try:
        data = json.loads(_record().read_text(encoding="utf-8"))
        if data.get("ide") == ide and same_folder(str(data.get("path")), str(opened)):
            age = time.time() - float(data.get("started", 0))
            return age if 0 <= age < LOADING_SECONDS else None
    except (OSError, ValueError, TypeError):
        pass
    return None


def remember_start(ide: str, opened: Path) -> None:
    path = _record()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ide": ide, "path": str(opened), "started": time.time()}), encoding="utf-8")


def command(ide: str, opened: Path) -> list[str]:
    """The command that opens `opened` in the IDE."""
    if ide == "visualstudio":
        devenv = visual_studio()
        if not devenv:
            raise DebugError("NOT_FOUND", "Visual Studio 2022 or 2026 was not found (vswhere)")
        return [devenv, str(opened)]
    from autodebug.install import ide_command

    launcher = ide_command(ide)
    if not launcher:
        raise DebugError("NOT_FOUND", f"the {IDE_NAMES[ide]} command was not found; open the folder in "
                                      f"{IDE_NAMES[ide]} yourself or ask the developer")
    return [launcher, "--new-window", str(opened)]


def start(argv: list[str]) -> None:
    """Start the IDE detached from Autodebug, so it keeps running when Autodebug exits."""
    options: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                     "close_fds": True}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(argv, **options)  # the IDE's own launcher, found above
