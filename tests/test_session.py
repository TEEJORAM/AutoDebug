"""The launch-configuration checks and variable paths in autodebug.session."""

import unittest

from autodebug.connection import DebugError
from autodebug.session import apply_platform, prepare_launch, remote_problem, split_path, substitutions, task_chain


class LaunchChecks(unittest.TestCase):
    def test_platform_block_is_applied_then_removed(self):
        config = {"program": "a", "windows": {"program": "a.exe"}, "linux": {"program": "a.bin"}, "osx": {}}
        self.assertEqual(apply_platform(config, "win32"), {"program": "a.exe"})
        self.assertEqual(apply_platform(config, "linux"), {"program": "a.bin"})
        self.assertEqual(apply_platform(config, "darwin"), {"program": "a"})

    def test_substitutions_that_would_prompt_are_found(self):
        config = {"program": "${input:file}", "args": ["${command:pick}", "${workspaceFolder}"], "processId": "${command:pickProcess}"}
        self.assertEqual(substitutions(config), ["${input:file}", "${command:pick}", "${command:pickProcess}"])
        self.assertEqual(substitutions(config, attach_pid_allowed=True), ["${input:file}", "${command:pick}"])

    def test_only_this_computer(self):
        for config in ({"host": "localhost"}, {"connect": {"host": "127.0.0.1", "port": 5678}},
                       {"miDebuggerServerAddress": "[::1]:1234"}, {"address": "::1"}, {}):
            self.assertIsNone(remote_problem(config), config)
        self.assertEqual(remote_problem({"connect": {"host": "10.0.0.5"}}), "connect.host")
        self.assertEqual(remote_problem({"miDebuggerServerAddress": "build-box:1234"}), "miDebuggerServerAddress")
        self.assertEqual(remote_problem({"pipeTransport": {"pipeProgram": "ssh"}}), "pipeTransport")

    def test_process_id_fills_the_attach_placeholder(self):
        attach = {"name": "a", "type": "lldb", "request": "attach", "pid": "${command:pickMyProcess}"}
        self.assertEqual(prepare_launch(attach, 4321, "linux")["pid"], 4321)
        with self.assertRaises(DebugError):
            prepare_launch(attach, None, "linux")
        with self.assertRaises(DebugError):
            prepare_launch({**attach, "pid": 99}, 4321, "linux")
        with self.assertRaises(DebugError):
            prepare_launch({"name": "l", "type": "lldb", "request": "launch"}, 4321, "linux")

    def test_task_chain_follows_depends_on_once(self):
        tasks = [{"label": "build", "dependsOn": ["configure", {"task": "fetch"}]},
                 {"label": "configure", "dependsOn": "build"}, {"label": "fetch"}, {"label": "unused"}]
        self.assertEqual([t["label"] for t in task_chain("build", tasks)], ["build", "configure", "fetch"])
        self.assertEqual(task_chain(None, tasks), [])


class Paths(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(split_path("mesh.verts[2].co"), ["mesh", "verts", "2", "co"])
        self.assertEqual(split_path("scene->objects[10]"), ["scene", "objects", "10"])
        self.assertEqual(split_path("total"), ["total"])


if __name__ == "__main__":
    unittest.main()
