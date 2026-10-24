# Requirements delta

### EX-01 Example trace
`autodebug_debug_example` takes no arguments. It loads `geometry.py` from the
current folder or `examples/AutoDebugDemo`, stops on the `total +=` line inside
`polygon_area`, and records `i`, `len(points)` and `total` for a unit square
before and after a move of `(2, 1)`. It writes `investigation.md` beside
`geometry.py`. The result sets `ide_debugger` to `not_connected`.

### EX-02 Refused files
A `geometry.py` that imports a module or calls a function other than `len`,
`abs`, or `range` is not executed, and `investigation.md` is not written.
