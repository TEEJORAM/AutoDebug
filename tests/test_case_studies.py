"""The site's case studies: pages built from the reports, nothing missing, nothing unsafe."""

import importlib.util
import io
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("case_studies", ROOT / "tools" / "case_studies.py")
cs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cs)


class Pages(unittest.TestCase):
    def test_pages_and_index_section_are_up_to_date(self):
        with redirect_stdout(io.StringIO()) as out:
            code = cs.main(["--check"])
        self.assertEqual(code, 0, out.getvalue())

    def test_every_case_has_its_files_and_videos_fit_on_github(self):
        data = cs.load()
        self.assertEqual(len(data["cases"]), 5)
        for case in data["cases"]:
            for suffix in (".md", ".mp4", ".jpg", ".html"):
                path = cs.FOLDER / f"{case['slug']}{suffix}"
                self.assertTrue(path.is_file(), path)
            self.assertLess((cs.FOLDER / f"{case['slug']}.mp4").stat().st_size, 50 * 1024 * 1024)
            self.assertTrue(case["facts"]["stops"], case["slug"])
            for _, src, _ in case["facts"]["stops"]:
                self.assertTrue((cs.FOLDER / src).is_file(), src)

    def test_index_links_every_case_and_shows_one_at_a_time(self):
        index = (cs.SITE / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="#cases"', index)
        panels = re.findall(r'<section class="case" id="case-\d+"[^>]*>', index)
        self.assertEqual(len(panels), 5)
        self.assertEqual(sum("hidden" in p for p in panels), 4)
        for case in cs.load()["cases"]:
            self.assertIn(f'href="case-studies/{case["slug"]}.html"', index)

    def test_report_pages_are_self_contained(self):
        for page in cs.FOLDER.glob("*.html"):
            text = page.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"<script[^>]+src=")
            self.assertIn('name="viewport"', text)


class Markdown(unittest.TestCase):
    def test_text_is_escaped_and_only_web_or_site_links_survive(self):
        self.assertEqual(cs.inline("<b>x</b>"), "&lt;b&gt;x&lt;/b&gt;")
        self.assertNotIn("href", cs.inline("[click](javascript:alert(1))"))
        self.assertEqual(cs.inline("[click](javascript:void)"), "click")
        self.assertIn('href="https://example.com/a"', cs.inline("[a](https://example.com/a)"))
        self.assertEqual(cs.inline("`<p>`"), "<code>&lt;p&gt;</code>")

    def test_report_facts_are_read(self):
        text = ("# Title\n\n## Debug sessions\n\n### Stop 1: The value is wrong.\n\n"
                "![Stop 1: Visual Studio at a.cpp:3](screenshots/s.png)\n\n## Root cause\n\n"
                "Confidence: Confirmed. Seen in Locals.\n\nVerified: rebuilt and ran.\n\n"
                "- Model: Some Model 1 (as the agent reported it)\n")
        body, facts = cs.render_markdown(text)
        self.assertEqual(facts["title"], "Title")
        self.assertEqual(facts["confidence"], "Confirmed")
        self.assertTrue(facts["verified"])
        self.assertEqual(facts["model"], "Some Model 1")
        self.assertEqual(facts["stops"][0][0], "Stop 1: The value is wrong.")
        self.assertIn('<h2 id="root-cause">', body)

    def test_unfenced_code_in_a_report_keeps_its_lines(self):
        body, _ = cs.render_markdown("for (int i) {\n    call(i);\n}\n")
        self.assertIn("<pre>for (int i) {\n    call(i);\n}</pre>", body)


if __name__ == "__main__":
    unittest.main()
