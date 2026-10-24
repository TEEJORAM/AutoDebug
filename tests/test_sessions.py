"""T03 acceptance tests — SessionRegistry (GW-03, GW-05). Stdlib `unittest`
and `threading` only, zero third-party packages."""

import threading
import unittest

from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.models import SessionRef, TargetRef
from autodebug.sessions import SessionRegistry


def make_session(**overrides) -> SessionRef:
    defaults = dict(
        host_id="local-mac",
        ide="clion",
        ide_instance_id="clion-window-1",
        debug_session_id="native-session-1",
        session_generation=1,
        pid=4210,
        executable="/disposable/test-app",
        state="paused",
        capabilities=("stack", "variables", "breakpoints", "step"),
    )
    defaults.update(overrides)
    return SessionRef(**defaults)


class TestExactSessionIdentity(unittest.TestCase):
    """GW-03: a session is identified by host, IDE instance, backend session
    ID, process identity and generation — never by process name alone."""

    def test_two_debuggers_open_are_distinguishable_and_require_disambiguation(self):
        # GW-03-A
        registry = SessionRegistry()
        session_a = make_session(debug_session_id="native-session-1", pid=111)
        session_b = make_session(debug_session_id="native-session-2", pid=222)
        registry.register(session_a)
        registry.register(session_b)

        loose_target = TargetRef(host_id="local-mac", ide="clion", debug_session_id=None, pid=None)
        matches = registry.find_by_target(loose_target)
        self.assertEqual(set(matches), {session_a, session_b})

        with self.assertRaises(AutoDebugError) as ctx:
            registry.resolve(loose_target)
        self.assertEqual(ctx.exception.detail.code, ErrorCode.SESSION_AMBIGUOUS)

        # Explicit selection resolves cleanly.
        precise_target = TargetRef(host_id="local-mac", ide="clion", debug_session_id="native-session-2", pid=None)
        self.assertEqual(registry.resolve(precise_target), session_b)

    def test_unregistered_target_resolves_to_none_not_a_guess(self):
        registry = SessionRegistry()
        target = TargetRef(host_id="local-mac", ide="xcode", debug_session_id=None, pid=None)
        self.assertIsNone(registry.resolve(target))

    def test_exited_process_with_reused_pid_fails_closed(self):
        # GW-03-B: "a previously selected process has exited and its PID was
        # reused" -> fails as SESSION_STALE or TARGET_MISMATCH, no backend call.
        registry = SessionRegistry()
        original = make_session(pid=4210, session_generation=1)
        registry.register(original)

        # Case 1: the session fully exited and was unregistered -> SESSION_STALE.
        registry.unregister(original)
        with self.assertRaises(AutoDebugError) as ctx:
            registry.verify_identity(
                original, expected_pid=4210, expected_generation=1, expected_ide_instance_id="clion-window-1"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.SESSION_STALE)

        # Case 2: the registry was refreshed and the same debug_session_id now
        # points at a different process/generation (PID reused) -> TARGET_MISMATCH.
        refreshed = make_session(pid=4210, session_generation=2)  # same key, new generation
        registry.register(refreshed)
        with self.assertRaises(AutoDebugError) as ctx:
            registry.verify_identity(
                original, expected_pid=4210, expected_generation=1, expected_ide_instance_id="clion-window-1"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.TARGET_MISMATCH)

    def test_matching_identity_passes_verification(self):
        registry = SessionRegistry()
        session = make_session()
        registry.register(session)
        registry.verify_identity(
            session,
            expected_pid=session.pid,
            expected_generation=session.session_generation,
            expected_ide_instance_id=session.ide_instance_id,
        )

    def test_two_windows_are_disambiguated_by_ide_instance_id(self):
        # GW-03: "IDE instance" is one of the five identity components a
        # target may select by, not just debug_session_id/pid.
        registry = SessionRegistry()
        window_1 = make_session(debug_session_id="native-session-1", ide_instance_id="clion-window-1", pid=111)
        window_2 = make_session(debug_session_id="native-session-2", ide_instance_id="clion-window-2", pid=222)
        registry.register(window_1)
        registry.register(window_2)

        target = TargetRef(
            host_id="local-mac", ide="clion", debug_session_id=None, pid=None, ide_instance_id="clion-window-2"
        )
        self.assertEqual(registry.resolve(target), window_2)

    def test_session_reassigned_to_a_different_ide_instance_fails_closed(self):
        # GW-03: the registry refreshes the same (host, ide, debug_session_id)
        # key but the IDE instance/window it belongs to has changed — this is
        # just as much an identity change as a reused PID, and must fail the
        # same way: TARGET_MISMATCH, with no backend call made.
        registry = SessionRegistry()
        original = make_session(pid=4210, session_generation=1, ide_instance_id="clion-window-1")
        registry.register(original)

        reassigned = make_session(pid=4210, session_generation=1, ide_instance_id="clion-window-2")
        registry.register(reassigned)

        with self.assertRaises(AutoDebugError) as ctx:
            registry.verify_identity(
                original, expected_pid=4210, expected_generation=1, expected_ide_instance_id="clion-window-1"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.TARGET_MISMATCH)

    def test_ambiguous_error_message_names_ide_instance_id_as_a_disambiguator(self):
        registry = SessionRegistry()
        registry.register(make_session(debug_session_id="native-session-1", pid=111))
        registry.register(make_session(debug_session_id="native-session-2", pid=222))
        loose_target = TargetRef(host_id="local-mac", ide="clion", debug_session_id=None, pid=None)

        with self.assertRaises(AutoDebugError) as ctx:
            registry.resolve(loose_target)
        self.assertIn("ide_instance_id", ctx.exception.detail.message)


