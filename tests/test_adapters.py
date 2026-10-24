"""T01 acceptance tests — stdlib `unittest` only, zero third-party packages.

Covers tasks.md T01's acceptance criteria and the IDE-01-A scenario
(docs/test-plan.md TC-20): five adapters are declared, none crashes, none
claims unproven support, and no real application or debugger is contacted.
"""

import platform
import unittest

from autodebug.adapters import (
    ALL_ADAPTERS,
    BaseAdapter,
    CLionAdapter,
    CursorAdapter,
    VisualStudioAdapter,
    VSCodeAdapter,
    XcodeAdapter,
)
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.models import CapabilityState

#: Adapters that are real implementations (fail closed with
#: BACKEND_UNAVAILABLE when no client is attached) rather than T01 stubs
#: (fail closed with a bare NotImplementedError). Updated as each proof
#: task (T08, T09, T10, T11, T12) lands. All five adapters are now real
#: implementations.
REAL_ADAPTERS = (VSCodeAdapter, CursorAdapter, CLionAdapter, XcodeAdapter, VisualStudioAdapter)


class TestAdapterEnumeration(unittest.TestCase):
    def test_exactly_five_adapters_declared(self):
        self.assertEqual(len(ALL_ADAPTERS), 5)

    def test_each_adapter_is_a_base_adapter(self):
        for cls in ALL_ADAPTERS:
            with self.subTest(cls.ide_id):
                self.assertTrue(issubclass(cls, BaseAdapter))

    def test_each_adapter_declares_required_identity(self):
        for cls in ALL_ADAPTERS:
            with self.subTest(cls.ide_id):
                instance = cls()
                self.assertTrue(instance.ide_id)
                self.assertTrue(instance.supported_os)
                self.assertTrue(instance.proof_task_id)

    def test_probe_never_claims_support_it_has_not_proven(self):
        # IDE-01-A: a wrong-OS adapter reports NOT_APPLICABLE rather than
        # crashing or claiming support; a right-OS adapter reports UNKNOWN,
        # since real capability discovery is T02's job, not T01's.
        for cls in ALL_ADAPTERS:
            instance = cls()
            result = instance.probe()
            with self.subTest(cls.ide_id):
                self.assertIn(
                    result.state, (CapabilityState.NOT_APPLICABLE, CapabilityState.UNKNOWN)
                )
                if platform.system() not in instance.supported_os:
                    self.assertEqual(result.state, CapabilityState.NOT_APPLICABLE)
                else:
                    self.assertEqual(result.state, CapabilityState.UNKNOWN)

    def test_no_real_debugger_operation_is_attempted(self):
        # Every operation beyond probe() must fail closed, never silently
        # succeed or contact a real process. All five adapters are now real
        # implementations (T08-T12) — with no client attached, each fails
        # closed with AutoDebugError(BACKEND_UNAVAILABLE) (IDE-03-A: "bridge
        # is absent -> UNAVAILABLE"), a stronger, typed guarantee than a
        # bare NotImplementedError, not a regression. No stub adapters
        # remain, so the `else` branch below is dead code kept only as a
        # structural safety net should a future adapter be added as a stub.
        for cls in ALL_ADAPTERS:
            instance = cls()
            with self.subTest(cls.ide_id):
                if cls in REAL_ADAPTERS:
                    with self.assertRaises(AutoDebugError) as ctx:
                        instance.list_sessions()
                    self.assertEqual(ctx.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)
                    with self.assertRaises(AutoDebugError) as ctx:
                        instance.launch_or_attach(target=None, reviewed_configuration=None)
                    self.assertEqual(ctx.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)
                else:
                    with self.assertRaises(NotImplementedError):
                        instance.list_sessions()
                    with self.assertRaises(NotImplementedError):
                        instance.launch_or_attach(target=None, reviewed_configuration=None)

    def test_is_paused_fails_closed_the_same_way_as_every_other_operation(self):
        # T08 added `is_paused` to BaseAdapter (previously only improvised on
        # the FakeAdapter test double — see tasks.md T08). Regression: the
        # still-stub adapters must raise NotImplementedError for it exactly
        # like every other operation; the real adapters (no client attached)
        # must raise BACKEND_UNAVAILABLE exactly like their other operations.
        # Confirms the new contract did not silently succeed for anyone.
        for cls in ALL_ADAPTERS:
            instance = cls()
            with self.subTest(cls.ide_id):
                if cls in REAL_ADAPTERS:
                    with self.assertRaises(AutoDebugError) as ctx:
                        instance.is_paused("some-session-id")
                    self.assertEqual(ctx.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)
                else:
                    with self.assertRaises(NotImplementedError):
                        instance.is_paused("some-session-id")


if __name__ == "__main__":
    unittest.main()
