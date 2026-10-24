"""T08 acceptance tests — VS Code adapter integration (GW-04, GW-06, IDE-03,
IDE-04). Stdlib `unittest` only, zero third-party packages, no MCP SDK.

Every test here runs against `FakeDebugMCPClient` — a mocked stand-in for a
real DebugMCP connection (`docs/vscode-debugmcp-mapping.md`'s unknowns are
unresolved; DebugMCP itself is not installed in this environment, confirmed
by filesystem check — see `tasks.md` T08). Nothing here contacts a real IDE,
installs anything, or opens a real debugger connection. Authorization-gate
regression tests prove that implementing this adapter does not loosen the
T05 security gate, which remains OPEN / NOT APPROVED.
"""

import inspect
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

from autodebug.adapters.base import CORE_OPERATIONS
from autodebug.adapters.vscode import DebugMCPClient, RemoteSessionInfo, VSCodeAdapter
from autodebug.approvals import ApprovalBroker, authorize_and_arm
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.evidence import REDACTED_PLACEHOLDER
from autodebug.facade import AutoDebugFacade
from autodebug.models import Breakpoint, CasePlan, CasePolicy, IntakeSource, ReproductionPlan, TargetRef
from autodebug.plans import stage_plan
from autodebug.router import Router
from autodebug.sessions import SessionRegistry
from tests.fixtures.fake_backend import FULL_SUPPORT, NOT_INSTALLED
from tests.fixtures.fake_debugmcp_client import FakeDebugMCPClient


def capable_report(adapter: VSCodeAdapter, *, can_launch: bool = True):
    if can_launch:
        backend = FULL_SUPPORT
    else:
        from autodebug.adapters.base import CORE_OPERATIONS as _OPS
        from tests.fixtures.fake_backend import FakeBackend

        backend = FakeBackend(supported_operations=frozenset(_OPS) - {"launch_or_attach"})
    return adapter.probe_capabilities(backend=backend, host_os="Darwin")


def make_plan(**overrides) -> CasePlan:
    defaults = dict(
        schema_version="0.1-draft",
        case_id="CASE-2026-T08",
        source_revision="abc123",
        target=TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None),
        breakpoints=(Breakpoint(file="/repo/src/app.py", line=10),),
        reproduction=ReproductionPlan(mode="manual", steps=("Open a disposable design",)),
        policy=CasePolicy(max_steps=20, max_inspection_seconds=300),
        digest_sha256=None,
    )
    defaults.update(overrides)
    return stage_plan(CasePlan(**defaults))


class TestNoClientFailsClosed(unittest.TestCase):
    """IDE-03-A: bridge absent -> UNAVAILABLE, not a bare NotImplementedError
    and never an invented success."""

    def test_zero_argument_construction_still_works(self):
        # test_adapters.py's enumeration test instantiates every adapter
        # with cls() — this must keep working.
        adapter = VSCodeAdapter()
        self.assertEqual(adapter.ide_id, "vscode")
        self.assertTrue(adapter.supported_os)

    def test_every_operation_reports_backend_unavailable_without_a_client(self):
        adapter = VSCodeAdapter()
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)
        ops = [
            lambda: adapter.list_sessions(),
            lambda: adapter.launch_or_attach(target, None),
            lambda: adapter.is_paused("x"),
        ]
        for op in ops:
            with self.assertRaises(AutoDebugError) as ctx:
                op()
            self.assertEqual(ctx.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)


class TestSessionDiscoveryAndTranslation(unittest.TestCase):
    def test_launch_or_attach_translates_remote_info_to_a_session_ref(self):
        client = FakeDebugMCPClient()
        adapter = VSCodeAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=4242)

        session = adapter.launch_or_attach(target, reviewed_configuration=None)

        self.assertEqual(session.host_id, "local-mac")
        self.assertEqual(session.ide, "vscode")
        self.assertEqual(session.pid, 4242)
        self.assertTrue(session.ide_instance_id)
        self.assertTrue(session.debug_session_id)
        self.assertEqual(session.session_generation, 1)

    def test_list_sessions_reflects_the_client(self):
        client = FakeDebugMCPClient()
        adapter = VSCodeAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)
        adapter.launch_or_attach(target, None)

        sessions = adapter.list_sessions()
        self.assertEqual(len(sessions), 1)

    def test_generation_is_assigned_locally_when_client_reports_none(self):
        # docs/vscode-debugmcp-mapping.md unknown #2: DebugMCP's ability to
        # report a stable generation is unverified; the adapter must track
        # its own fallback rather than crash or silently default to a
        # constant that could mask a real identity change.
        client = FakeDebugMCPClient()
        adapter = VSCodeAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)
        a = adapter.launch_or_attach(target, None)
        b = adapter.launch_or_attach(target, None)
        self.assertNotEqual(a.debug_session_id, b.debug_session_id)
        self.assertEqual(a.session_generation, 1)
        self.assertEqual(b.session_generation, 2)


