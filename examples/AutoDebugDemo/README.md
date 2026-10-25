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

## 3. Let the AI agent debug it with AutoDebug

Set up AutoDebug once (see the [main README](../../README.md#set-up-once)):
`py -m autodebug setup cursor` (or `setup vscode`), reload the IDE window, and
turn on the `autodebug` MCP server.

1. Open this folder (`examples/AutoDebugDemo`) in Cursor or VS Code. The status
   bar shows **AutoDebug**.
2. In the agent chat (Agent mode), ask:

   > Help me debug AutoDebugDemo: moving a shape changes its area. Use the
   > autodebug tools to find the root cause and write a report.

3. The IDE asks whether the agent may run "Debug tests", with the breakpoints it
   chose. Click **Approve**.

The agent stops in `polygon_area`, steps through the loop, traces `i` and
`total` on line 15, and finds that the loop ends at `i = 2` for four corners.
The report appears in `autodebug-reports/`.

## C++ version

`cpp/geometry.cpp` has the same bug at line 16, for Visual Studio, CLion, Xcode
or VS Code with a C++ debugger. Build it from this folder (needs CMake and a C++
compiler):

```sh
cmake -S cpp -B build
cmake --build build
```

Run `build\Debug\geometry.exe` on Windows (Visual Studio generator) or
`build/geometry` on macOS/Linux. In CLion open the `cpp` folder.

### With AutoDebug in Visual Studio

After `autodebug setup visualstudio`, generate a Visual Studio solution and open it:

```powershell
cmake -S cpp -B build\vs
Invoke-Item (Get-Item build\vs\AutoDebugDemo.sln*)[0]
```

(Visual Studio 2026 writes `AutoDebugDemo.slnx`, 2022 `AutoDebugDemo.sln`.) The
startup project is already **geometry**; keep the **Debug** configuration. Then
ask the agent:

> Use the autodebug tools with the Visual Studio window (ide: visualstudio) and its
> launch configuration "geometry (Debug|x64)". Find why moving a shape changes its
> area: stop in polygon_area at geometry.cpp line 16, trace total, and write a report.

Name Visual Studio in the prompt when Cursor or VS Code is open too; otherwise
the agent may debug in its own IDE. In Visual Studio the workspace folder is the
CMake source folder (`cpp`), so the file is `geometry.cpp`. Click **Approve** in
Visual Studio. The breakpoint is shown as not bound until
the program has loaded; that is normal.
