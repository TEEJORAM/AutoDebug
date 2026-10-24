"""Bound facade latency; quarantine late or noncooperative backend results."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol, TypeVar

from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail

T = TypeVar("T")
_LOG = logging.getLogger(__name__)


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


def call_bounded(
    function: Callable[[], T], *, timeout: float, cancellation: Cancellation,
    on_abandon: Callable[[], None], on_late_result: Callable[[T], None] | None = None,
    on_late_error: Callable[[], None] | None = None,
) -> T:
    finished = threading.Event()
    abandoned = threading.Event()
    cleanup_lock = threading.Lock()
    values: list[T] = []
    errors: list[BaseException] = []
    cleaned = False

    def cleanup() -> None:
        nonlocal cleaned
        with cleanup_lock:
            if cleaned or not finished.is_set():
                return
            cleaned = True
        try:
            if errors and on_late_error is not None:
                on_late_error()
            elif values and on_late_result is not None:
                on_late_result(values[0])
        except Exception:
            _LOG.error("Late backend cleanup failed; target remains quarantined")

    def worker() -> None:
        try:
            values.append(function())
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()
            if abandoned.is_set():
                cleanup()

    if cancellation.is_set():
        raise AutoDebugError(ErrorDetail(code=ErrorCode.CANCELLED, message="operation cancelled before dispatch"))
    deadline = time.monotonic() + timeout
    threading.Thread(target=worker, name="autodebug-bounded-operation", daemon=True).start()
    while True:
        if cancellation.is_set() or time.monotonic() >= deadline:
            cancelled = cancellation.is_set()
            on_abandon()
            abandoned.set()
            if finished.is_set():
                threading.Thread(target=cleanup, name="autodebug-late-cleanup", daemon=True).start()
            raise AutoDebugError(ErrorDetail(
                code=ErrorCode.CANCELLED if cancelled else ErrorCode.TIMEOUT,
                message="backend operation cancelled" if cancelled else "backend operation deadline exceeded",
            ))
        if finished.wait(min(0.01, max(0.0, deadline - time.monotonic()))):
            if cancellation.is_set() or time.monotonic() >= deadline:
                continue
            if errors:
                raise errors[0]
            return values[0]
