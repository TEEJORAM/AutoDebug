"""T08-T12 acceptance tests for the five client-backed IDE adapters
(GW-03, GW-06, IDE-02, IDE-03, IDE-04, DE-03, DE-07, DE-08, DE-09, RP-06).

One shared suite runs against every adapter with its own mocked client from
`tests/fixtures/fake_ide_clients.py`. No real IDE debugger protocol has been
verified for any adapter, so nothing here contacts a real IDE, installs
anything, or opens a debugger connection. The authorization-gate regressions
prove that implementing an adapter never loosens the T05 security gate,
which remains OPEN / NOT APPROVED.
"""

import inspect
import itertools
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import autodebug.adapters.base as base_module
from autodebug.adapters.base import CORE_OPERATIONS, RemoteSessionInfo
from autodebug.adapters.clion import CLionAdapter, CLionDebugClient
from autodebug.adapters.cursor import CursorAdapter, CursorDebugClient
from autodebug.adapters.visual_studio import VisualStudioAdapter, VisualStudioDebugClient
from autodebug.adapters.vscode import DebugMCPClient, VSCodeAdapter
from autodebug.adapters.xcode import XcodeAdapter, XcodeDebugClient
from autodebug.approvals import ApprovalBroker, authorize_and_arm, reject_prohibited_target
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.evidence import REDACTED_PLACEHOLDER, EvidenceStore
from autodebug.facade import AutoDebugFacade
from autodebug.models import (
    ApprovalRecord, Breakpoint, CapabilityState, CasePlan, CasePolicy, IntakeSource, ReproductionPlan, TargetRef,
)
from autodebug.plans import stage_plan
from autodebug.router import Router
from autodebug.sessions import SessionRegistry
from tests.fixtures.fake_backend import FULL_SUPPORT, NOT_INSTALLED, FakeBackend
from tests.fixtures.fake_ide_clients import (
    FakeCLionDebugClient, FakeCursorDebugClient, FakeDebugMCPClient, FakeVisualStudioDebugClient,
    FakeXcodeDebugClient,
)

#: (adapter, its client Protocol, its fake client, breakpoint file)
ADAPTERS = (
    (VSCodeAdapter, DebugMCPClient, FakeDebugMCPClient, "/repo/src/app.py"),
    (CursorAdapter, CursorDebugClient, FakeCursorDebugClient, "/repo/src/app.py"),
    (CLionAdapter, CLionDebugClient, FakeCLionDebugClient, "/repo/src/app.cpp"),
    (XcodeAdapter, XcodeDebugClient, FakeXcodeDebugClient, "/repo/src/app.swift"),
    (VisualStudioAdapter, VisualStudioDebugClient, FakeVisualStudioDebugClient, "/repo/src/app.cs"),
)


def dummy_approval(case_id: str) -> ApprovalRecord:
    """Placeholder for checks that run before the broker inspects approval
    (e.g. `_verify_session`); never accepted by a real broker."""
    return ApprovalRecord(case_id=case_id, plan_digest="unused", reviewer="unused", expiration="0", scope=(), token="unused")