class TestSafeOperationSerialization(unittest.TestCase):
    """GW-05: state-changing commands are serialized per native session."""

    def test_second_concurrent_lease_on_same_session_is_rejected(self):
        # GW-05-A, synchronous form: a lease already held blocks a second one.
        registry = SessionRegistry()
        session = make_session()
        with registry.lease(session):
            with self.assertRaises(AutoDebugError) as ctx:
                with registry.lease(session):
                    pass
            self.assertEqual(ctx.exception.detail.code, ErrorCode.POLICY_LIMIT)

    def test_different_sessions_are_independent(self):
        registry = SessionRegistry()
        session_a = make_session(debug_session_id="native-session-1")
        session_b = make_session(debug_session_id="native-session-2")
        with registry.lease(session_a):
            with registry.lease(session_b):
                pass  # must not raise: unrelated sessions don't contend

    def test_concurrent_threads_all_fail_while_one_holds_the_session(self):
        # GW-05-A with real threads, made deterministic via explicit
        # synchronization (not timing/sleep): a holder thread deliberately
        # keeps the lease open while 4 challenger threads attempt it
        # concurrently. Every challenger must be rejected — none may proceed
        # while the holder is still inside its critical section.
        registry = SessionRegistry()
        session = make_session()
        holder_has_entered = threading.Event()
        release_holder = threading.Event()
        results: list[object] = []
        results_lock = threading.Lock()

        def holder():
            with registry.lease(session):
                holder_has_entered.set()
                release_holder.wait(timeout=2)

        def challenger():
            holder_has_entered.wait(timeout=2)
            try:
                with registry.lease(session):
                    outcome = "succeeded"
            except AutoDebugError as exc:
                outcome = exc.detail.code
            with results_lock:
                results.append(outcome)

        holder_thread = threading.Thread(target=holder)
        holder_thread.start()
        self.assertTrue(holder_has_entered.wait(timeout=2))

        challengers = [threading.Thread(target=challenger) for _ in range(4)]
        for t in challengers:
            t.start()
        for t in challengers:
            t.join()

        release_holder.set()
        holder_thread.join(timeout=2)

        self.assertEqual(results, [ErrorCode.POLICY_LIMIT] * 4)

        # Once released, the session is free again.
        with registry.lease(session):
            pass


if __name__ == "__main__":
    unittest.main()
