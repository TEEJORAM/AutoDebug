"""T12 acceptance tests — Visual Studio adapter integration (GW-06, IDE-02,
IDE-03, IDE-04). Stdlib `unittest` only, zero third-party packages, no MCP
SDK.

Every test here runs against `FakeVisualStudioDebugClient` — a mocked
stand-in for a real Visual Studio debugger connection (an Autodesk-approved
internal bridge, or an independently authored public-API/EnvDTE
extension). Capability-probing tests inject Windows, Darwin, and Linux
host names deterministically, independent of the test runner's OS.
These probes do not claim an actual Windows connection. Nothing here
contacts a real IDE, installs anything, or opens a real debugger
connection. Authorization-gate regression tests prove that implementing
this adapter does not loosen the T05 security gate, which remains
OPEN / NOT APPROVED.
"""

import inspect
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from autodebug.adapters.base import CORE_OPERATIONS
from autodebug.adapters.visual_studio import RemoteSessionInfo, VisualStudioAdapter, VisualStudioDebugClient
from autodebug.approvals import ApprovalBroker, authorize_and_arm
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.evidence import REDACTED_PLACEHOLDER, EvidenceStore
from autodebug.facade import AutoDebugFacade
from autodebug.models import ApprovalRecord, Breakpoint, CasePlan, CasePolicy, IntakeSource, ReproductionPlan, TargetRef
from autodebug.plans import stage_plan
from autodebug.router import Router
from autodebug.sessions import SessionRegistry
from tests.fixtures.fake_backend import FULL_SUPPORT, NOT_INSTALLED
from tests.fixtures.fake_visual_studio_client import FakeVisualStudioDebugClient


def dummy_approval(case_id: str) -> ApprovalRecord:
    """A placeholder `ApprovalRecord` for tests that only need to reach a
    facade check that happens *before* the approval is ever inspected
    (e.g. `_verify_session`'s SESSION_STALE/TARGET_MISMATCH checks, which
    run ahead of `ApprovalBroker.verify_approval` in `autodebug_step`/
    `autodebug_continue`). Never accepted by the real broker."""
    return ApprovalRecord(case_id=case_id, plan_digest="unused", reviewer="unused", expiration="0", scope=(), token="unused")


def _arm_vs_case_and_pause(registry: SessionRegistry, facade: AutoDebugFacade, case_id: str, client: FakeVisualStudioDebugClient):
    """Inject a mocked session and paused state, never broker authorization."""
    adapter = VisualStudioAdapter(client=client)
    target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
    plan = make_plan(case_id=case_id, target=target)
    facade.autodebug_create_case(
        case_id=case_id,
        intake_source=IntakeSource.DEVELOPER_TEXT,
        intake_description="T12 facade-boundary check",
        adapter=adapter,
        target=target,
    )
    staged = facade.autodebug_stage_plan(case_id=case_id, plan=plan)
    digest = staged["result"]["digest_sha256"]
    ctx = facade._cases[case_id]
    ctx.case.mark_approved(digest)
    ctx.case.begin_arming()
    session = adapter.launch_or_attach(target, reviewed_configuration=None)
    registry.register(session)
    ctx.session = session
    ctx.case.confirm_session()
    binding_results = adapter.set_breakpoints(session, ctx.case.plan.breakpoints)
    ctx.case.bind_breakpoints(binding_results)
    ctx.case.begin_reproduction()
    client.simulate_stop(session.debug_session_id)
    ctx.case.pause()
    return adapter, session


def capable_report(adapter: VisualStudioAdapter, *, can_launch: bool = True):
    # Visual Studio is Windows-only; host_os is forced to "Windows" here so
    # the adapter's own operation-level logic can be exercised on any
    # test runner — this does not claim a real Windows
    # connection, only that the adapter is being probed as if on one.
    if can_launch:
        backend = FULL_SUPPORT
    else:
        from tests.fixtures.fake_backend import FakeBackend

        backend = FakeBackend(supported_operations=frozenset(CORE_OPERATIONS) - {"launch_or_attach"})
    return adapter.probe_capabilities(backend=backend, host_os="Windows")


