"""Session registry (T03) — GW-03: explicit native session identity, and
GW-05: safe per-session operation serialization.

Session identity is never process-name-based. This registry is the single
source of truth for which `SessionRef` instances AutoDebug currently considers
live; a target that doesn't resolve to exactly one registered session is a
reason to stop, not to guess.
"""

from __future__ import annotations

import threading

from autodebug.errors import AutoDebugError, ErrorCode, ErrorDetail
from autodebug.models import SessionRef, TargetRef

_SessionKey = tuple[str, str, str]  # (host_id, ide, debug_session_id)


def _key(host_id: str, ide: str, debug_session_id: str) -> _SessionKey:
    return (host_id, ide, debug_session_id)


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[_SessionKey, SessionRef] = {}
        self._registry_lock = threading.Lock()
        self._op_locks: dict[_SessionKey, threading.Lock] = {}
        self._arm_locks: dict[tuple[str, str], threading.Lock] = {}
        self._owners: dict[_SessionKey, object] = {}
        self._quarantined_targets: set[tuple[str, str]] = set()

    def register(self, session: SessionRef) -> None:
        """Record or refresh a session's current identity."""
        with self._registry_lock:
            self._sessions[_key(session.host_id, session.ide, session.debug_session_id)] = session

    def unregister(self, session: SessionRef) -> None:
        """Drop a session, e.g. after disconnect or a confirmed process exit."""
        with self._registry_lock:
            key = _key(session.host_id, session.ide, session.debug_session_id)
            if self._sessions.get(key) == session:
                self._sessions.pop(key, None)

    def arming_lease(self, target: TargetRef) -> SessionLease:
        with self._registry_lock:
            self._check_quarantine(target.host_id, target.ide)
            lock = self._arm_locks.setdefault((target.host_id, target.ide), threading.Lock())
        return SessionLease(lock)

    def claim(self, session: SessionRef, owner: object) -> None:
        key = _key(session.host_id, session.ide, session.debug_session_id)
        with self._registry_lock:
            self._check_quarantine(session.host_id, session.ide)
            current_owner = self._owners.get(key)
            if current_owner is not None and current_owner is not owner:
                raise AutoDebugError(
                    ErrorDetail(code=ErrorCode.POLICY_LIMIT, message="session belongs to another active case")
                )
            self._owners[key] = owner

    def release_owner(self, session: SessionRef, owner: object) -> None:
        key = _key(session.host_id, session.ide, session.debug_session_id)
        with self._registry_lock:
            if self._owners.get(key) is owner:
                self._owners.pop(key, None)

    def verify_owner(self, session: SessionRef, owner: object) -> None:
        with self._registry_lock:
            self._check_quarantine(session.host_id, session.ide)
            if self._owners.get(_key(session.host_id, session.ide, session.debug_session_id)) is not owner:
                raise AutoDebugError(ErrorDetail(code=ErrorCode.TARGET_MISMATCH, message="session is not owned by this investigation"))

    def quarantine(self, target: TargetRef) -> None:
        with self._registry_lock:
            self._quarantined_targets.add((target.host_id, target.ide))

    def _check_quarantine(self, host_id: str, ide: str) -> None:
        if (host_id, ide) in self._quarantined_targets:
            raise AutoDebugError(ErrorDetail(code=ErrorCode.BACKEND_UNAVAILABLE, message="backend target is quarantined after an abandoned operation"))

    def all_sessions(self) -> tuple[SessionRef, ...]:
        with self._registry_lock:
            return tuple(self._sessions.values())

    def find_by_target(self, target: TargetRef) -> tuple[SessionRef, ...]:
        """Every registered session matching `target`'s known fields.

        An underspecified target (e.g. host+ide only, on a host with two
        windows open) can legitimately match more than one session — that is
        GW-03-A's point: the caller must disambiguate, not us. `ide_instance_id`
        is one of the fields GW-03 names as part of a session's identity, so a
        target may disambiguate by it just as it can by `debug_session_id`/`pid`.
        """
        with self._registry_lock:
            matches = []
            for session in self._sessions.values():
                if session.host_id != target.host_id or session.ide != target.ide:
                    continue
                if target.debug_session_id is not None and session.debug_session_id != target.debug_session_id:
                    continue
                if target.pid is not None and session.pid != target.pid:
                    continue
                if target.ide_instance_id is not None and session.ide_instance_id != target.ide_instance_id:
                    continue
                matches.append(session)
            return tuple(matches)

    def resolve(self, target: TargetRef) -> SessionRef | None:
        """Resolve `target` to exactly one session, or `None` if it isn't
        registered yet. GW-03-A: two or more matches is `SESSION_AMBIGUOUS`,
        never a silent "pick the first one"."""
        matches = self.find_by_target(target)
        if len(matches) > 1:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.SESSION_AMBIGUOUS,
                    message=(
                        f"{len(matches)} sessions match {target.host_id}/{target.ide}; "
                        "specify debug_session_id, pid, or ide_instance_id to disambiguate"
                    ),
                )
            )
        return matches[0] if matches else None

    def verify_identity(
        self,
        session: SessionRef,
        *,
        expected_pid: int,
        expected_generation: int,
        expected_ide_instance_id: str,
    ) -> None:
        """GW-03-B: re-check PID, generation, and IDE instance before a
        mutating operation.

        A session that has exited (no longer registered) fails as
        `SESSION_STALE`; a session whose registered identity has since
        changed — PID reused by a new process, a new generation/nonce, or
        (GW-03) reassignment to a different IDE instance/window — fails as
        `TARGET_MISMATCH`. Either way, no backend call is made first.
        """
        with self._registry_lock:
            current = self._sessions.get(_key(session.host_id, session.ide, session.debug_session_id))
        if current is None:
            raise AutoDebugError(
                ErrorDetail(code=ErrorCode.SESSION_STALE, message="session is no longer registered")
            )
        if (
            current.pid != expected_pid
            or current.session_generation != expected_generation
            or current.ide_instance_id != expected_ide_instance_id
            or current.executable != session.executable
            or current.process_start_id != session.process_start_id
        ):
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.TARGET_MISMATCH,
                    message="session identity has changed since it was last referenced",
                )
            )

    def lease(self, session: SessionRef) -> SessionLease:
        """GW-05: a non-blocking, per-session mutual-exclusion lease. At most
        one mutating operation on a given session proceeds at a time; a
        second concurrent attempt is rejected immediately, never queued
        silently or left to race."""
        key = _key(session.host_id, session.ide, session.debug_session_id)
        with self._registry_lock:
            self._check_quarantine(session.host_id, session.ide)
            lock = self._op_locks.setdefault(key, threading.Lock())
        return SessionLease(lock)


class SessionLease:
    """Context manager wrapping a per-session lock. Raises `POLICY_LIMIT` if
    the session is already busy, rather than blocking — GW-05 requires
    serialization and a controlled rejection, not an unbounded wait."""

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock
        self._acquired = False

    def __enter__(self) -> SessionLease:
        self._acquired = self._lock.acquire(blocking=False)
        if not self._acquired:
            raise AutoDebugError(
                ErrorDetail(
                    code=ErrorCode.POLICY_LIMIT,
                    message="another operation is already in progress on this session",
                )
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._acquired:
            self._lock.release()
            self._acquired = False
