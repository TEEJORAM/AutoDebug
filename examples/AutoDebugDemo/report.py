"""Print the area of a few sketch shapes, before and after moving them.

Moving a shape must never change its area, but here it does. Run:

    python report.py
"""

from geometry import move, polygon_area

SHAPES = {
    "unit square": [(0, 0), (1, 0), (1, 1), (0, 1)],
    "triangle": [(0, 0), (4, 0), (0, 3)],
    "L-bracket": [(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)],
}


def main() -> int:
    wrong = 0
    for name, points in SHAPES.items():
        here = polygon_area(points)
        moved = polygon_area(move(points, 2, 1))
        status = "ok" if here == moved else "WRONG"
        wrong += status == "WRONG"
        print(f"{name:12} area {here:6.2f}   after move {moved:6.2f}   {status}")
    print(f"\n{wrong} of {len(SHAPES)} shapes change area when moved.")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
