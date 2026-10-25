"""`autodebug setup` and `doctor`: extension package and MCP config files."""

import io
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from autodebug import cli, install


class Package(unittest.TestCase):
    def test_vsix_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = install.build_vsix(Path(tmp))
            self.assertEqual(path.name, "autodebug.autodebug-0.4.0.vsix")
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ["extension.vsixmanifest", "[Content_Types].xml",
                                                      "extension/package.json", "extension/extension.js",
                                                      "extension/relay.js", "extension/readme.md"])
                ET.fromstring(archive.read("extension.vsixmanifest"))
                self.assertEqual(json.loads(archive.read("extension/package.json"))["main"], "./extension.js")
            self.assertEqual(path.read_bytes(), install.build_vsix(Path(tmp) / "again").read_bytes())

    def test_extension_has_no_dependencies_or_evaluate(self):
        self.assertNotIn("dependencies", install.manifest())
        source = (install.EXTENSION_DIR / "relay.js").read_text(encoding="utf-8")
        self.assertNotIn("'evaluate'", source)
        self.assertIn("listen(0, '127.0.0.1'", source)


class Config(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {"APPDATA": str(self.home / "Roaming"), "XDG_CONFIG_HOME": str(self.home / ".config"),
                                               "AUTODEBUG_HOME": str(self.home / "state")})
        patcher.start()
        self.addCleanup(patcher.stop)
        home = mock.patch.object(Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def test_cursor_global_config_keeps_other_servers(self):
        path = self.home / ".cursor" / "mcp.json"
        path.parent.mkdir()
        old = {"mcpServers": {"other": {"command": "x"}, "autodebug": {"command": "py", "args": ["-m", "autodebug", "serve", "--demo"]}}}
        path.write_text(json.dumps(old), encoding="utf-16")  # Windows PowerShell 5.1 writes UTF-16
        self.assertEqual(install.write_config("cursor"), path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["mcpServers"]["other"], {"command": "x"})
        self.assertEqual(data["mcpServers"]["autodebug"]["args"], ["-m", "autodebug", "serve"])

    def test_project_and_vscode_files(self):
        project = self.home / "MyApp"
        project.mkdir()
        project = project.resolve()  # setup writes to the real path (macOS /private, Windows long names)
        self.assertEqual(install.write_config("vscode", str(project)), project / ".vscode" / "mcp.json")
        entry = json.loads((project / ".vscode" / "mcp.json").read_text())["servers"]["autodebug"]
        self.assertEqual(entry["type"], "stdio")
        self.assertEqual(install.write_config("cursor", str(project)), project / ".cursor" / "mcp.json")
        self.assertTrue(install.config_file("vscode").name == "mcp.json")

    def test_commented_config_is_not_overwritten(self):
        path = self.home / ".cursor" / "mcp.json"
        path.parent.mkdir()
        path.write_text('{ // mine\n "mcpServers": {} }', encoding="utf-8")
        with self.assertRaises(ValueError):
            install.write_config("cursor")
        self.assertIn("// mine", path.read_text())

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_setup_installs_and_configures(self):
        calls = []
        with mock.patch.object(install, "ide_command", return_value="cursor"), \
                mock.patch.object(install.subprocess, "run", side_effect=lambda c, **k: calls.append(c) or mock.Mock(returncode=0, stdout="", stderr="")):
            code, out = self.run_cli("setup", "cursor")
        self.assertEqual(code, 0, out)
        self.assertEqual(calls[0][:2], ["cursor", "--uninstall-extension"])
        self.assertEqual(calls[-1][:2], ["cursor", "--install-extension"])
        self.assertIn("extension installed in Cursor", out)
        self.assertIn("Cursor Settings → MCP: turn on autodebug", out)
        self.assertTrue((self.home / ".cursor" / "mcp.json").is_file())

    def test_setup_without_the_ide_command_explains_vsix(self):
        with mock.patch.object(install, "ide_command", return_value=None):
            code, out = self.run_cli("setup", "vscode")
        self.assertEqual(code, 1)
        self.assertIn("Install from VSIX", out)

    def test_doctor_flags_old_demo_entries(self):
        project = self.home / "Demo"
        (project / ".cursor").mkdir(parents=True)
        (project / ".cursor" / "mcp.json").write_text(json.dumps(
            {"mcpServers": {"autodebug": {"command": "py", "args": ["-m", "autodebug", "serve", "--demo"]}}}))
        code, out = self.run_cli("doctor", str(project))
        self.assertEqual(code, 1)
        self.assertIn("old server command", out)
        install.write_config("cursor", str(project))
        code, out = self.run_cli("doctor", str(project))
        self.assertIn(f"Cursor: {project.resolve() / '.cursor' / 'mcp.json'}", out)

    def test_doctor_names_an_old_extension_in_a_running_window(self):
        from tests.fake_extension import FakeExtension

        fake = FakeExtension(self.home / "state" / "bridges", str(self.home / "Demo"))
        self.addCleanup(fake.close)
        fake.write_file(protocol=2, version="0.2.0")
        code, out = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertIn("AutoDebug extension 0.2.0 (protocol 2)", out)
        self.assertIn("Developer: Reload Window", out)


if __name__ == "__main__":
    unittest.main()
