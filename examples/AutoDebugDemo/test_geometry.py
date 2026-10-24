"""Tests for geometry.py. One of them fails until the bug is fixed:

    python -m unittest -v
"""

import unittest

from geometry import move, polygon_area

SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]


class PolygonAreaTests(unittest.TestCase):
    def test_unit_square_at_origin(self):
        self.assertEqual(polygon_area(SQUARE), 1.0)

    def test_area_does_not_change_when_moved(self):
        self.assertEqual(polygon_area(move(SQUARE, 2, 1)), 1.0)


if __name__ == "__main__":
    unittest.main()
