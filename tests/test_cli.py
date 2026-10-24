"""CLI-01..CLI-05 (openspec/changes/cli-usability): subcommands, evidence
location, doctor, client configuration and editable installs."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from autodebug import cli

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:  # argparse --help/--version/usage errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class _TempDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="autodebug-cli-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


class TestCommands(unittest.TestCase):
    def test_no_command_prints_usage_and_exits_2(self):
        code, out, err = run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("serve, doctor or config", err)

    def test_version(self):
        code, out, _ = run_cli("--version")
        self.assertEqual(code, 0)
        self.assertIn("autodebug 0.1.0", out)

    def test_legacy_flags_map_to_serve(self):
        self.assertEqual(cli._legacy_serve_argv(["--evidence-dir", "x", "--demo"])[0], "serve")
        self.assertEqual(cli._legacy_serve_argv(["--demo"])[0], "serve")
        for argv in (["--help"], ["--version"], ["doctor"], []):
            self.assertEqual(cli._legacy_serve_argv(argv), argv)


class TestEvidenceLocation(_TempDir):
    def test_precedence_explicit_then_env_then_default(self):
        with patch.dict(os.environ, {cli.EVIDENCE_ENV: str(self.tmp / "env")}):
            self.assertEqual(cli.resolve_evidence_dir(str(self.tmp / "flag")), self.tmp / "flag")
            self.assertEqual(cli.resolve_evidence_dir(None), self.tmp / "env")
        with patch.dict(os.environ, {}, clear=True), patch.object(cli, "default_evidence_dir", return_value=self.tmp / "d"):
            self.assertEqual(cli.resolve_evidence_dir(None), self.tmp / "d")

    def test_platform_defaults(self):
        home = Path("/home/tester")
        cases = {
            ("Linux", ()): home / ".local" / "state" / "autodebug",
            ("Linux", (("XDG_STATE_HOME", "/xdg"),)): Path("/xdg") / "autodebug",
            ("Darwin", ()): home / "Library" / "Application Support" / "autodebug",
            ("Windows", (("LOCALAPPDATA", "C:/Users/u/AppData/Local"),)): Path("C:/Users/u/AppData/Local") / "autodebug",
        }
        for (system, env), expected in cases.items():
            # Path.home() is patched too: with a cleared environment Windows
            # cannot determine a home directory at all.
            with self.subTest(system=system, env=env), patch.object(cli.platform, "system", return_value=system), \
                    patch.dict(os.environ, dict(env), clear=True), patch.object(cli.Path, "home", return_value=home):
                self.assertEqual(cli.default_evidence_dir(), expected)

    @unittest.skipUnless(cli.secure_storage_supported(), "needs secure evidence storage")
    def test_each_run_gets_a_fresh_private_folder(self):
        root = self.tmp / "evidence"
        first, second = cli.create_run_dir(root), cli.create_run_dir(root)
        self.assertNotEqual(first, second)
        for path in (root, first, second):
            self.assertTrue(cli.is_private_dir(path), path)
            if hasattr(os, "getuid"):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700, path)
        self.assertTrue(first.name.startswith("run-"))

    def test_refuses_symlink_and_checkout(self):
        real = self.tmp / "real"
        real.mkdir()
        link = self.tmp / "link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(ValueError):
            cli.create_run_dir(link)
        if cli.inside_source_checkout(ROOT):
            with self.assertRaises(ValueError):
                cli.create_run_dir(ROOT / "evidence-should-not-exist")
            self.assertFalse((ROOT / "evidence-should-not-exist").exists())


class TestDoctor(_TempDir):
    def test_json_report_creates_nothing(self):
        target = self.tmp / "not-yet"
        code, out, _ = run_cli("doctor", "--json", "--evidence-dir", str(target))
        report = json.loads(out)
        self.assertEqual(code, 0 if report["ready"] else 1)
        names = {check["name"] for check in report["checks"]}
        self.assertTrue({"Python", "Evidence storage", "Evidence folder", "IDE adapters", "Real debuggers"} <= names)
        self.assertFalse(target.exists())

    def test_fails_when_storage_or_python_unsupported(self):
        with patch.object(cli, "secure_storage_supported", return_value=False):
            code, out, _ = run_cli("doctor", "--evidence-dir", str(self.tmp / "e"))
        self.assertEqual(code, 1)
        self.assertIn("not available", out)
        with patch.object(cli, "MIN_PYTHON", (99, 0)):
            code, out, _ = run_cli("doctor", "--evidence-dir", str(self.tmp / "e"))
        self.assertEqual(code, 1)
        self.assertIn("needs 3.11", out)

    def test_evidence_inside_checkout_fails(self):
        if not cli.inside_source_checkout(ROOT):
            self.skipTest("not running from a Git checkout")
        code, out, _ = run_cli("doctor", "--evidence-dir", str(ROOT / "evidence"))
        self.assertEqual(code, 1)
        self.assertIn("inside the AutoDebug checkout", out)

    def test_plain_output_without_color_when_not_a_tty(self):
        code, out, _ = run_cli("doctor", "--evidence-dir", str(self.tmp / "e"))
        self.assertNotIn("\033[", out)
        self.assertIn("AutoDebug doctor", out)


class TestConfig(unittest.TestCase):
    def test_json_clients_use_documented_shapes(self):
        for client, key, has_type in (("vscode", "servers", True), ("cursor", "mcpServers", True),
                                      ("claude-desktop", "mcpServers", False)):
            with self.subTest(client=client):
                code, out, err = run_cli("config", client, "--demo")
                self.assertEqual(code, 0)
                entry = json.loads(out)[key]["autodebug"]
                self.assertEqual(entry["command"], sys.executable)
                self.assertEqual(entry["args"], ["-m", "autodebug", "serve", "--demo"])
                self.assertEqual(entry.get("type") == "stdio", has_type)
                self.assertTrue(err.strip())  # placement hint goes to stderr, not stdout

    def test_claude_code_command_orders_options_before_name(self):
        spec = {"command": "/py", "args": ["-m", "autodebug", "serve"], "env": {"PYTHONPATH": "/src"}}
        output, _ = cli.render_config("claude-code", "autodebug", spec)
        self.assertIn("claude mcp add --env PYTHONPATH=/src --transport stdio autodebug -- /py -m autodebug serve",
                      output.replace('"', "").replace("'", ""))

    def test_source_checkout_adds_pythonpath_and_explicit_dir_is_absolute(self):
        spec = cli.server_spec(demo=False, evidence_dir="relative/dir")
        self.assertTrue(Path(spec["args"][-1]).is_absolute())
        if cli._source_pythonpath():
            self.assertEqual(spec["env"]["PYTHONPATH"], str(ROOT / "src"))

    def test_warns_when_storage_unsupported(self):
        with patch.object(cli, "secure_storage_supported", return_value=False):
            _, _, err = run_cli("config", "vscode")
        self.assertIn("warning", err)


class TestServeGuards(_TempDir):
    def test_demo_refused_without_secure_storage(self):
        with patch.object(cli, "secure_storage_supported", return_value=False):
            code, out, err = run_cli("serve", "--demo", "--evidence-dir", str(self.tmp / "e"))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("--demo needs evidence storage", err)
        self.assertFalse((self.tmp / "e").exists())

    @unittest.skipUnless(cli.secure_storage_supported(), "needs POSIX evidence storage")
    def test_repeated_demo_starts_do_not_collide(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1",
                   **{cli.EVIDENCE_ENV: str(self.tmp / "e")})
        init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
        for _ in range(2):
            result = subprocess.run([sys.executable, "-m", "autodebug", "serve", "--demo"], input=(init + "\n").encode(),
                                    env=env, cwd=self.tmp, capture_output=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["id"], 1)  # stdout is pure JSON-RPC
            self.assertIn(b"evidence:", result.stderr)
        self.assertEqual(len(list((self.tmp / "e").glob("run-*"))), 2)


@unittest.skipIf(sys.version_info < (3, 11), "build_backend uses tomllib; AutoDebug requires Python 3.11+")
class TestEditableInstall(_TempDir):
    def test_editable_wheel_points_at_src(self):
        sys.path.insert(0, str(ROOT))
        self.addCleanup(sys.path.remove, str(ROOT))
        import build_backend

        self.assertEqual(build_backend.get_requires_for_build_editable(), [])
        wheel = self.tmp / build_backend.build_editable(str(self.tmp))
        with zipfile.ZipFile(wheel) as archive:
            pth = archive.read("__editable__.autodebug.pth").decode().strip()
            self.assertEqual(Path(pth), ROOT / "src")
            self.assertFalse(any(name.startswith("autodebug/") for name in archive.namelist()))


if __name__ == "__main__":
    unittest.main()
