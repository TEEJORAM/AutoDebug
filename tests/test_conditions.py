"""Conditions only compare values: the server (session.check_condition), the VS Code relay (relay.js) and the Visual
Studio relay (Gate.cs) apply one grammar. The same cases go through all three."""

import unittest

from autodebug.connection import DebugError
from autodebug.session import check_condition
from tests.test_extension import NODE, HarnessTest
from tests.test_visualstudio import DOTNET, VisualStudioTest

ALLOWED = ["i > 500", 'name == "x"', "x is None", "x is not None", "not done", "!done && i>=3",
           "p->next != nullptr", "a.b[2] == -1.5", "flag", "i == 0x10 or j < 2", "s == 'a b'", "count >= 10 and ok"]
REFUSED = ["f()", "i = 3", "i + 1 > 2", "a[i] == 1", "(i > 2)", "i >", "and i", "i > 2 and", "x.y()",
           '__import__("os")', "i++", "a; b", "i > 2 > 3", "x == y = 3", "i -= 1", "delete p", "not"]


class Server(unittest.TestCase):
    def test_the_grammar(self):
        for text in ALLOWED:
            self.assertEqual(check_condition(text), text, text)
        for text in REFUSED:
            with self.assertRaises(DebugError, msg=text):
                check_condition(text)


class Relays:
    def check(self):
        for text, answer in [(t, "allowed") for t in ALLOWED] + [(t, "refused") for t in REFUSED]:
            self.send(f"condition {text}")
            self.assertEqual(self.expect("CONDITION"), answer, text)


@unittest.skipIf(NODE is None, "needs Node.js")
class VsCodeRelay(Relays, HarnessTest):
    def test_the_same_grammar(self):
        self.check()

    def test_a_condition_that_runs_code_is_refused_before_the_dialog(self):
        with self.assertRaises(DebugError):
            self.start(breakpoints=[{"file": "geometry.py", "line": 15, "condition": "reset() or True"}])


@unittest.skipIf(DOTNET is None, "needs the .NET SDK")
class VisualStudioRelay(Relays, VisualStudioTest):
    def test_the_same_grammar(self):
        self.check()


if __name__ == "__main__":
    unittest.main()
