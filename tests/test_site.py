"""site/index.html stays in step with the README's commands."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Site(unittest.TestCase):
    def test_setup_commands_match_the_readme(self):
        site = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        blocks = re.findall(r'<div class="block"[^>]*><pre>(.*?)</pre>', site, re.S)
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            for line in block.strip().splitlines():
                self.assertIn(line, readme, f"site command not in README: {line}")

    def test_page_is_self_contained(self):
        site = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(site, r'<script[^>]+src=')
        self.assertIn('name="viewport"', site)
        self.assertIn("prefers-reduced-motion", site)


if __name__ == "__main__":
    unittest.main()