def make_plan(**overrides) -> CasePlan:
    defaults = dict(
        schema_version="0.1-draft",
        case_id="CASE-2026-T12",
        source_revision="abc123",
        target=TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None),
        breakpoints=(Breakpoint(file="/repo/src/app.cs", line=10),),
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
        adapter = VisualStudioAdapter()
        self.assertEqual(adapter.ide_id, "visual_studio")
        self.assertTrue(adapter.supported_os)

    def test_every_operation_reports_backend_unavailable_without_a_client(self):
        adapter = VisualStudioAdapter()
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
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
        client = FakeVisualStudioDebugClient()
        adapter = VisualStudioAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=4242)

        session = adapter.launch_or_attach(target, reviewed_configuration=None)

        self.assertEqual(session.host_id, "local-mac")
        self.assertEqual(session.ide, "visual_studio")
        self.assertEqual(session.pid, 4242)
        self.assertTrue(session.ide_instance_id)
        self.assertTrue(session.debug_session_id)
        self.assertEqual(session.session_generation, 1)

    def test_list_sessions_reflects_the_client(self):
        client = FakeVisualStudioDebugClient()
        adapter = VisualStudioAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
        adapter.launch_or_attach(target, None)

        sessions = adapter.list_sessions()
        self.assertEqual(len(sessions), 1)

    def test_generation_is_assigned_locally_when_client_reports_none(self):
        client = FakeVisualStudioDebugClient()
        adapter = VisualStudioAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
        a = adapter.launch_or_attach(target, None)
        b = adapter.launch_or_attach(target, None)
        self.assertNotEqual(a.debug_session_id, b.debug_session_id)
        self.assertEqual(a.session_generation, 1)
        self.assertEqual(b.session_generation, 2)


class TestGW06ScenariosAgainstRouter(unittest.TestCase):
    """Driven directly through Router/SessionRegistry, independent of the
    approval gate."""

    def test_scenario_a_launch(self):
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeVisualStudioDebugClient()
        adapter = VisualStudioAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)

        session = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=False
        )
        self.assertEqual(client.start_or_attach_calls, 1)
        self.assertIn(session, registry.all_sessions())

    def test_scenario_b_attach(self):
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeVisualStudioDebugClient()
        adapter = VisualStudioAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=9999)

        session = router.arm_target(
            adapter, capable_report(adapter), target, reviewed_configuration=None, process_running=True
        )
        self.assertEqual(client.start_or_attach_calls, 1)
        self.assertEqual(session.pid, 9999)

    def test_scenario_c_existing_session_reused_no_hidden_second_session(self):
        # IDE-04-B point 8: confirm no hidden second debugger session.
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeVisualStudioDebugClient()
        adapter = VisualStudioAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=4210)

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
        client = FakeVisualStudioDebugClient(can_start_or_attach=False)
        adapter = VisualStudioAdapter(client=client)
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)

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
        self.client = FakeVisualStudioDebugClient()
        self.adapter = VisualStudioAdapter(client=self.client)
        self.target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
        self.session = self.adapter.launch_or_attach(self.target, None)

    def test_breakpoint_binding_confirmed(self):
        breakpoints = (Breakpoint(file="/repo/app.cs", line=10), Breakpoint(file="/repo/app.cs", line=20))
        results = self.adapter.set_breakpoints(self.session, breakpoints)
        self.assertTrue(all(r.bound for r in results))
        self.assertEqual(len(results), 2)

    def test_breakpoint_binding_failure_is_reported_not_assumed(self):
        client = FakeVisualStudioDebugClient(can_bind_breakpoints=False)
        adapter = VisualStudioAdapter(client=client)
        session = adapter.launch_or_attach(self.target, None)
        results = adapter.set_breakpoints(session, (Breakpoint(file="/repo/app.cs", line=10),))
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