class TestGW06ScenariosAgainstRouter(unittest.TestCase):
    """Driven directly through Router/SessionRegistry, independent of the
    approval gate — per the developer's instruction to implement and prove
    the adapter integration independently of that gate where possible."""

    def test_scenario_a_launch(self):
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeDebugMCPClient()
        adapter = VSCodeAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)

        session = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=False
        )
        self.assertEqual(client.start_or_attach_calls, 1)
        self.assertIn(session, registry.all_sessions())

    def test_scenario_b_attach(self):
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeDebugMCPClient()
        adapter = VSCodeAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=9999)

        session = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=True
        )
        self.assertEqual(client.start_or_attach_calls, 1)
        self.assertEqual(session.pid, 9999)

    def test_scenario_c_existing_session_reused_no_hidden_second_session(self):
        # IDE-04-B point 8: confirm no hidden second debugger session.
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeDebugMCPClient()
        adapter = VSCodeAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=4210)

        first = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=False
        )
        self.assertEqual(client.start_or_attach_calls, 1)

        second = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=True
        )
        self.assertIs(second, first)
        self.assertEqual(client.start_or_attach_calls, 1, "a second debugger session must never be created")
        self.assertEqual(len(registry.all_sessions()), 1)

    def test_scenario_d_decline_when_unsupported(self):
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeDebugMCPClient(can_start_or_attach=False)
        adapter = VSCodeAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)

        with self.assertRaises(AutoDebugError) as ctx:
            router.arm_target(
                adapter,
                capable_report(adapter, can_launch=False),
                target,
                reviewed_configuration=None,
                process_running=False,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.CAPABILITY_UNSUPPORTED)
        self.assertEqual(client.start_or_attach_calls, 0, "an unsupported op must never reach the client")
        self.assertEqual(registry.all_sessions(), ())


class TestBreakpointStackVariablesStepContinue(unittest.TestCase):
    """RP-06 binding, stack inspection, variable reads, stepping and
    continuation — IDE-04-B points 2, 4, 5, 6."""

    def setUp(self):
        self.client = FakeDebugMCPClient()
        self.adapter = VSCodeAdapter(client=self.client)
        self.target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)
        self.session = self.adapter.launch_or_attach(self.target, None)

    def test_breakpoint_binding_confirmed(self):
        breakpoints = (Breakpoint(file="/repo/app.py", line=10), Breakpoint(file="/repo/app.py", line=20))
        results = self.adapter.set_breakpoints(self.session, breakpoints)
        self.assertTrue(all(r.bound for r in results))
        self.assertEqual(len(results), 2)

    def test_breakpoint_binding_failure_is_reported_not_assumed(self):
        client = FakeDebugMCPClient(can_bind_breakpoints=False)
        adapter = VSCodeAdapter(client=client)
        session = adapter.launch_or_attach(self.target, None)
        results = adapter.set_breakpoints(session, (Breakpoint(file="/repo/app.py", line=10),))
        self.assertFalse(results[0].bound)
        self.assertTrue(results[0].reason)

    def test_debugger_stop_detected_via_is_paused(self):
        self.assertFalse(self.adapter.is_paused(self.session.debug_session_id))
        self.client.simulate_stop(self.session.debug_session_id)
        self.assertTrue(self.adapter.is_paused(self.session.debug_session_id))

    def test_wait_for_stop_returns_once_paused(self):
        self.client.simulate_stop(self.session.debug_session_id)
        self.adapter.wait_for_stop(self.session, timeout=1.0)  # must not raise

    def test_wait_for_stop_times_out_when_never_paused(self):
        with self.assertRaises(AutoDebugError) as ctx:
            self.adapter.wait_for_stop(self.session, timeout=0.05)
        self.assertEqual(ctx.exception.detail.code, ErrorCode.TIMEOUT)

    def test_stack_inspection(self):
        self.client.simulate_stop(self.session.debug_session_id)
        frames = self.adapter.get_stack(self.session, frame_limit=2)
        self.assertEqual(len(frames), 2)

    def test_variable_read_returns_raw_unredacted_value(self):
        # DE-07 redaction happens once, at the facade layer — the adapter
        # must return the raw value, exactly like FakeAdapter does, so
        # there is exactly one redaction point, not a second divergent one.
        self.client.simulate_stop(self.session.debug_session_id)
        variables = self.adapter.get_variables(self.session, "frame-0", ("password",))
        self.assertEqual(variables["password"], "hunter2")
        self.assertNotEqual(variables["password"], REDACTED_PLACEHOLDER)

    def test_step_and_continue_do_not_raise(self):
        self.client.simulate_stop(self.session.debug_session_id)
        self.adapter.step(self.session, "step_over")
        self.adapter.continue_execution(self.session)
        self.assertFalse(self.adapter.is_paused(self.session.debug_session_id))

    def test_disconnect_removes_the_session_and_does_not_relaunch(self):
        self.adapter.disconnect(self.session)
        self.assertEqual(self.client.disconnect_calls, 1)
        self.assertEqual(self.adapter.list_sessions(), ())


