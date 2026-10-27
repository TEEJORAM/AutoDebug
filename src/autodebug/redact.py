"""Hide secret-looking values before an agent or a report sees them."""

from __future__ import annotations

import re

REDACTED = "***REDACTED***"
MAX_VALUE = 2000

_SECRET_NAME = re.compile(
    r"pass(word|wd|phrase)?|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential|auth(?!or)|cookie|session[_-]?id",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"AKIA[0-9A-Z]{16}"                         # AWS access key ID
    r"|(?:sk|rk|pk)-[A-Za-z0-9_-]{20,}"          # API keys with sk-/rk-/pk- prefixes
    r"|gh[pousr]_[A-Za-z0-9]{36,}"               # GitHub tokens
    r"|xox[abpr]-[A-Za-z0-9-]{10,}"              # Slack tokens
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # JWT
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
)


def looks_secret(text: str) -> bool:
    """True when the text contains a key- or token-shaped value."""
    return bool(_SECRET_VALUE.search(text))


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def clean_text(text: object, limit: int = MAX_VALUE) -> str:
    """Mask secret-shaped substrings and cap the length."""
    value = _SECRET_VALUE.sub(REDACTED, str(text))
    return value if len(value) <= limit else value[:limit] + f"… ({len(value) - limit} more characters)"


def clean_value(name: str, value: object, limit: int = MAX_VALUE) -> str:
    """A variable's value as the agent may see it."""
    if is_secret_name(name):
        return REDACTED
    return clean_text(value, limit)
