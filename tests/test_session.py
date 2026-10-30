"""The launch-configuration checks and variable paths in autodebug.session."""

import unittest

from autodebug.checks import check_hit_condition, check_log_message
from autodebug.connection import DebugError
from autodebug.launch import apply_platform, prepare_launch, remote_problem, substitutions, task_chain, test_arguments
from autodebug.values import split_path


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


class BreakpointOptions(unittest.TestCase):
    def test_hit_conditions_are_counts(self):
        for good in ("5", ">=5", "%10", " == 3 ", "<2"):
            self.assertEqual(check_hit_condition(good), good.strip())
        self.assertIsNone(check_hit_condition(None))
        for bad in ("i > 5", "5 and 6", "len(x)", ">= -1"):
            with self.assertRaises(DebugError, msg=bad):
                check_hit_condition(bad)

    def test_log_messages_name_variables_only(self):
        for good in ("total={total}", "{mesh.verts[2].co} at {i}", "no braces", "{ scene->objects[3] }"):
            self.assertEqual(check_log_message(good), good)
        for bad in ("{total + 1}", "{f()}", "{__import__('os')}", "{a[i]}", "two\nlines"):
            with self.assertRaises(DebugError, msg=bad):
                check_log_message(bad)


class OldExtension(unittest.TestCase):
    def test_a_request_the_extension_does_not_know_asks_for_setup(self):
        from types import SimpleNamespace

        from autodebug.session import Session

        class Relay:
            window = SimpleNamespace(ide="cursor")

            def call(self, op, args, timeout=0):
                raise DebugError("BAD_REQUEST", f"the debugger request {args['command']} is not allowed")

        session = Session(Relay())
        with self.assertRaises(DebugError) as caught:
            session._dap("modules", {})
        self.assertEqual(caught.exception.code, "OLD_EXTENSION")
        self.assertIn("Run autodebug setup, then reload", caught.exception.message)
        session._options_supported([{"file": "a.py", "line": 1}])  # plain breakpoints are fine
        with self.assertRaises(DebugError) as caught:
            session._options_supported([{"file": "a.py", "line": 1, "log_message": "x={x}"}])
        self.assertIn("cannot place hit counts, log points or columns", caught.exception.message)


class OneTest(unittest.TestCase):
    def test_runners(self):
        launch = {"name": "t", "request": "launch"}
        self.assertEqual(test_arguments({**launch, "module": "pytest"}, "tests/test_a.py::test_b"), ["tests/test_a.py::test_b"])
        self.assertEqual(test_arguments({**launch, "module": "unittest"}, "test_a.Case.test_b"), ["test_a.Case.test_b"])
        self.assertEqual(test_arguments({**launch, "type": "go", "mode": "test"}, "TestArea"), ["-test.run", "^TestArea$"])
        self.assertEqual(test_arguments({**launch, "program": "${workspaceFolder}/node_modules/.bin/jest"}, "moves"),
                         ["--runInBand", "-t", "moves"])
        self.assertEqual(test_arguments({**launch, "program": "node_modules/vitest/vitest.mjs"}, "moves"), ["run", "-t", "moves"])

    def test_refusals(self):
        with self.assertRaises(DebugError) as caught:
            test_arguments({"name": "app", "request": "launch", "program": "app.py"}, "test_x")
        self.assertIn("pass args", caught.exception.message)
        for bad in ("-k x", "a\nb", "${env:HOME}", ""):
            with self.assertRaises(DebugError):
                test_arguments({"name": "t", "request": "launch", "module": "pytest"}, bad)
        with self.assertRaises(DebugError):
            test_arguments({"name": "t", "request": "attach", "module": "pytest"}, "test_x")


if __name__ == "__main__":
    unittest.main()
