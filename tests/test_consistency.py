"""The server, the VS Code relay and the Visual Studio relay each enforce the same rules on their own. These tests
read the three sources and check the rules are written the same way: the allowed debugger requests, the step
requests, the hit-count pattern, the variable-path pattern and the condition grammar."""

import re
import unittest
from pathlib import Path

from autodebug import checks

SRC = Path(__file__).resolve().parent.parent / "src" / "autodebug"
RELAY = (SRC / "extension" / "relay.js").read_text(encoding="utf-8")
GATE = (SRC / "visualstudio" / "Core" / "Gate.cs").read_text(encoding="utf-8")
PATH_PATTERN = r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|->[A-Za-z_$][\w$]*|\[\d{1,9}\])*"


def _quoted(text: str) -> set[str]:
    return set(re.findall(r"['\"](\w+)['\"]", text))


def _js_set(name: str) -> set[str]:
    return _quoted(re.search(rf"const {name} = new Set\(\[(.*?)\]\);", RELAY, re.S).group(1))


def _cs_set(name: str) -> set[str]:
    return _quoted(re.search(rf"HashSet<string> {name} = new HashSet<string> \{{(.*?)\}};", GATE, re.S).group(1))


def _python_requests() -> set[str]:
    sent = set()
    for module in SRC.glob("*.py"):
        sent |= set(re.findall(r"_dap\(\"(\w+)\"", module.read_text(encoding="utf-8")))
    return sent


class SameRules(unittest.TestCase):
    def test_the_relays_allow_the_same_debugger_requests(self):
        self.assertEqual(_js_set("DAP_COMMANDS"), _cs_set("Allowed"))
        self.assertEqual(_js_set("STEPS"), _cs_set("Steps"))

    def test_the_server_sends_only_allowed_requests(self):
        sent = _python_requests()
        self.assertTrue(sent, "found no requests in the server's code")
        self.assertLessEqual(sent, _js_set("DAP_COMMANDS"))

    def test_nothing_that_runs_code_is_allowed(self):
        for command in ("evaluate", "setVariable", "setExpression", "writeMemory", "goto", "restartFrame"):
            self.assertNotIn(command, _js_set("DAP_COMMANDS"))
            self.assertNotIn(command, _cs_set("Allowed"))

    def test_hit_counts_are_checked_alike(self):
        python = checks._HIT.pattern
        self.assertIn(f"const HIT = /^{python}$/;", RELAY)
        self.assertIn(f'Regex(@"^{python}$")', GATE)

    def test_variable_paths_are_checked_alike(self):
        self.assertEqual(checks._VARIABLE_PATH.pattern, PATH_PATTERN)
        self.assertIn(f"const VARIABLE_PATH = /^{PATH_PATTERN}$/;", RELAY)
        self.assertIn(f'Regex(@"^{PATH_PATTERN}$")', GATE)

    def test_conditions_use_one_token_grammar(self):
        python = re.sub(r"\(\?P<\w+>", "(", re.sub(r"\s+", "", checks._CONDITION_TOKEN.pattern))
        js = re.search(r"const CONDITION_TOKEN = /(.*)/y;", RELAY).group(1)
        cs = re.search(r'Regex ConditionToken = new System\.Text\.RegularExpressions\.Regex\(\s*@"\\G(.*)"\);',
                       GATE).group(1).replace('""', '"')
        self.assertEqual(js, python)
        self.assertEqual(cs, python)


if __name__ == "__main__":
    unittest.main()
