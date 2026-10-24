"""Bridge wire format (ide-debug-bridge design, "Bridge protocol").

Newline-delimited UTF-8 JSON over one loopback TCP connection. The first line
from AutoDebug is `{"hello": <token>, "protocol": 1}`; then each request is
`{"id", "op", "args"}` and each reply `{"id", "ok", "result" | "error"}`.
"""

from __future__ import annotations

import json
import math

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1024 * 1024
LOOPBACK = "127.0.0.1"


class ProtocolError(ValueError):
    """A malformed, oversized or unexpected bridge message."""


def _unique(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ProtocolError("non-finite JSON number")


def _finite(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ProtocolError("non-finite JSON number")
    return number


def encode(message: dict) -> bytes:
    data = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) + 1 > MAX_MESSAGE_BYTES:
        raise ProtocolError("message exceeds 1 MiB")
    return data + b"\n"


def decode(line: bytes) -> dict:
    if len(line) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message exceeds 1 MiB")
    if not line.endswith(b"\n"):
        raise ProtocolError("connection closed mid-message")
    try:
        message = json.loads(line.decode("utf-8"), object_pairs_hook=_unique,
                             parse_constant=_reject_constant, parse_float=_finite)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("invalid UTF-8 JSON") from exc
    if type(message) is not dict:
        raise ProtocolError("message must be a JSON object")
    return message
