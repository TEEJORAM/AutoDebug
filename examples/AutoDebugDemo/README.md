# AutoDebugDemo

A tiny sketch-geometry project for trying AutoDebug. It contains no company
code or data. Moving a shape does not change its area.

The shoelace loop in `geometry.py` includes the edge from the last point back
to the first: `(i + 1) % n`. Leaving that edge out made a moved unit square
report area `2.00` instead of `1.00`.

## 1. Run it

From the AutoDebug folder.

Windows (PowerShell):

```powershell
cd examples\AutoDebugDemo
py report.py
py -m unittest -v
```

macOS / Linux:

```sh
cd examples/AutoDebugDemo
python3 report.py
python3 -m unittest -v
```

`report.py` prints `ok` for every shape and ends with `0 of 3 shapes change area when moved.` Both tests pass.

## 2. Look at the loop in VS Code

1. Open this folder in VS Code (**File → Open Folder → `examples/AutoDebugDemo`**).
2. Open `geometry.py`. The area term is on line 16 (`total += x1 * y2 - x2 * y1`).
3. **Run and Debug** → **Debug tests** → `F5`.
4. At each stop, `i` runs `0 .. len(points) - 1`, and the next point is `points[(i + 1) % n]`.

## 3. Try AutoDebug with this project

Run this from the AutoDebug folder, then open `examples/AutoDebugDemo` in VS
Code and start the server (**MCP: List Servers → autodebug → Start Server**).

Windows (PowerShell):

```powershell
py -m autodebug config vscode --demo --write examples\AutoDebugDemo
```

macOS / Linux:

```sh
autodebug config vscode --demo --write examples/AutoDebugDemo
```

Ask Copilot Chat in **Agent** mode:

> Use the autodebug tools to investigate case AUTODEBUG-DEMO: show its status,
> the stack, and the variables local_var and password, then complete the case
> as inconclusive.

**What this shows today:** AutoDebug can only drive its built-in *synthetic*
debugger, so case `AUTODEBUG-DEMO` is not this app. It demonstrates the
workflow: verified stop, bounded stack, redacted variables (`password`), step
budget and an evidence report on disk.

## 4. When AutoDebug can drive VS Code's debugger

[`autodebug-plan.json`](autodebug-plan.json) is a plan for this file: a
breakpoint at `geometry.py:16` and a launch of `report.py`. You would approve
that exact plan before AutoDebug could set the breakpoint in your VS Code
session.

## C++ version

`cpp/geometry.cpp` uses the same closing-edge loop, for Visual Studio, CLion,
Xcode or VS Code with a C++ debugger. Build it from this folder (needs CMake
and a C++ compiler):

```sh
cmake -S cpp -B build
cmake --build build
```

Run `build\Debug\geometry.exe` on Windows (Visual Studio generator) or
`build/geometry` on macOS/Linux. In Visual Studio use **File → Open → CMake...**
on `cpp/CMakeLists.txt`; in CLion open the `cpp` folder.
