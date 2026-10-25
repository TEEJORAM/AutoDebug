"""`autodebug setup` and `doctor`: extension package and MCP config files."""

import io
import json
import sys
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
            self.assertEqual(path.name, "autodebug.autodebug-0.5.0.vsix")
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ["extension.vsixmanifest", "[Content_Types].xml",
                                                      "extension/package.json", "extension/extension.js",
                                                      "extension/relay.js", "extension/mcp.js", "extension/readme.md", "extension/LICENSE.txt"])
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
        from autodebug import hub  # doctor checks the service; do not leave one running after the test
        for name, value in (("connect_service", {}), ("status", {"version": "test", "pid": 1, "busy": False})):
            patch = mock.patch.object(hub, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

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
        self.assertIn("extension-autodebug, already switched on", out)
        self.assertFalse((self.home / ".cursor" / "mcp.json").is_file())

    def test_setup_alone_connects_everything_it_finds(self):
        claude = self.home / ".claude.json"
        claude.write_text(json.dumps({"numStartups": 7, "mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
        project = self.home / "Demo"
        project.mkdir()
        with mock.patch.object(install, "ide_command", side_effect=lambda ide: "cursor" if ide == "cursor" else None), \
                mock.patch.object(install, "vsix_installer", return_value=None), \
                mock.patch.object(install.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")):
            code, out = self.run_cli("setup", "--no-install", str(project))
        self.assertEqual(code, 0, out)
        self.assertIn("for Cursor, Claude Code", out)
        self.assertNotIn("VS Code", out)
        data = json.loads(claude.read_text(encoding="utf-8"))
        self.assertEqual(data["numStartups"], 7)  # Claude Code's own settings are kept
        self.assertEqual(set(data["mcpServers"]), {"other"})  # a project folder was given: the entry goes there
        self.assertEqual(json.loads((project.resolve() / ".mcp.json").read_text())["mcpServers"]["autodebug"]["args"],
                         ["-m", "autodebug", "serve"])
        self.assertFalse((project.resolve() / ".cursor" / "mcp.json").is_file())  # the extension registers it
        self.assertTrue(install.has_agent_instructions(str(project)))
        self.assertIn("Left for you:\n  1. Cursor: Developer: Reload Window", out)
        code, out = self.run_cli("setup", "claude", "--no-install")
        self.assertIn("autodebug", json.loads(claude.read_text(encoding="utf-8"))["mcpServers"])
        self.assertIn("Nothing left to set up.", out)

    def test_setup_finding_nothing_says_what_to_install(self):
        with mock.patch.object(install, "ide_command", return_value=None), \
                mock.patch.object(install, "vsix_installer", return_value=None), \
                mock.patch.object(install, "claude_present", return_value=False):
            code, out = self.run_cli("setup")
        self.assertEqual(code, 1)
        self.assertIn("found none of VS Code, Cursor", out)

    def test_setup_without_the_ide_command_explains_vsix(self):
        with mock.patch.object(install, "ide_command", return_value=None):
            code, out = self.run_cli("setup", "vscode")
        self.assertEqual(code, 1)
        self.assertIn("Install from VSIX", out)

    def test_doctor_flags_old_demo_entries(self):
        project = self.home / "Demo"
        (project / ".vscode").mkdir(parents=True)
        (project / ".vscode" / "mcp.json").write_text(json.dumps(
            {"servers": {"autodebug": {"command": "py", "args": ["-m", "autodebug", "serve", "--demo"]}}}))
        code, out = self.run_cli("doctor", str(project))
        self.assertEqual(code, 1)
        self.assertIn("old server command", out)
        install.write_config("vscode", str(project))
        code, out = self.run_cli("doctor", str(project))
        self.assertIn(f"VS Code: {project.resolve() / '.vscode' / 'mcp.json'}", out)

    def test_cursor_relies_on_the_extension_and_drops_the_old_entry(self):
        path = self.home / ".cursor" / "mcp.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"mcpServers": {"figcraft": {"command": "x"}, "autodebug": {"command": "py"}}}))
        code, out = self.run_cli("doctor")
        self.assertIn("Cursor shows it switched off", out)
        with mock.patch.object(install, "ide_command", return_value="cursor"), \
                mock.patch.object(install.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")):
            code, out = self.run_cli("setup", "cursor")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(path.read_text())["mcpServers"], {"figcraft": {"command": "x"}})
        server = json.loads(install.server_file().read_text())
        self.assertEqual((server["command"], server["args"]), (sys.executable, ["-m", "autodebug", "serve"]))
        self.assertIn("the extension registers the MCP server itself", out)
        self.assertIn("already switched on", out)
        code, out = self.run_cli("doctor")
        self.assertNotIn("Cursor shows it switched off", out)
        self.assertIn("can register the server themselves", out)

    def test_doctor_names_an_old_extension_in_a_running_window(self):
        from tests.fake_extension import FakeExtension

        fake = FakeExtension(self.home / "state" / "bridges", str(self.home / "Demo"))
        self.addCleanup(fake.close)
        fake.write_file(protocol=2, version="0.2.0")
        code, out = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertIn("AutoDebug extension 0.2.0 (protocol 2)", out)
        self.assertIn("Developer: Reload Window", out)

    def test_visual_studio_config_is_the_user_mcp_json(self):
        path = install.write_config("visualstudio")
        self.assertEqual(path, self.home / ".mcp.json")
        entry = json.loads(path.read_text())["servers"]["autodebug"]
        self.assertEqual((entry["type"], entry["args"]), ("stdio", ["-m", "autodebug", "serve"]))
        project = self.home / "Blender"
        self.assertEqual(install.write_config("visualstudio", str(project)), project.resolve() / ".mcp.json")

    def test_setup_visualstudio_with_a_missing_vsix_file_stops(self):
        with mock.patch.object(install, "vsix_installer", return_value="VSIXInstaller.exe"), \
             mock.patch.object(install, "visual_studio_running", return_value=False), \
             mock.patch.object(install, "install_vs_extension") as installer:
            code, out = self.run_cli("setup", "visualstudio", "--vsix", str(self.home / "missing.vsix"))
        self.assertEqual(code, 1)
        self.assertIn("there is no file", out)
        installer.assert_not_called()

    def test_setup_visualstudio_while_visual_studio_is_open_says_so(self):
        with mock.patch.object(install, "vsix_installer", return_value="VSIXInstaller.exe"), \
             mock.patch.object(install, "visual_studio_running", return_value=True), \
             mock.patch.object(install, "install_vs_extension") as installer:
            code, out = self.run_cli("setup", "visualstudio", "--vsix", str(self.home / "a.vsix"))
        self.assertEqual(code, 1)
        self.assertIn("Visual Studio is open", out)
        installer.assert_not_called()

    def test_setup_visualstudio_without_visual_studio_explains(self):
        with mock.patch.object(install, "vsix_installer", return_value=None):
            code, out = self.run_cli("setup", "visualstudio")
        self.assertEqual(code, 1)
        self.assertIn("could not find Visual Studio 2022 or 2026", out)
        self.assertIn("added to", out)


    def test_setup_with_a_folder_writes_agent_instructions(self):
        project = self.home / "Demo"
        project.mkdir()
        (project / "AGENTS.md").write_text("# Team notes\n\nKeep tests green.\n", encoding="utf-8")
        with mock.patch.object(install, "vsix_installer", return_value=None):
            self.run_cli("setup", "visualstudio", str(project))
        code, out = self.run_cli("agents", str(project))
        self.assertEqual(code, 0)
        text = (project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Team notes\n\nKeep tests green.\n"))
        self.assertEqual(text.count(install.AGENTS_START), 1)
        self.assertIn(" run list_targets ide=visualstudio", text)
        self.assertIn("click **Approve**", text)
        self.assertTrue(install.has_agent_instructions(str(project)))


class License(unittest.TestCase):
    def test_every_package_carries_the_mit_license(self):
        root = Path(install.__file__).resolve().parents[2]
        self.assertEqual(install.LICENSE_TEXT, (root / "LICENSE").read_text(encoding="utf-8"))
        self.assertTrue(install.LICENSE_TEXT.startswith("MIT License"))
        with tempfile.TemporaryDirectory() as folder:
            with zipfile.ZipFile(install.build_vsix(Path(folder))) as vsix:
                self.assertEqual(vsix.read("extension/LICENSE.txt").decode(), install.LICENSE_TEXT)
                self.assertIn("Content.License", vsix.read("extension.vsixmanifest").decode())
        self.assertEqual(install.manifest()["license"], "MIT")
        self.assertEqual((root / "src" / "autodebug" / "visualstudio" / "Extension" / "LICENSE.txt").read_text(encoding="utf-8"),
                         install.LICENSE_TEXT)
        self.assertIn("<License>LICENSE.txt</License>", (root / "src" / "autodebug" / "visualstudio" / "Extension"
                                                          / "source.extension.vsixmanifest").read_text())


class VisualStudioPackage(unittest.TestCase):
    def test_an_installed_copy_is_removed_before_installing(self):
        calls = []
        with mock.patch.object(install.subprocess, "run",
                               side_effect=lambda c, **k: calls.append(c) or mock.Mock(returncode=0)):
            install.install_vs_extension("VSIXInstaller.exe", Path("a.vsix"))
        self.assertEqual(calls, [["VSIXInstaller.exe", "/quiet", f"/uninstall:{install.VS_EXTENSION_ID}"],
                                 ["VSIXInstaller.exe", "/quiet", "a.vsix"]])
        manifest = Path(install.__file__).with_name("visualstudio") / "Extension" / "source.extension.vsixmanifest"
        self.assertIn(f'Identity Id="{install.VS_EXTENSION_ID}"', manifest.read_text())

    def test_every_part_has_the_same_version(self):
        from autodebug import __version__
        source = Path(install.__file__).with_name("visualstudio")
        self.assertIn(f'Version="{__version__}" Language', (source / "Extension" / "source.extension.vsixmanifest").read_text())
        self.assertIn(f"<Version>{__version__}</Version>", (source / "Extension" / "AutoDebug.VisualStudio.csproj").read_text())
        self.assertIn(f'Version = "{__version__}"', (source / "Core" / "RelayServer.cs").read_text())
        self.assertIn(f"visualstudio-v{{version}}", install.VS_RELEASE)


if __name__ == "__main__":
    unittest.main()
