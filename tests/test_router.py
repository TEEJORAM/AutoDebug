"""T03 acceptance tests — Router (GW-04, GW-06). Stdlib `unittest` only,
exercised entirely against the fake backend/adapter fixtures."""

import unittest

from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.models import CapabilityState, TargetRef
from autodebug.router import Router
from autodebug.sessions import SessionRegistry
from tests.fixtures.fake_adapter import FakeAdapter
from tests.fixtures.fake_backend import FULL_SUPPORT, NOT_INSTALLED


def capable_report(adapter: FakeAdapter, *, can_launch: bool = True):
    backend = FULL_SUPPORT if can_launch else NOT_INSTALLED
    return adapter.probe_capabilities(backend=backend, host_os="Darwin")


class TestGW06LaunchAttachScenarios(unittest.TestCase):
    def test_scenario_a_application_not_running_is_launched(self):
        # GW-06-A
        registry = SessionRegistry()
        router = Router(registry)
        adapter = FakeAdapter()
        target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)

        session = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=False
        )

        self.assertEqual(adapter.launch_or_attach_calls, 1)
        self.assertIn(session, registry.all_sessions())

    def test_scenario_b_application_running_not_attached_is_attached(self):
        # GW-06-B
        registry = SessionRegistry()
        router = Router(registry)
        adapter = FakeAdapter()
        target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=9999)

        session = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=True
        )

        self.assertEqual(adapter.launch_or_attach_calls, 1)
        self.assertEqual(session.pid, 9999)
        self.assertIn(session, registry.all_sessions())

    def test_scenario_c_existing_session_is_reused_never_duplicated(self):
        # GW-06-C / GW-04: an existing session always wins; no second debugger.
        registry = SessionRegistry()
        router = Router(registry)
        adapter = FakeAdapter()
        target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=4210)

        first = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=False
        )
        self.assertEqual(adapter.launch_or_attach_calls, 1)

        # Ask again for the same target, this time claiming it's already
        # running (process_running flips) — must reuse, not launch/attach again.
        second = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=True
        )

        self.assertIs(second, first)
        self.assertEqual(adapter.launch_or_attach_calls, 1, "a second debugger must never be launched")
        self.assertEqual(len(registry.all_sessions()), 1)

    def test_scenario_d_unsupported_operation_declines_without_touching_the_adapter(self):
        # GW-06-D / GW-04-A: adapter can't launch or attach -> decline cleanly.
        registry = SessionRegistry()
        router = Router(registry)
        adapter = FakeAdapter(can_launch_or_attach=False)
        target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)

        with self.assertRaises(AutoDebugError) as ctx:
            router.arm_target(
                adapter,
                capable_report(adapter, can_launch=False),
                target,
                reviewed_configuration=None,
                process_running=False,
            )

        self.assertEqual(ctx.exception.detail.code, ErrorCode.CAPABILITY_UNSUPPORTED)
        self.assertEqual(adapter.launch_or_attach_calls, 0, "an unsupported op must never reach the adapter")
        self.assertEqual(registry.all_sessions(), ())

    def test_wrong_adapter_for_target_ide_is_rejected(self):
        # GW-04: AutoDebug must operate on the requested IDE's own debugger,
        # never silently substitute a different adapter.
        registry = SessionRegistry()
        router = Router(registry)
        adapter = FakeAdapter()  # adapter.ide_id == "fake"
        target = TargetRef(host_id="local-mac", ide="clion", debug_session_id=None, pid=None)

        with self.assertRaises(AutoDebugError) as ctx:
            router.arm_target(
                adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=False
            )

        self.assertEqual(ctx.exception.detail.code, ErrorCode.TARGET_MISMATCH)
        self.assertEqual(adapter.launch_or_attach_calls, 0)


class TestCapabilityReportDrivesTheDecision(unittest.TestCase):
    def test_capability_report_operations_reflect_the_fake_backend_used(self):
        adapter = FakeAdapter()
        report = capable_report(adapter, can_launch=True)
        self.assertEqual(report.operations["launch_or_attach"], CapabilityState.AVAILABLE)

        report = capable_report(adapter, can_launch=False)
        self.assertEqual(report.state, CapabilityState.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
