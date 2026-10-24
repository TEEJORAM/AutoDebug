"""UG-01..UG-03: guide command, static site, Pages workflow."""

import unittest
from pathlib import Path

from autodebug import cli
from autodebug.guide import GUIDE_URL, SITE_MUST_CONTAIN, render_guide

ROOT = Path(__file__).resolve().parents[1]


class TestGuideCommand(unittest.TestCase):
    def test_guide_exits_0_and_names_the_pages_url(self):
        from tests.test_cli import run_cli

        code, out, err = run_cli("guide")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn(GUIDE_URL, out)
        self.assertIn("Real debugger control is disabled", out)
        self.assertIn("config vscode --demo --write", out)
        self.assertIn("config cursor --demo --write", out)
        self.assertIn("does not write CLion, Visual Studio or Xcode", out)

    def test_text_follows_the_operating_system(self):
        windows = render_guide("Windows", "py -m autodebug")
        self.assertIn("%LOCALAPPDATA%\\autodebug", windows)
        self.assertIn("py -m autodebug doctor", windows)
        linux = render_guide("Linux", "autodebug")
        self.assertIn("~/.local/state/autodebug", linux)
        self.assertIn("no known configuration path on Linux", linux)
        mac = render_guide("Darwin", "autodebug")
        self.assertIn("~/Library/Application Support/autodebug", mac)
        self.assertIn("autodebug config claude-desktop --demo --write", mac)

    def test_doctor_ready_line_points_at_the_guide(self):
        from tests.test_cli import run_cli

        code, out, _ = run_cli("doctor")
        if code == 0:
            self.assertIn(GUIDE_URL, out)


class TestSite(unittest.TestCase):
    def test_pages_site_contains_the_shared_steps(self):
        html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        for phrase in SITE_MUST_CONTAIN:
            self.assertIn(phrase, html, phrase)

    def test_pages_workflow_publishes_the_site_directory(self):
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("path: site", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)
        self.assertIn("Does not install packages or contact a debugger.", workflow)