class TestCapabilityProbingIndependentOfClient(unittest.TestCase):
    """`probe_capabilities()` is inherited unchanged from `BaseAdapter` and
    never touches `self._client` — capability discovery (GW-02) and live
    reachability (`BACKEND_UNAVAILABLE`) are deliberately independent
    checks."""

    def test_unknown_before_any_backend_description(self):
        adapter = VSCodeAdapter()  # no client either
        report = adapter.probe_capabilities(backend=None, host_os="Darwin")
        from autodebug.models import CapabilityState

        self.assertEqual(report.state, CapabilityState.UNKNOWN)

    def test_not_installed_backend_reports_unavailable(self):
        adapter = VSCodeAdapter()
        report = adapter.probe_capabilities(backend=NOT_INSTALLED, host_os="Darwin")
        from autodebug.models import CapabilityState

        self.assertEqual(report.state, CapabilityState.UNAVAILABLE)

    def test_full_support_backend_reports_available_for_every_core_operation(self):
        adapter = VSCodeAdapter(client=FakeDebugMCPClient())
        report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")
        from autodebug.models import CapabilityState

        for op in CORE_OPERATIONS:
            with self.subTest(op):
                self.assertEqual(report.operations[op], CapabilityState.AVAILABLE)


class TestAuthorizationGateStillBlocksVSCode(unittest.TestCase):
    """Binding regression: implementing a real `VSCodeAdapter` must not
    loosen the T05 security gate. `ApprovalBroker.verify_approval` must
    still unconditionally refuse `backend_kind != "fake"`, even though the
    adapter can now actually perform every operation."""

    def test_authorize_and_arm_refuses_a_fully_wired_real_adapter(self):
        def now():
            return 1000.0

        tokens = iter(f"token-{i}" for i in range(1, 10))
        broker = ApprovalBroker(now=now, make_token=lambda: next(tokens))
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeDebugMCPClient()
        real_adapter = VSCodeAdapter(client=client)  # fully wired, not a bare stub
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)
        plan = make_plan(target=target)

        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind="fake",  # only ever reviewed/issued for the fake backend
            target_identity="local-mac/vscode/None",
            scope=("op:arm_case",),
            ttl_seconds=60.0,
            human_presence_confirmed=True,
        )

        with self.assertRaises(AutoDebugError) as ctx:
            authorize_and_arm(
                broker,
                approval,
                plan=plan,
                target_identity="local-mac/vscode/None",
                required_scope="op:arm_case",
                router=router,
                adapter=real_adapter,
                capability_report=capable_report(real_adapter),
                target=target,
                reviewed_configuration=None,
                process_running=False,
            )
        self.assertIn(ctx.exception.detail.code, (ErrorCode.TARGET_MISMATCH, ErrorCode.PERMISSION_DENIED))
        self.assertEqual(client.start_or_attach_calls, 0, "the real client must never be reached")
        self.assertEqual(registry.all_sessions(), ())

    def test_facade_never_calls_bare_router_arm_target_remains_true(self):
        # Re-confirm T07's structural guard still holds with this new
        # adapter in the picture — the facade module itself is unchanged,
        # but this documents the regression is checked again here too.
        from autodebug import facade as facade_module

        source = inspect.getsource(facade_module.AutoDebugFacade.autodebug_arm_case)
        self.assertNotIn("self._router.arm_target(", source)