class TestNeverSpawnsAnIndependentDebuggerProcess(unittest.TestCase):
    """`docs/ide-integrations.md` section D: `VisualStudioAdapter` must use
    Visual Studio's own native debugger session via an approved bridge or
    extension, never spawn an independent debugger process itself."""

    def test_module_source_contains_no_process_spawning_code(self):
        import autodebug.adapters.visual_studio as vs_module

        source = inspect.getsource(vs_module).lower()
        for forbidden in ("subprocess", "os.system", "popen"):
            with self.subTest(forbidden):
                self.assertNotIn(forbidden, source)


class TestCapabilityProbingIndependentOfClient(unittest.TestCase):
    def test_unknown_before_any_backend_description(self):
        adapter = VisualStudioAdapter()
        report = adapter.probe_capabilities(backend=None, host_os="Windows")
        from autodebug.models import CapabilityState

        self.assertEqual(report.state, CapabilityState.UNKNOWN)

    def test_not_installed_backend_reports_unavailable(self):
        adapter = VisualStudioAdapter()
        report = adapter.probe_capabilities(backend=NOT_INSTALLED, host_os="Windows")
        from autodebug.models import CapabilityState

        self.assertEqual(report.state, CapabilityState.UNAVAILABLE)

    def test_full_support_backend_reports_available_for_every_core_operation(self):
        adapter = VisualStudioAdapter(client=FakeVisualStudioDebugClient())
        report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Windows")
        from autodebug.models import CapabilityState

        for op in CORE_OPERATIONS:
            with self.subTest(op):
                self.assertEqual(report.operations[op], CapabilityState.AVAILABLE)

    def test_injected_host_os_reports_deterministic_applicability(self):
        adapter = VisualStudioAdapter(client=FakeVisualStudioDebugClient())
        from autodebug.models import CapabilityState

        for host_os in ("Windows", "Darwin", "Linux"):
            with self.subTest(host_os=host_os):
                report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os=host_os)
                if host_os == "Windows":
                    self.assertEqual(report.state, CapabilityState.AVAILABLE)
                    self.assertEqual(
                        report.operations, {op: CapabilityState.AVAILABLE for op in CORE_OPERATIONS}
                    )
                else:
                    self.assertEqual(report.state, CapabilityState.NOT_APPLICABLE)
                    self.assertEqual(report.operations, {})


