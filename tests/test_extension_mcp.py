"""The extension registers the autodebug MCP server with Cursor or VS Code itself (extension/mcp.js),
driven through Node.js with a stand-in for the `vscode` module. Skipped without Node.js."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
MCP = ROOT / "src" / "autodebug" / "extension" / "mcp.js"

SCRIPT = r"""
const mcp = require(process.argv[1]);
const [ide, state, home, folder] = process.argv.slice(2);
const calls = [];
const vscode = { workspace: { workspaceFolders: [{ uri: { fsPath: folder } }] } };
if (ide === 'cursor') vscode.cursor = { mcp: { registerServer: (c) => calls.push(['register', c]),
                                               unregisterServer: (n) => calls.push(['unregister', n]) } };
if (ide === 'vscode') {
  vscode.McpStdioServerDefinition = class { constructor(...a) { this.args = a; } };
  vscode.lm = { registerMcpServerDefinitionProvider: (id, p) => {
    calls.push(['provider', id, p.provideMcpServerDefinitions().map((d) => d.args)]); return { dispose() {} }; } };
}
const context = { subscriptions: [], globalStorageUri: { fsPath: home + '/User/globalStorage/SwagatTeejoram.autodebug' } };
const result = mcp.register(vscode, context, { stateFolder: state, log: () => {}, home });
context.subscriptions.forEach((s) => s.dispose && s.dispose());
console.log(JSON.stringify({ result, calls }));
"""


@unittest.skipIf(NODE is None, "needs Node.js")
class Register(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state, self.home, self.folder = self.root / "state", self.root / "home", self.root / "project"
        for folder in (self.state, self.home, self.folder):
            folder.mkdir()
        self.server = {"command": "C:/Python314/python.exe", "args": ["-m", "autodebug", "serve"],
                       "env": {"PYTHONPATH": "D:/AutoDebug/src"}, "version": "0.5.0"}
        (self.state / "server.json").write_text(json.dumps(self.server), encoding="utf-8")

    def run_ide(self, ide: str) -> dict:
        done = subprocess.run([NODE, "-e", SCRIPT, str(MCP), ide, str(self.state), str(self.home), str(self.folder)],
                              capture_output=True, text=True, timeout=30, check=True)
        return json.loads(done.stdout)

    def test_cursor_gets_the_server_from_setup(self):
        out = self.run_ide("cursor")
        self.assertEqual(out["result"], "cursor")
        self.assertEqual(out["calls"][0], ["register", {"name": "autodebug", "server": {
            "command": self.server["command"], "args": self.server["args"], "env": self.server["env"]}}])
        self.assertEqual(out["calls"][1], ["unregister", "autodebug"])  # when the window closes

    def test_vscode_gets_a_provider(self):
        out = self.run_ide("vscode")
        self.assertEqual(out["result"], "vscode")
        self.assertEqual(out["calls"], [["provider", "autodebug.server", [[
            "AutoDebug", self.server["command"], self.server["args"], self.server["env"], "0.5.0"]]]])
        manifest = json.loads((MCP.parent / "package.json").read_text(encoding="utf-8"))
        self.assertIn({"id": "autodebug.server", "label": "AutoDebug"}, manifest["contributes"]["mcpServerDefinitionProviders"])

    def test_an_existing_mcp_json_entry_is_not_duplicated(self):
        (self.home / ".cursor").mkdir()
        (self.home / ".cursor" / "mcp.json").write_text('{"mcpServers": {"autodebug": {"command": "py"}}}', encoding="utf-8")
        self.assertEqual(self.run_ide("cursor"), {"result": "configured", "calls": []})
        (self.folder / ".vscode").mkdir()
        (self.folder / ".vscode" / "mcp.json").write_text('{"servers": {"autodebug": {"command": "py"}}}', encoding="utf-8")
        self.assertEqual(self.run_ide("vscode"), {"result": "configured", "calls": []})

    def test_without_setup_or_an_api_nothing_is_registered(self):
        (self.state / "server.json").unlink()
        self.assertEqual(self.run_ide("cursor"), {"result": "no-config", "calls": []})
        self.assertEqual(self.run_ide("old"), {"result": "unsupported", "calls": []})


if __name__ == "__main__":
    unittest.main()
