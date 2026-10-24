"""B8 — extension packaging, `autodebug bridge` and the doctor line (BR-01, BR-12)."""

import io
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from autodebug import cli
from autodebug.bridge import package
from autodebug.bridge.client import bridges_dir
from tests.fixtures.fake_bridge import FakeBridge

NS = {"v": "http://schemas.microsoft.com/developer/vsx-schema/2011"}


class Vsix(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_layout_matches_what_vsce_produces(self):
        path = package.build_vsix(self.folder)
        self.assertEqual(path.name, "autodebug.autodebug-bridge-0.1.0.vsix")
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.namelist(), [
                "extension.vsixmanifest", "[Content_Types].xml", "extension/package.json",
                "extension/extension.js", "extension/bridge-core.js", "extension/readme.md"])
            root = ET.fromstring(archive.read("extension.vsixmanifest"))
            ET.fromstring(archive.read("[Content_Types].xml"))
            manifest = json.loads(archive.read("extension/package.json"))
        identity = root.find("v:Metadata/v:Identity", NS).attrib
        self.assertEqual((identity["Id"], identity["Publisher"], identity["Version"]),
                         (manifest["name"], manifest["publisher"], manifest["version"]))
        engine = root.find("v:Metadata/v:Properties/v:Property[@Id='Microsoft.VisualStudio.Code.Engine']", NS)
        self.assertEqual(engine.attrib["Value"], manifest["engines"]["vscode"])

    def test_extension_manifest_declares_no_dependencies(self):
        manifest = package.manifest()
        self.assertNotIn("dependencies", manifest)
        self.assertNotIn("extensionDependencies", manifest)
        self.assertEqual(manifest["main"], "./extension.js")
        self.assertEqual(manifest["activationEvents"], ["onStartupFinished"])

    def test_builds_are_reproducible(self):
        first = package.build_vsix(self.folder / "a").read_bytes()
        second = package.build_vsix(self.folder / "b").read_bytes()
        self.assertEqual(first, second)

    def test_the_bridge_core_never_forwards_evaluate(self):
        source = (package.EXTENSION_DIR / "bridge-core.js").read_text(encoding="utf-8")
        self.assertNotIn("'evaluate'", source)
        self.assertNotIn("setVariable", source)
        self.assertIn("listen(0, '127.0.0.1'", source)


class BridgeCommand(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "evidence"

    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main([*argv, "--evidence-dir", str(self.root)])
        return code, out.getvalue()

    def test_vsix_only(self):
        code, out = self.run_cli("bridge", "install", "vscode", "--vsix-only")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "extension" / package.vsix_name()).is_file())
        self.assertTrue((self.root / "bridges").is_dir())
        self.assertIn(".vsix", out)

    def test_missing_ide_command_explains_the_manual_install(self):
        with mock.patch.object(package, "find_ide_command", return_value=None):
            code, out = self.run_cli("bridge", "install", "cursor")
        self.assertEqual(code, 1)
        self.assertIn("Install from VSIX", out)
        self.assertIn("`cursor` command is not on PATH", out)

    def test_installs_with_the_ide_command(self):
        calls = []
        def fake_run(command, **kwargs):
            calls.append(command)
            return mock.Mock(returncode=0, stdout="installed", stderr="")
        with mock.patch.object(package, "find_ide_command", return_value="code"), \
                mock.patch.object(package.subprocess, "run", fake_run):
            code, out = self.run_cli("bridge", "install", "vscode")
        self.assertEqual(code, 0)
        self.assertEqual(calls[0][:2], ["code", "--install-extension"])
        self.assertEqual(calls[0][3], "--force")
        self.assertIn("Developer: Reload Window", out)
        self.assertIn("config vscode --write PROJECT_FOLDER", out)

    def test_status_and_doctor_list_running_windows(self):
        fake = FakeBridge(bridges_dir(self.root), "/work/demo")
        self.addCleanup(fake.close)
        code, out = self.run_cli("bridge", "status")
        self.assertEqual(code, 0)
        self.assertIn("1 window(s) — vscode: /work/demo", out)
        check = next(c for c in cli.run_checks(self.root) if c.name == "IDE bridge")
        self.assertEqual(check.status, "ok")

    def test_doctor_creates_nothing(self):
        cli.run_checks(self.root)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