class TestFacadeRedactionBoundaryWithRealAdapter(unittest.TestCase):
    """DE-07/RP-04: manually injected sessions never authorize sensitive reads.

    Walking the state machine is test-only setup, not broker approval.
    Even a broker-issued real-backend approval must fail the open gate.
    Direct adapter protocol and approved fake-facade tests cover redaction.
    """

    def test_unapproved_real_facade_reads_and_wait_are_refused_without_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = SessionRegistry()
            broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: "unused-token")
            facade = AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=Path(tmp))

            client = FakeDebugMCPClient()
            adapter = VSCodeAdapter(client=client)
            target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)
            case_id = "CASE-2026-T08-REDACTION"
            plan = make_plan(case_id=case_id, target=target)

            created = facade.autodebug_create_case(
                case_id=case_id,
                intake_source=IntakeSource.DEVELOPER_TEXT,
                intake_description="T08 redaction-boundary check",
                adapter=adapter,
                target=target,
            )
            self.assertTrue(created["ok"], created)
            staged = facade.autodebug_stage_plan(case_id=case_id, plan=plan)
            self.assertTrue(staged["ok"], staged)
            digest = staged["result"]["digest_sha256"]

            # State-machine setup cannot substitute for broker authorization.
            ctx = facade._cases[case_id]
            ctx.case.mark_approved(digest)
            ctx.case.begin_arming()
            session = adapter.launch_or_attach(target, reviewed_configuration=None)
            registry.register(session)  # Router.arm_target would normally do this
            ctx.session = session
            ctx.case.confirm_session()
            binding_results = adapter.set_breakpoints(session, ctx.case.plan.breakpoints)
            ctx.case.bind_breakpoints(binding_results)
            ctx.case.begin_reproduction()
            from autodebug.evidence import EvidenceStore

            ctx.evidence_store = EvidenceStore(Path(tmp), case_id)

            client.simulate_stop(session.debug_session_id)
            ctx.case.pause()
            approval = broker.issue_approval(
                ctx.case.plan,
                reviewer="dev",
                backend_kind=adapter.ide_id,
                target_identity=f"{target.host_id}/{target.ide}/{target.pid}",
                scope=("op:arm_case",),
                ttl_seconds=60.0,
                human_presence_confirmed=True,
            )
            with (
                patch.object(client, "get_variables", side_effect=AssertionError("unauthorized variable read")) as variables,
                patch.object(client, "get_stack", side_effect=AssertionError("unauthorized stack read")) as stack,
                patch.object(client, "is_paused", side_effect=AssertionError("unauthorized pause query")) as paused,
            ):
                for stored_approval, expected in ((None, "NOT_APPROVED"), (approval, "PERMISSION_DENIED")):
                    with self.subTest(approval=expected):
                        ctx.approval = stored_approval
                        results = (
                            facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=1.0),
                            facade.autodebug_get_stack(case_id=case_id, frame_limit=1),
                            facade.autodebug_get_variables(
                                case_id=case_id, frame_id="frame-0", selected_names=("password", "local_var")
                            ),
                        )
                        for result in results:
                            self.assertFalse(result["ok"], result)
                            self.assertEqual(result["error"]["code"], expected)
                            self.assertNotIn("result", result)
                            self.assertNotIn("hunter2", repr(result))
                        self.assertEqual(ctx.case.state.value, "paused")
                variables.assert_not_called()
                stack.assert_not_called()
                paused.assert_not_called()
            self.assertEqual(ctx.evidence_store.read_events(), ())
            for path in (Path(tmp) / case_id).iterdir():
                if path.is_file():
                    self.assertNotIn(b"hunter2", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