class TestAuthorizationGateStillBlocksVisualStudio(unittest.TestCase):
    """Binding regression: implementing a real `VisualStudioAdapter` must
    not loosen the T05 security gate."""

    def test_authorize_and_arm_refuses_a_fully_wired_real_adapter(self):
        def now():
            return 1000.0

        tokens = iter(f"token-{i}" for i in range(1, 10))
        broker = ApprovalBroker(now=now, make_token=lambda: next(tokens))
        registry = SessionRegistry()
        router = Router(registry)
        client = FakeVisualStudioDebugClient()
        real_adapter = VisualStudioAdapter(client=client)  # fully wired, not a bare stub
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
        plan = make_plan(target=target)

        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind="fake",  # only ever reviewed/issued for the fake backend
            target_identity="local-mac/visual_studio/None",
            scope=("op:arm_case",),
            ttl_seconds=60.0,
            human_presence_confirmed=True,
        )

        with self.assertRaises(AutoDebugError) as ctx:
            authorize_and_arm(
                broker,
                approval,
                plan=plan,
                target_identity="local-mac/visual_studio/None",
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

            client = FakeVisualStudioDebugClient()
            adapter = VisualStudioAdapter(client=client)
            target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
            case_id = "CASE-2026-T12-REDACTION"
            plan = make_plan(case_id=case_id, target=target)

            created = facade.autodebug_create_case(
                case_id=case_id,
                intake_source=IntakeSource.DEVELOPER_TEXT,
                intake_description="T12 redaction-boundary check",
                adapter=adapter,
                target=target,
            )
            self.assertTrue(created["ok"], created)
            staged = facade.autodebug_stage_plan(case_id=case_id, plan=plan)
            self.assertTrue(staged["ok"], staged)
            digest = staged["result"]["digest_sha256"]

            ctx = facade._cases[case_id]
            ctx.case.mark_approved(digest)
            ctx.case.begin_arming()
            session = adapter.launch_or_attach(target, reviewed_configuration=None)
            registry.register(session)
            ctx.session = session
            ctx.case.confirm_session()
            binding_results = adapter.set_breakpoints(session, ctx.case.plan.breakpoints)
            ctx.case.bind_breakpoints(binding_results)
            ctx.case.begin_reproduction()
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


class TestStaleSessionIdentityWithRealVisualStudioAdapter(unittest.TestCase):
    """GW-03-B, re-applied at the facade layer (`_verify_session`), proven
    with a real `VisualStudioAdapter` session."""

    def test_exited_session_blocks_get_stack_get_variables_step_and_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = SessionRegistry()
            broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: "unused-token")
            facade = AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=Path(tmp))
            client = FakeVisualStudioDebugClient()
            case_id = "CASE-2026-T12-STALE"
            adapter, session = _arm_vs_case_and_pause(registry, facade, case_id, client)
            registry.unregister(session)  # simulates the process/session exiting
            approval = dummy_approval(case_id)

            stack = facade.autodebug_get_stack(case_id=case_id, frame_limit=1)
            self.assertFalse(stack["ok"])
            self.assertEqual(stack["error"]["code"], "SESSION_STALE")
            self.assertEqual(
                facade._cases[case_id].case.state.value,
                "incomplete",
                "DE-08: first disconnect must label the case incomplete",
            )

            variables = facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
            self.assertFalse(variables["ok"])
            self.assertEqual(variables["error"]["code"], "SESSION_STALE")

            stepped = facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
            self.assertFalse(stepped["ok"])
            self.assertEqual(stepped["error"]["code"], "NOT_PAUSED")

            resumed = facade.autodebug_continue(case_id=case_id, approval=approval)
            self.assertFalse(resumed["ok"])
            self.assertEqual(resumed["error"]["code"], "NOT_PAUSED")

    def test_reassigned_session_identity_blocks_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = SessionRegistry()
            broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: "unused-token")
            facade = AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=Path(tmp))
            client = FakeVisualStudioDebugClient()
            case_id = "CASE-2026-T12-REASSIGNED"
            adapter, session = _arm_vs_case_and_pause(registry, facade, case_id, client)

            reassigned = replace(session, session_generation=session.session_generation + 1)
            registry.register(reassigned)  # same key, different identity fields

            stepped = facade.autodebug_step(case_id=case_id, approval=dummy_approval(case_id), kind="step_over")
            self.assertFalse(stepped["ok"])
            self.assertEqual(stepped["error"]["code"], "TARGET_MISMATCH")
            # T14 security review: a reused/reassigned identity is a
            # security concern distinct from DE-08's disconnect trigger --
            # it must never mark the case INCOMPLETE.
            self.assertEqual(facade._cases[case_id].case.state.value, "paused")


