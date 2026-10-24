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

## 3. Let an AI agent debug it with AutoDebug

The agent sets the breakpoints, runs **Debug tests** under VS Code's debugger,
steps through the code and writes a report, but only after you click
**Approve** in VS Code. Do steps 1 and 2 once; they need VS Code with the
Python extension.

**1. Install the AutoDebug Bridge extension.** From the AutoDebug folder:

Windows (PowerShell):

```powershell
py -m autodebug bridge install vscode
```

macOS / Linux:

```sh
autodebug bridge install vscode
```

If it says the `code` command is not on PATH, it prints the path of a `.vsix`
file instead: in VS Code open **Extensions** → **···** → **Install from VSIX…**
and choose that file.

**2. Connect this folder.** Still in the AutoDebug folder:

Windows (PowerShell):

```powershell
py -m autodebug config vscode --write examples\AutoDebugDemo
```

macOS / Linux:

```sh
autodebug config vscode --write examples/AutoDebugDemo
```

There is no `--demo` here: that would start the practice debugger instead.

**3. Open this folder in VS Code.** **File → Open Folder** →
`examples/AutoDebugDemo`. The status bar shows **AutoDebug** when the bridge is
running (if it doesn't, run **Developer: Reload Window**). Then Command Palette
→ **MCP: List Servers** → **autodebug** → **Start Server** (or **Restart
Server** if it was already running).

**4. Ask the agent.** In Copilot Chat, **Agent** mode:

> Help to debug AutoDebugDemo using the autodebug tools. Bug: moving a shape
> changes its area (the "Debug tests" launch configuration shows it). Choose
> breakpoints in the code that computes the area, request my approval, then
> step through it to find the cause. Finish the case with the problem, root
> cause, solution and evidence, and tell me where the report is.

**5. Approve.** VS Code shows a dialog listing exactly what will run: the
launch configuration, the breakpoints and the step and time limits. Click
**Approve** only if that is what you want. Nothing runs before you click.

The agent then stops at its breakpoints, reads the stack and variables, and
steps until it finds the cause. The report appears in
`autodebug-reports/DEMO-AREA-MOVE.md`, with the problem, a timeline of every
stop and step, the root cause and the fix. Values that look like secrets are
shown as `***REDACTED***`.

[`autodebug-plan.json`](autodebug-plan.json) is an example of the plan the agent
stages; it uses `D:\Projects\AutoDebug\...` as the folder, so the agent
replaces that with yours.

**In Cursor** the steps are the same with `cursor` in place of `vscode`:
`bridge install cursor` and `config cursor --write examples\AutoDebugDemo`
(writes `.cursor/mcp.json`). Install the **Python** and **Python Debugger**
extensions in Cursor, enable `autodebug` in **Cursor Settings → MCP**, and ask in
Agent chat, adding: *"We are in Cursor, so use target ide cursor."*

**Practice debugger.** `config vscode --demo --write examples/AutoDebugDemo`
instead connects AutoDebug's built-in synthetic debugger (case
`AUTODEBUG-DEMO`, not this app), which needs no extension and no approval.

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
