"""What the agent writes into a breakpoint: conditions, hit counts and log messages. The debugger only reads values
for them, so each is checked to be a comparison, a count or a list of variable names (docs/design.md, "Agent
tools"). The relays (relay.js, Gate.cs) apply the same rules on their own."""

from __future__ import annotations

import re

from autodebug.connection import DebugError


#: A hit condition: a count, optionally with the comparison the debugger applies (>=, >, ==, <=, <, %).
_HIT = re.compile(r"\s*(>=|<=|==|>|<|%)?\s*\d{1,9}\s*")


#: What a log message may show between braces: a variable or a path into one, never an expression.
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


_VARIABLE_PATH = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|->[A-Za-z_$][\w$]*|\[\d{1,9}\])*")


def check_hit_condition(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _HIT.fullmatch(value):
        raise DebugError("BAD_REQUEST", "hit_condition is a count such as 5, >=5 or %10")
    return value.strip()


def check_log_message(value: object) -> str | None:
    """A log point's message. Braces may name a variable or a path into one ({total}, {mesh.verts[2].co}), so the
    debugger only reads values; anything else in braces would be an expression it evaluates."""
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 300 or any(ord(ch) < 32 for ch in value):
        raise DebugError("BAD_REQUEST", "log_message is one line of at most 300 characters")
    for inner in _PLACEHOLDER.findall(value):
        if not _VARIABLE_PATH.fullmatch(inner.strip()):
            raise DebugError("BAD_REQUEST", f"log_message may show variables by name only, like {{total}} or "
                                            f"{{mesh.verts[2].co}}; {{{inner}}} is an expression")
    return value


#: One token of a condition: a quoted string, a number, a comparison or joining operator, or a variable path.
_CONDITION_TOKEN = re.compile(r"""\s*(?:
    (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<number>0[xX][0-9a-fA-F]+|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?[fFuUlL]*)
  | (?P<operator>==|!=|<=|>=|<|>|&&|\|\||!)
  | (?P<path>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|->[A-Za-z_$][\w$]*|\[\d{1,9}\])*)
)""", re.VERBOSE)




def check_condition(value: object) -> str | None:
    """A breakpoint or exception condition the debugger can only compare: variables, paths, numbers, strings and
    true/false/null, joined by ==, !=, <, <=, >, >=, is (not), not/!, and/&&, or/||. No calls, assignments or
    arithmetic: anything else would run code the developer did not approve."""
    if value in (None, ""):
        return None
    text = str(value)
    if len(text) > 300 or any(ord(ch) < 32 for ch in text):
        raise DebugError("BAD_REQUEST", "a condition is one line of at most 300 characters")
    tokens = _condition_tokens(text)
    if tokens is None or not _only_comparisons(tokens):
        raise DebugError("BAD_REQUEST", f"a condition may only compare values, like i > 500 or name == \"x\"; "
                                        f"{text.strip()[:60]!r} is not one")
    return text.strip()


def _condition_tokens(text: str) -> list[tuple[str, str]] | None:
    """The condition as (kind, word) pairs: value, compare, negate or join. None when something else is in it."""
    tokens, at, end = [], 0, len(text.rstrip())
    while at < end:
        match = _CONDITION_TOKEN.match(text, at)
        if not match or match.end() == at:
            return None
        kind, word = match.lastgroup, match.group(match.lastgroup)
        if kind == "path":
            kind = {"and": "join", "or": "join", "not": "negate", "is": "compare"}.get(word, "value")
        elif kind == "operator":
            kind = {"&&": "join", "||": "join", "!": "negate"}.get(word, "compare")
        else:
            kind = "value"
        tokens.append((kind, word))
        at = match.end()
    return tokens


def _only_comparisons(tokens: list[tuple[str, str]]) -> bool:
    """term := [not] value [compare [not after is] value]; terms joined by and/or."""
    i = 0
    while True:
        while i < len(tokens) and tokens[i][0] == "negate":
            i += 1
        if i >= len(tokens) or tokens[i][0] != "value":
            return False
        i += 1
        if i < len(tokens) and tokens[i][0] == "compare":
            i += 1
            if i < len(tokens) and tokens[i - 1][1] == "is" and tokens[i][0] == "negate":
                i += 1
            if i >= len(tokens) or tokens[i][0] != "value":
                return False
            i += 1
        if i == len(tokens):
            return True
        if tokens[i][0] != "join":
            return False
        i += 1
