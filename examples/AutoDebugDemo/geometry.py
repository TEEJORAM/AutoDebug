"""Sketch geometry for the AutoDebugDemo project.

The shoelace loop includes the edge from the last point back to the first.
"""

Point = tuple[float, float]


def polygon_area(points: list[Point]) -> float:
    """Area of a simple polygon, using the shoelace formula."""
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def move(points: list[Point], dx: float, dy: float) -> list[Point]:
    """The same shape, shifted by (dx, dy)."""
    return [(x + dx, y + dy) for x, y in points]