class _AdapterSuite:
    """Mixin run once per adapter by the concrete classes at the bottom."""

    adapter_cls = VSCodeAdapter
    client_cls = FakeDebugMCPClient
    breakpoint_file = "/repo/src/app.py"

    # -- helpers -------------------------------------------------------

    @property
    def ide(self) -> str:
        return self.adapter_cls.ide_id

    @property
    def host_id(self) -> str:
        return self.adapter_cls.default_host_id

    @property
    def host_os(self) -> str:
        return "Darwin" if "Darwin" in self.adapter_cls.supported_os else self.adapter_cls.supported_os[0]

    def target(self, pid: int | None = None) -> TargetRef:
        return TargetRef(host_id=self.host_id, ide=self.ide, debug_session_id=None, pid=pid)

    @property
    def identity(self) -> str:
        return f"{self.host_id}/{self.ide}/None"

    def capable_report(self, adapter, *, can_launch: bool = True):
        backend = FULL_SUPPORT if can_launch else FakeBackend(
            supported_operations=frozenset(CORE_OPERATIONS) - {"launch_or_attach"}
        )
        return adapter.probe_capabilities(backend=backend, host_os=self.host_os)

    def make_plan(self, **overrides) -> CasePlan:
        defaults = dict(
            schema_version="0.1-draft",
            case_id=f"CASE-2026-{self.ide.upper()}",
            source_revision="abc123",
            target=self.target(),
            breakpoints=(Breakpoint(file=self.breakpoint_file, line=10),),
            reproduction=ReproductionPlan(mode="manual", steps=("Open a disposable design",)),
            policy=CasePolicy(max_steps=20, max_inspection_seconds=300),
            digest_sha256=None,
        )
        defaults.update(overrides)
        return stage_plan(CasePlan(**defaults))

    def make_facade(self, tmp: str):
        registry = SessionRegistry()
        broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: "unused-token")
        return registry, broker, AutoDebugFacade(registry=registry, broker=broker, evidence_base_dir=Path(tmp))

    def create_staged_case(self, facade, case_id, adapter):
        plan = self.make_plan(case_id=case_id)
        created = facade.autodebug_create_case(
            case_id=case_id, intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description=f"{self.ide} facade-boundary check", adapter=adapter, target=self.target(),
        )
        self.assertTrue(created["ok"], created)
        staged = facade.autodebug_stage_plan(case_id=case_id, plan=plan)
        self.assertTrue(staged["ok"], staged)
        return plan, facade._cases[case_id]

    def inject_session(self, registry, facade, case_id, client, *, pause: bool = True):
        """Walk the state machine with a mocked session — test setup only,
        never broker authorization."""
        adapter = self.adapter_cls(client=client)
        plan, ctx = self.create_staged_case(facade, case_id, adapter)
        ctx.case.mark_approved(ctx.case.plan.digest_sha256)
        ctx.case.begin_arming()
        session = adapter.launch_or_attach(self.target(), reviewed_configuration=None)
        registry.register(session)
        ctx.session = session
        ctx.case.confirm_session()
        ctx.case.bind_breakpoints(adapter.set_breakpoints(session, ctx.case.plan.breakpoints))
        ctx.case.begin_reproduction()
        if pause:
            client.simulate_stop(session.debug_session_id)
            ctx.case.pause()
        return adapter, session, ctx

    # -- IDE-03-A: no client fails closed --------------------------------

    def test_zero_argument_construction_still_works(self):
        adapter = self.adapter_cls()
        self.assertEqual(adapter.ide_id, self.ide)
        self.assertTrue(adapter.supported_os)

    def test_default_host_is_local_and_overridable(self):
        # DE-07 only accepts "local..." hosts; the default must pass it.
        reject_prohibited_target(self.adapter_cls.default_host_id)
        session = self.adapter_cls(client=self.client_cls(), host_id="local-dev-box").launch_or_attach(self.target(), None)
        self.assertEqual(session.host_id, "local-dev-box")

    def test_every_operation_reports_backend_unavailable_without_a_client(self):
        adapter = self.adapter_cls()
        for op in (
            adapter.list_sessions,
            lambda: adapter.launch_or_attach(self.target(), None),
            lambda: adapter.is_paused("x"),
        ):
            with self.assertRaises(AutoDebugError) as ctx:
                op()
            self.assertEqual(ctx.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)

    def test_module_source_contains_no_process_spawning_code(self):
        # docs/ide-integrations.md: use the IDE's own native session through
        # an approved bridge; never spawn an independent debugger process.
        for module in (inspect.getmodule(self.adapter_cls), base_module):
            source = inspect.getsource(module).lower()
            for forbidden in ("subprocess", "os.system", "popen"):
                with self.subTest(module=module.__name__, forbidden=forbidden):
                    self.assertNotIn(forbidden, source)

    # -- session discovery and translation -------------------------------

    def test_launch_or_attach_translates_remote_info_to_a_session_ref(self):
        adapter = self.adapter_cls(client=self.client_cls())
        session = adapter.launch_or_attach(self.target(pid=4242), reviewed_configuration=None)
        self.assertEqual(session.host_id, self.host_id)
        self.assertEqual(session.ide, self.ide)
        self.assertEqual(session.pid, 4242)
        self.assertTrue(session.ide_instance_id)
        self.assertTrue(session.debug_session_id)
        self.assertEqual(session.session_generation, 1)

    def test_list_sessions_reflects_the_client(self):
        adapter = self.adapter_cls(client=self.client_cls())
        adapter.launch_or_attach(self.target(), None)
        self.assertEqual(len(adapter.list_sessions()), 1)

    def test_generation_is_assigned_locally_when_client_reports_none(self):
        adapter = self.adapter_cls(client=self.client_cls())
        a = adapter.launch_or_attach(self.target(), None)
        b = adapter.launch_or_attach(self.target(), None)
        self.assertNotEqual(a.debug_session_id, b.debug_session_id)
        self.assertEqual(a.session_generation, 1)
        self.assertEqual(b.session_generation, 2)

    def test_client_reported_generation_is_used_verbatim(self):
        client = self.client_cls()
        adapter = self.adapter_cls(client=client)
        info = RemoteSessionInfo("remote-1", 4242, "window-1", "/fake/app", "running", generation=5)
        with patch.object(client, "start_or_attach", return_value=info):
            self.assertEqual(adapter.launch_or_attach(self.target(), None).session_generation, 5)

    # -- GW-06 scenarios through Router (independent of the approval gate) --

    def test_scenario_a_launch(self):
        registry = SessionRegistry()
        client = self.client_cls()
        adapter = self.adapter_cls(client=client)
        session = Router(registry).arm_target(
            adapter, self.capable_report(adapter), self.target(), reviewed_configuration=None, process_running=False
        )
        self.assertEqual(client.start_or_attach_calls, 1)
        self.assertIn(session, registry.all_sessions())

    def test_scenario_b_attach(self):
        registry = SessionRegistry()
        client = self.client_cls()
        adapter = self.adapter_cls(client=client)
        session = Router(registry).arm_target(
            adapter, self.capable_report(adapter), self.target(pid=9999), reviewed_configuration=None,
            process_running=True,
        )
        self.assertEqual(client.start_or_attach_calls, 1)
        self.assertEqual(session.pid, 9999)

    def test_scenario_c_existing_session_reused_no_hidden_second_session(self):
        # IDE-04-B point 8: confirm no hidden second debugger session.
        registry = SessionRegistry()
        router = Router(registry)
        client = self.client_cls()
        adapter = self.adapter_cls(client=client)
        target = self.target(pid=4210)
        first = router.arm_target(adapter, self.capable_report(adapter), target, None, process_running=False)
        second = router.arm_target(adapter, self.capable_report(adapter), target, None, process_running=True)
        self.assertIs(second, first)
        self.assertEqual(client.start_or_attach_calls, 1, "a second debugger session must never be created")
        self.assertEqual(len(registry.all_sessions()), 1)

    def test_scenario_d_decline_when_unsupported(self):
        registry = SessionRegistry()
        client = self.client_cls(can_start_or_attach=False)
        adapter = self.adapter_cls(client=client)
        with self.assertRaises(AutoDebugError) as ctx:
            Router(registry).arm_target(
                adapter, self.capable_report(adapter, can_launch=False), self.target(),
                reviewed_configuration=None, process_running=False,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.CAPABILITY_UNSUPPORTED)
        self.assertEqual(client.start_or_attach_calls, 0, "an unsupported op must never reach the client")
        self.assertEqual(registry.all_sessions(), ())

    # -- RP-06 binding, stack, variables, step, continue -------------------

    def _live(self, **client_kwargs):
        client = self.client_cls(**client_kwargs)
        adapter = self.adapter_cls(client=client)
        return client, adapter, adapter.launch_or_attach(self.target(), None)

    def test_breakpoint_binding_confirmed(self):
        _, adapter, session = self._live()
        breakpoints = (Breakpoint(file=self.breakpoint_file, line=10), Breakpoint(file=self.breakpoint_file, line=20))
        results = adapter.set_breakpoints(session, breakpoints)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.bound for r in results))

    def test_breakpoint_binding_failure_is_reported_not_assumed(self):
        _, adapter, session = self._live(can_bind_breakpoints=False)
        results = adapter.set_breakpoints(session, (Breakpoint(file=self.breakpoint_file, line=10),))
        self.assertFalse(results[0].bound)
        self.assertTrue(results[0].reason)

    def test_debugger_stop_detected_via_is_paused(self):
        client, adapter, session = self._live()
        self.assertFalse(adapter.is_paused(session.debug_session_id))
        client.simulate_stop(session.debug_session_id)
        self.assertTrue(adapter.is_paused(session.debug_session_id))

    def test_wait_for_stop_returns_once_paused(self):
        client, adapter, session = self._live()
        client.simulate_stop(session.debug_session_id)
        adapter.wait_for_stop(session, timeout=1.0)  # must not raise

    def test_wait_for_stop_times_out_when_never_paused(self):
        _, adapter, session = self._live()
        with self.assertRaises(AutoDebugError) as ctx:
            adapter.wait_for_stop(session, timeout=0.05)
        self.assertEqual(ctx.exception.detail.code, ErrorCode.TIMEOUT)

    def test_stack_inspection(self):
        client, adapter, session = self._live()
        client.simulate_stop(session.debug_session_id)
        self.assertEqual(len(adapter.get_stack(session, frame_limit=2)), 2)

    def test_variable_read_returns_raw_unredacted_value(self):
        # DE-07 redaction happens once, at the facade; adapters return raw.
        client, adapter, session = self._live()
        client.simulate_stop(session.debug_session_id)
        variables = adapter.get_variables(session, "frame-0", ("password",))
        self.assertEqual(variables["password"], "hunter2")
        self.assertNotEqual(variables["password"], REDACTED_PLACEHOLDER)

    def test_step_and_continue_do_not_raise(self):
        client, adapter, session = self._live()
        client.simulate_stop(session.debug_session_id)
        adapter.step(session, "step_over")
        adapter.continue_execution(session)
        self.assertFalse(adapter.is_paused(session.debug_session_id))

    def test_disconnect_removes_the_session_and_does_not_relaunch(self):
        client, adapter, session = self._live()
        adapter.disconnect(session)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(adapter.list_sessions(), ())

    # -- GW-02 / IDE-02 capability probing --------------------------------

    def test_unknown_before_any_backend_description(self):
        report = self.adapter_cls().probe_capabilities(backend=None, host_os=self.host_os)
        self.assertEqual(report.state, CapabilityState.UNKNOWN)

    def test_not_installed_backend_reports_unavailable(self):
        report = self.adapter_cls().probe_capabilities(backend=NOT_INSTALLED, host_os=self.host_os)
        self.assertEqual(report.state, CapabilityState.UNAVAILABLE)

    def test_full_support_backend_reports_available_for_every_core_operation(self):
        report = self.adapter_cls(client=self.client_cls()).probe_capabilities(backend=FULL_SUPPORT, host_os=self.host_os)
        for op in CORE_OPERATIONS:
            with self.subTest(op):
                self.assertEqual(report.operations[op], CapabilityState.AVAILABLE)

    def test_injected_host_os_reports_deterministic_applicability(self):
        # IDE-02-A: an unsupported OS is NOT_APPLICABLE and never probes the backend.
        adapter = self.adapter_cls(client=self.client_cls())
        for host_os in ("Windows", "Darwin", "Linux"):
            with self.subTest(host_os=host_os):
                report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os=host_os)
                if host_os in self.adapter_cls.supported_os:
                    self.assertEqual(report.state, CapabilityState.AVAILABLE)
                    self.assertEqual(report.operations, {op: CapabilityState.AVAILABLE for op in CORE_OPERATIONS})
                else:
                    self.assertEqual(report.state, CapabilityState.NOT_APPLICABLE)
                    self.assertEqual(report.operations, {})

    # -- T05 authorization gate still blocks real adapters ----------------

    def test_authorize_and_arm_refuses_a_fully_wired_real_adapter(self):
        tokens = iter(f"token-{i}" for i in range(1, 10))
        broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: next(tokens))
        registry = SessionRegistry()
        client = self.client_cls()
        adapter = self.adapter_cls(client=client)
        plan = self.make_plan()
        approval = broker.issue_approval(
            plan, reviewer="dev", backend_kind="fake", target_identity=self.identity,
            scope=("op:arm_case",), ttl_seconds=60.0, human_presence_confirmed=True,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            authorize_and_arm(
                broker, approval, plan=plan, target_identity=self.identity, required_scope="op:arm_case",
                router=Router(registry), adapter=adapter, capability_report=self.capable_report(adapter),
                target=self.target(), reviewed_configuration=None, process_running=False,
            )
        self.assertIn(ctx.exception.detail.code, (ErrorCode.TARGET_MISMATCH, ErrorCode.PERMISSION_DENIED))
        self.assertEqual(client.start_or_attach_calls, 0, "the real client must never be reached")
        self.assertEqual(registry.all_sessions(), ())

    def test_approval_for_another_ide_does_not_authorize_this_adapter(self):
        other = "cursor" if self.ide == "vscode" else "vscode"
        broker = ApprovalBroker(now=lambda: 1000.0, make_token=lambda: "token-1")
        adapter = self.adapter_cls(client=self.client_cls())
        plan = self.make_plan()
        approval = broker.issue_approval(
            plan, reviewer="dev", backend_kind="fake", target_identity=f"{self.host_id}/{other}/None",
            scope=("op:arm_case",), ttl_seconds=60.0, human_presence_confirmed=True,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            authorize_and_arm(
                broker, approval, plan=plan, target_identity=self.identity, required_scope="op:arm_case",
                router=Router(SessionRegistry()), adapter=adapter, capability_report=self.capable_report(adapter),
                target=self.target(), reviewed_configuration=None, process_running=False,
            )
        self.assertIn(ctx.exception.detail.code, (ErrorCode.TARGET_MISMATCH, ErrorCode.PERMISSION_DENIED))

    # -- facade boundaries with a real adapter class ----------------------

    def test_unapproved_real_facade_reads_and_wait_are_refused_without_leaks(self):
        # DE-07/RP-04: injected sessions never authorize sensitive reads, and
        # even a broker-issued real-backend approval fails the open gate.
        with tempfile.TemporaryDirectory() as tmp:
            registry, broker, facade = self.make_facade(tmp)
            client = self.client_cls()
            case_id = "CASE-REDACTION"
            adapter, _, ctx = self.inject_session(registry, facade, case_id, client)
            ctx.evidence_store = EvidenceStore(Path(tmp), case_id)
            approval = broker.issue_approval(
                ctx.case.plan, reviewer="dev", backend_kind=adapter.ide_id, target_identity=self.identity,
                scope=("op:arm_case",), ttl_seconds=60.0, human_presence_confirmed=True,
            )
            with (
                patch.object(client, "get_variables", side_effect=AssertionError("unauthorized variable read")) as variables,
                patch.object(client, "get_stack", side_effect=AssertionError("unauthorized stack read")) as stack,
                patch.object(client, "is_paused", side_effect=AssertionError("unauthorized pause query")) as paused,
            ):
                for stored_approval, expected in ((None, "NOT_APPROVED"), (approval, "PERMISSION_DENIED")):
                    with self.subTest(approval=expected):
                        ctx.approval = stored_approval
                        for result in (
                            facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=1.0),
                            facade.autodebug_get_stack(case_id=case_id, frame_limit=1),
                            facade.autodebug_get_variables(
                                case_id=case_id, frame_id="frame-0", selected_names=("password", "local_var")
                            ),
                        ):
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

    def test_exited_session_blocks_get_stack_get_variables_step_and_continue(self):
        # GW-03-B at the facade layer; DE-08 labels the case incomplete.
        with tempfile.TemporaryDirectory() as tmp:
            registry, _, facade = self.make_facade(tmp)
            case_id = "CASE-STALE"
            _, session, ctx = self.inject_session(registry, facade, case_id, self.client_cls())
            registry.unregister(session)  # the process/session exited
            approval = dummy_approval(case_id)

            stack = facade.autodebug_get_stack(case_id=case_id, frame_limit=1)
            self.assertEqual(stack["error"]["code"], "SESSION_STALE")
            self.assertEqual(ctx.case.state.value, "incomplete", "DE-08: disconnect must label the case incomplete")
            variables = facade.autodebug_get_variables(case_id=case_id, frame_id="f0", selected_names=("local_var",))
            self.assertEqual(variables["error"]["code"], "SESSION_STALE")
            self.assertEqual(facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")["error"]["code"], "NOT_PAUSED")
            self.assertEqual(facade.autodebug_continue(case_id=case_id, approval=approval)["error"]["code"], "NOT_PAUSED")

    def test_reassigned_session_identity_blocks_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry, _, facade = self.make_facade(tmp)
            case_id = "CASE-REASSIGNED"
            _, session, ctx = self.inject_session(registry, facade, case_id, self.client_cls())
            registry.register(replace(session, session_generation=session.session_generation + 1))
            stepped = facade.autodebug_step(case_id=case_id, approval=dummy_approval(case_id), kind="step_over")
            self.assertEqual(stepped["error"]["code"], "TARGET_MISMATCH")
            # A reassigned identity is a security refusal, not a DE-08 disconnect.
            self.assertEqual(ctx.case.state.value, "paused")

    def test_failed_binding_disconnects_unregisters_and_revokes(self):
        # RP-06: a real adapter's public arm path is refused by the gate before
        # binding, so exercise the rollback helper directly.
        with tempfile.TemporaryDirectory() as tmp:
            registry, broker, facade = self.make_facade(tmp)
            client = self.client_cls()
            adapter = self.adapter_cls(client=client)
            plan, ctx = self.create_staged_case(facade, "CASE-ROLLBACK", adapter)
            session = adapter.launch_or_attach(self.target(), reviewed_configuration=None)
            registry.register(session)
            approval = broker.issue_approval(
                plan, reviewer="dev", backend_kind="fake", target_identity=self.identity,
                scope=("op:arm_case",), ttl_seconds=60.0, human_presence_confirmed=True,
            )
            facade._rollback_failed_arming(ctx, session)

            self.assertEqual(registry.all_sessions(), (), "the session must not be left live/registered")
            self.assertEqual(client.disconnect_calls, 1)
            self.assertEqual(ctx.case.state.value, "failed")
            self.assertIsNone(ctx.session)
            with self.assertRaises(AutoDebugError) as broker_ctx:
                broker.verify_approval(
                    approval, plan=plan, backend_kind="fake", target_identity=self.identity, required_scope="op:arm_case",
                )
            self.assertEqual(broker_ctx.exception.detail.code, ErrorCode.CANCELLED)

    def test_unapproved_wait_is_refused_before_cancellation_still_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry, _, facade = self.make_facade(tmp)
            client = self.client_cls()
            case_id = "CASE-CANCEL"
            _, _, ctx = self.inject_session(registry, facade, case_id, client, pause=False)
            with (
                patch.object(client, "is_paused", side_effect=AssertionError("unauthorized pause query")) as paused,
                patch.object(facade, "_sleep", side_effect=AssertionError("unauthorized wait polled")) as sleep,
            ):
                waited = facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=10.0)
                self.assertEqual(waited["error"]["code"], "NOT_APPROVED")
                paused.assert_not_called()
                sleep.assert_not_called()
            self.assertEqual(ctx.case.state.value, "awaiting_developer_reproduction")
            cancelled = facade.autodebug_cancel_case(case_id=case_id)
            self.assertTrue(cancelled["ok"], cancelled)
            self.assertTrue(ctx.cancel_event.is_set())
            self.assertEqual(ctx.case.state.value, "cancelled")

    def test_step_is_also_unconditionally_refused_for_a_real_adapter(self):
        # DE-03's step budget sits behind verify_approval, so for any
        # ide_id != "fake" the gate refuses first, even with a matching scope.
        with tempfile.TemporaryDirectory() as tmp:
            registry, broker, facade = self.make_facade(tmp)
            _, _, ctx = self.inject_session(registry, facade, "CASE-STEPGATE", self.client_cls())
            approval = broker.issue_approval(
                ctx.case.plan, reviewer="dev", backend_kind=self.ide, target_identity=self.identity,
                scope=("op:step",), ttl_seconds=60.0, human_presence_confirmed=True,
            )
            stepped = facade.autodebug_step(case_id="CASE-STEPGATE", approval=approval, kind="step_over")
            self.assertEqual(stepped["error"]["code"], "PERMISSION_DENIED")
            self.assertEqual(ctx.steps_taken, 0, "the step budget counter must never advance on a refused call")


class TestVSCodeAdapter(_AdapterSuite, unittest.TestCase):
    adapter_cls, client_cls, breakpoint_file = VSCodeAdapter, FakeDebugMCPClient, "/repo/src/app.py"


class TestCursorAdapter(_AdapterSuite, unittest.TestCase):
    adapter_cls, client_cls, breakpoint_file = CursorAdapter, FakeCursorDebugClient, "/repo/src/app.py"


class TestCLionAdapter(_AdapterSuite, unittest.TestCase):
    adapter_cls, client_cls, breakpoint_file = CLionAdapter, FakeCLionDebugClient, "/repo/src/app.cpp"


class TestXcodeAdapter(_AdapterSuite, unittest.TestCase):
    adapter_cls, client_cls, breakpoint_file = XcodeAdapter, FakeXcodeDebugClient, "/repo/src/app.swift"


class TestVisualStudioAdapter(_AdapterSuite, unittest.TestCase):
    adapter_cls, client_cls, breakpoint_file = VisualStudioAdapter, FakeVisualStudioDebugClient, "/repo/src/app.cs"


class TestAdapterHosts(unittest.TestCase):
    def test_windows_only_adapter_does_not_default_to_a_mac_host(self):
        target = TargetRef(host_id="local-windows", ide="visual_studio", debug_session_id=None, pid=None)
        session = VisualStudioAdapter(client=FakeVisualStudioDebugClient()).launch_or_attach(target, None)
        self.assertEqual(session.host_id, "local-windows")


class TestAdaptersStayIndependent(unittest.TestCase):
    """IDE-03: each adapter is typed and tested independently — no shared
    client Protocol object or ide_id between any two adapters."""

    def test_every_adapter_has_a_distinct_client_protocol_and_ide_id(self):
        for (a, a_proto, _, _), (b, b_proto, _, _) in itertools.combinations(ADAPTERS, 2):
            with self.subTest(a=a.ide_id, b=b.ide_id):
                self.assertIsNot(a_proto, b_proto)
                self.assertNotEqual(a.ide_id, b.ide_id)

    def test_facade_never_calls_bare_router_arm_target(self):
        from autodebug import facade as facade_module

        source = inspect.getsource(facade_module.AutoDebugFacade.autodebug_arm_case)
        self.assertNotIn("self._router.arm_target(", source)


if __name__ == "__main__":
    unittest.main()
