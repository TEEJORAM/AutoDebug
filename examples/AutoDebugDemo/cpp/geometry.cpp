// C++ twin of geometry.py / report.py, for debugging in Visual Studio,
// CLion, Xcode or VS Code with a C++ debugger. Same deliberate bug.
#include <cmath>
#include <cstdio>
#include <utility>
#include <vector>

using Point = std::pair<double, double>;

// Area of a simple polygon, using the shoelace formula.
double polygon_area(const std::vector<Point>& points) {
    double total = 0.0;
    for (std::size_t i = 0; i + 1 < points.size(); ++i) {
        const auto [x1, y1] = points[i];
        const auto [x2, y2] = points[i + 1];
        total += x1 * y2 - x2 * y1;
    }
    return std::fabs(total) / 2;
}

// The same shape, shifted by (dx, dy).
std::vector<Point> move(const std::vector<Point>& points, double dx, double dy) {
    std::vector<Point> moved;
    for (const auto& [x, y] : points) moved.emplace_back(x + dx, y + dy);
    return moved;
}

int main() {
    const std::pair<const char*, std::vector<Point>> shapes[] = {
        {"unit square", {{0, 0}, {1, 0}, {1, 1}, {0, 1}}},
        {"triangle", {{0, 0}, {4, 0}, {0, 3}}},
        {"L-bracket", {{0, 0}, {4, 0}, {4, 1}, {1, 1}, {1, 3}, {0, 3}}},
    };
    int wrong = 0;
    for (const auto& [name, points] : shapes) {
        const double here = polygon_area(points);
        const double moved = polygon_area(move(points, 2, 1));
        const bool ok = here == moved;
        wrong += ok ? 0 : 1;
        std::printf("%-12s area %6.2f   after move %6.2f   %s\n", name, here, moved, ok ? "ok" : "WRONG");
    }
    std::printf("\n%d of 3 shapes change area when moved.\n", wrong);
    return wrong ? 1 : 0;
}