class TestBreakpointBindingFailureRollbackWithRealVisualStudioAdapter(unittest.TestCase):
    """RP-06/`BREAKPOINT_UNBOUND`: `facade._rollback_failed_arming` must
    clean up a real `VisualStudioAdapter` session exactly as it does
    `FakeAdapter` (T07) — a real adapter's `ide_id` means
    `autodebug_arm_case`'s full public path always refuses at the
    (correct, by-design) authorization step before ever reaching binding,
    so this test exercises the rollback helper directly against a real,
    live Visual Studio session."""

    def test_failed_binding_disconnects_unregisters_and_revokes(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = SessionRegistry()
            broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: "unused-token")
            facade = AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=Path(tmp))
            client = FakeVisualStudioDebugClient()
            case_id = "CASE-2026-T12-ROLLBACK"
            adapter = VisualStudioAdapter(client=client)
            target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
            plan = make_plan(case_id=case_id, target=target)
            facade.autodebug_create_case(
                case_id=case_id,
                intake_source=IntakeSource.DEVELOPER_TEXT,
                intake_description="T12 rollback check",
                adapter=adapter,
                target=target,
            )
            facade.autodebug_stage_plan(case_id=case_id, plan=plan)
            ctx = facade._cases[case_id]

            session = adapter.launch_or_attach(target, reviewed_configuration=None)
            registry.register(session)
            approval_record = broker.issue_approval(
                plan,
                reviewer="dev",
                backend_kind="fake",
                target_identity="local-mac/visual_studio/None",
                scope=("op:arm_case",),
                ttl_seconds=60.0,
                human_presence_confirmed=True,
            )
            facade._rollback_failed_arming(ctx, session)

            self.assertEqual(registry.all_sessions(), (), "the session must not be left live/registered")
            self.assertEqual(client.disconnect_calls, 1)
            self.assertEqual(ctx.case.state.value, "failed")
            self.assertIsNone(ctx.session)
            with self.assertRaises(AutoDebugError) as broker_ctx:
                broker.verify_approval(
                    approval_record,
                    plan=plan,
                    backend_kind="fake",
                    target_identity="local-mac/visual_studio/None",
                    required_scope="op:arm_case",
                )
            self.assertEqual(broker_ctx.exception.detail.code, ErrorCode.CANCELLED)


class TestCancellationAndStepBudgetWithRealVisualStudioAdapter(unittest.TestCase):
    """DE-09 cancellation and DE-03 step-budget enforcement, proven with a
    real `VisualStudioAdapter` session."""

    def test_unapproved_wait_is_refused_before_cancellation_still_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = SessionRegistry()
            broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: "unused-token")
            facade = AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=Path(tmp))
            client = FakeVisualStudioDebugClient()
            case_id = "CASE-2026-T12-CANCEL"
            adapter = VisualStudioAdapter(client=client)
            target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
            plan = make_plan(case_id=case_id, target=target)
            facade.autodebug_create_case(
                case_id=case_id,
                intake_source=IntakeSource.DEVELOPER_TEXT,
                intake_description="T12 cancellation check",
                adapter=adapter,
                target=target,
            )
            facade.autodebug_stage_plan(case_id=case_id, plan=plan)
            ctx = facade._cases[case_id]
            ctx.case.mark_approved(plan.digest_sha256)
            ctx.case.begin_arming()
            session = adapter.launch_or_attach(target, None)
            registry.register(session)
            ctx.session = session
            ctx.case.confirm_session()
            ctx.case.bind_breakpoints(adapter.set_breakpoints(session, plan.breakpoints))
            ctx.case.begin_reproduction()
            with (
                patch.object(client, "is_paused", side_effect=AssertionError("unauthorized pause query")) as paused,
                patch.object(facade, "_sleep", side_effect=AssertionError("unauthorized wait polled")) as sleep,
            ):
                waited = facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=10.0)
                self.assertFalse(waited["ok"], waited)
                self.assertEqual(waited["error"]["code"], "NOT_APPROVED")
                paused.assert_not_called()
                sleep.assert_not_called()
            self.assertEqual(ctx.case.state.value, "awaiting_developer_reproduction")
            cancelled = facade.autodebug_cancel_case(case_id=case_id)
            self.assertTrue(cancelled["ok"], cancelled)
            self.assertTrue(ctx.cancel_event.is_set())
            self.assertEqual(ctx.case.state.value, "cancelled")

    def test_step_is_also_unconditionally_refused_for_a_real_adapter(self):
        # DE-03's step-budget check in `autodebug_step` runs *after*
        # `ApprovalBroker.verify_approval` — which means, by design, it is
        # structurally unreachable for any adapter whose `ide_id != "fake"`:
        # the backend-kind gate refuses the call before the budget is ever
        # consulted. DE-03 itself remains exercised against `FakeAdapter`
        # in `test_facade.py` (ide_id == "fake"), where the gate does open.
        with tempfile.TemporaryDirectory() as tmp:
            registry = SessionRegistry()
            broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: "unused-token")
            facade = AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=Path(tmp))
            client = FakeVisualStudioDebugClient()
            case_id = "CASE-2026-T12-STEPGATE"
            adapter, session = _arm_vs_case_and_pause(registry, facade, case_id, client)
            ctx = facade._cases[case_id]

            approval = broker.issue_approval(
                ctx.case.plan,
                reviewer="dev",
                backend_kind="visual_studio",
                target_identity="local-mac/visual_studio/None",  # matches target_identity_for(ctx.target)
                scope=("op:step",),
                ttl_seconds=60.0,
                human_presence_confirmed=True,
            )
            stepped = facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
            self.assertFalse(stepped["ok"])
            self.assertEqual(stepped["error"]["code"], "PERMISSION_DENIED")
            self.assertEqual(ctx.steps_taken, 0, "the step budget counter must never advance on a refused call")


