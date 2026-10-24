# AutoDebugDemo

A tiny sketch-geometry project with **one deliberate bug**, for practising
debugging and for trying AutoDebug. It contains no company code or data.

**The bug:** moving a shape must never change its area, but here it does.

## 1. See it fail

Run these from the AutoDebug folder.

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

`report.py` prints:

```text
unit square  area   1.00   after move   2.00   WRONG
triangle     area   6.00   after move   9.00   WRONG
L-bracket    area   6.00   after move   9.00   WRONG

3 of 3 shapes change area when moved.
```

and one test fails with `AssertionError: 2.0 != 1.0`.

## 2. Find it with the VS Code debugger

1. Open this folder in VS Code (**File → Open Folder → `examples/AutoDebugDemo`**)
   and install the recommended Python extensions when asked.
2. Open `geometry.py` and click left of line 15 (`total += x1 * y2 - x2 * y1`)
   to set a breakpoint.
3. Open **Run and Debug**, choose **Debug tests**, and press `F5`.
4. Each time it stops, look at `i`, `len(points)` and `total` in the
   **Variables** panel. How many times does the loop run for a 4-corner square?
   Which edge of the shape is never added?

<details>
<summary>Answer</summary>

The loop runs `len(points) - 1` times, so it never adds the closing edge from
the last corner back to the first. At the origin that edge's term happens to be
`0`, which is why the unmoved square looks right. Fix it in `geometry.py`:

```python
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
```

Then run the tests again; both pass and `report.py` prints `ok` for every shape.
</details>

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

[`autodebug-plan.json`](autodebug-plan.json) is the plan an AI client would
stage for this bug: a breakpoint at `geometry.py:15`, a launch of `report.py`
and manual reproduction steps. You would approve that exact plan, AutoDebug
would set the breakpoint in your VS Code session, and the AI would read `i`,
`len(points)` and `total` at each stop. It may report `CONFIRMED` only once the
fixed code passes the tests.

## C++ version

`cpp/geometry.cpp` has the same bug at line 16, for Visual Studio, CLion, Xcode
or VS Code with a C++ debugger. Build it from this folder (needs CMake and a C++
compiler):

```sh
cmake -S cpp -B build
cmake --build build
```

Run `build\Debug\geometry.exe` on Windows (Visual Studio generator) or
`build/geometry` on macOS/Linux. In Visual Studio use **File → Open → CMake...**
on `cpp/CMakeLists.txt`; in CLion open the `cpp` folder.
