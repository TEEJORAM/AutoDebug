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
        self.assertEqual(len(blocks), 3)  # Windows, macOS, Linux
        for block in blocks:
            for line in block.strip().splitlines():
                self.assertIn(line, readme, f"site command not in README: {line}")

    def test_page_is_self_contained(self):
        site = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(site, r'<script[^>]+src=')
        self.assertIn('name="viewport"', site)
        self.assertIn("prefers-reduced-motion", site)

    def test_no_link_to_the_source_repository(self):
        # The site is reviewed anonymously: no link names the repository or its owner.
        for page in (ROOT / "site").rglob("*.html"):
            text = page.read_text(encoding="utf-8").lower()
            for name in ("teejoram", "swagat"):
                self.assertNotIn(name, text, page.name)
            # Store pages show the publisher's name, so the site names stores without linking them.
            for store in ("pypi.org", "open-vsx.org", "marketplace.visualstudio.com"):
                self.assertNotIn(store, text, page.name)

    def test_documentation_has_no_links(self):
        # The documentation names files and sites as plain text: no hyperlinks, none to the repository or a store.
        pages = [ROOT / "README.md", ROOT / "CLAUDE.md", *(ROOT / "docs").rglob("*.md"),
                 *(ROOT / "examples").rglob("*.md"), *(ROOT / "src").rglob("*.md")]
        for page in pages:
            text = page.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\]\(https?://|<a\s+href", page.name)
            self.assertNotIn("github.com/teejoram", text.lower(), page.name)
        self.assertNotIn("teejoram", (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