class TestVisualStudioAdapterDoesNotShareOtherAdaptersProtocol(unittest.TestCase):
    """IDE-03: Visual Studio must be tested and typed independently from
    VS Code, Cursor, CLion, and Xcode — no shared client Protocol,
    RemoteSessionInfo instance, or ide_id, and a client built for one must
    not satisfy another's type."""

    def test_visual_studio_uses_a_distinct_client_protocol_from_the_others(self):
        from autodebug.adapters.clion import CLionDebugClient
        from autodebug.adapters.cursor import CursorDebugClient
        from autodebug.adapters.vscode import DebugMCPClient
        from autodebug.adapters.xcode import XcodeDebugClient

        self.assertIsNot(VisualStudioDebugClient, DebugMCPClient)
        self.assertIsNot(VisualStudioDebugClient, CursorDebugClient)
        self.assertIsNot(VisualStudioDebugClient, CLionDebugClient)
        self.assertIsNot(VisualStudioDebugClient, XcodeDebugClient)

    def test_visual_studio_has_a_distinct_ide_id_from_the_others(self):
        from autodebug.adapters.clion import CLionAdapter
        from autodebug.adapters.cursor import CursorAdapter
        from autodebug.adapters.vscode import VSCodeAdapter
        from autodebug.adapters.xcode import XcodeAdapter

        self.assertNotEqual(VisualStudioAdapter.ide_id, VSCodeAdapter.ide_id)
        self.assertNotEqual(VisualStudioAdapter.ide_id, CursorAdapter.ide_id)
        self.assertNotEqual(VisualStudioAdapter.ide_id, CLionAdapter.ide_id)
        self.assertNotEqual(VisualStudioAdapter.ide_id, XcodeAdapter.ide_id)

    def test_a_vscode_approval_does_not_authorize_a_visual_studio_adapter(self):
        # Defense in depth, independent of the backend_kind=="fake" gate:
        # even a hypothetically-approved "vscode" scope must not satisfy a
        # "visual_studio" adapter's target_identity/backend check.
        def now():
            return 1000.0

        broker = ApprovalBroker(now=now, make_token=lambda: "token-1")
        registry = SessionRegistry()
        router = Router(registry)
        vs_adapter = VisualStudioAdapter(client=FakeVisualStudioDebugClient())
        target = TargetRef(host_id="local-mac", ide="visual_studio", debug_session_id=None, pid=None)
        plan = make_plan(target=target)

        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind="fake",
            target_identity="local-mac/vscode/None",  # issued for vscode, not visual_studio
            scope=("op:arm_case",),
            ttl_seconds=60.0,
            human_presence_confirmed=True,
        )

        with self.assertRaises(AutoDebugError) as ctx:
            authorize_and_arm(
                broker,
                approval,
                plan=plan,
                target_identity="local-mac/visual_studio/None",
                required_scope="op:arm_case",
                router=router,
                adapter=vs_adapter,
                capability_report=capable_report(vs_adapter),
                target=target,
                reviewed_configuration=None,
                process_running=False,
            )
        self.assertIn(ctx.exception.detail.code, (ErrorCode.TARGET_MISMATCH, ErrorCode.PERMISSION_DENIED))


if __name__ == "__main__":
    unittest.main()
