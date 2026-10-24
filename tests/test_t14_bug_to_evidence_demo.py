"""T14 acceptance tests — Bug-to-Evidence Demonstration (`RP-01`-`RP-08`,
`DE-01`-`DE-09`). Stdlib `unittest` only, zero third-party packages, no MCP
SDK.

**This entire file is a SIMULATED demonstration against `FakeAdapter` and a
disposable synthetic test case.** It proves the *workflow* (intake ->
reproduction plan -> developer approval -> debugger execution -> evidence
collection -> root-cause analysis -> investigation report) wires T01-T13's
components together correctly end to end. It proves nothing about any real
native IDE debugger — `FakeAdapter` is an in-memory test double (see
`tests/fixtures/fake_adapter.py`), not VS Code/Cursor/CLion/Xcode/Visual
Studio. The T05 real-debugger security gate (`FAKE_BACKEND_KIND = "fake"` in
`src/autodebug/approvals.py`) remains OPEN / NOT APPROVED and is itself
re-verified below (`TestAuthorizationFailureDemonstration`) rather than
assumed. Every "evidence" and "report" artifact produced by these tests is
written to a throwaway `tempfile.TemporaryDirectory()` and is simulated
data about a fake function (`maybe_divide`), not a real bug in any real
product.
"""

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from autodebug.adapters import VSCodeAdapter
from autodebug.approvals import ApprovalBroker
from autodebug.errors import ErrorCode
from autodebug.evidence import REDACTED_PLACEHOLDER, EvidenceStore
from autodebug.facade import SCOPE_ARM, SCOPE_CONTINUE, SCOPE_STEP, AutoDebugFacade, target_identity_for
from autodebug.models import (
    Breakpoint,
    CasePlan,
    CasePolicy,
    ExecutionConfidence,
    IntakeSource,
    ReproductionPlan,
    RootCauseConfidence,
    TargetRef,
)
import hashlib
from autodebug.plans import stage_plan
from autodebug.sessions import SessionRegistry
from tests.fixtures.fake_adapter import FakeAdapter
from tests.fixtures.fake_backend import FULL_SUPPORT


def make_broker(start_time: float = 2000.0):
    clock = {"t": start_time}
    tokens = iter(f"t14-token-{i}" for i in range(1, 10_000))
    return ApprovalBroker(now=lambda: clock["t"], make_token=lambda: next(tokens)), clock


class T14DemoBase(unittest.TestCase):
    """A disposable synthetic bug: `maybe_divide(a, b)` in a fake repo
    returns a nonsensical value instead of raising when `b == 0`, because a
    (fictitious) guard was accidentally inverted. This is not a real file in
    this repository or any product; it exists only as a target description
    the fake adapter's breakpoint/stack/variable responses are allegorically
    "about" for the purpose of this demonstration."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base_dir = Path(self._tmp.name)
        self.registry = SessionRegistry()
        self.broker, self.clock = make_broker()
        self.facade = AutoDebugFacade(
            registry=self.registry,
            broker=self.broker,
            evidence_base_dir=self.base_dir,
            now=lambda: self.clock["t"],
            sleep=lambda _seconds: None,
        )
        self.target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)

    def api_script_plan(self, case_id: str) -> CasePlan:
        return stage_plan(
            CasePlan(
                schema_version="0.1-draft",
                case_id=case_id,
                source_revision="demo-rev-1",
                target=self.target,
                breakpoints=(Breakpoint(file="/demo/repo/maybe_divide.py", line=7),),
                reproduction=ReproductionPlan(
                    mode="api_script",
                    steps=("call maybe_divide(10, 0) via the reviewed harness script",),
                    script_content="def maybe_divide(a, b):\n    return a / b\nmaybe_divide(10, 0)\n",
                    script_sha256=hashlib.sha256(b"def maybe_divide(a, b):\n    return a / b\nmaybe_divide(10, 0)\n").hexdigest(),
                    risks=("Raises a synthetic division error; no real app invoked",),
                    sample_document="No document; disposable synthetic Python function",
                ),
                policy=CasePolicy(max_steps=5, max_inspection_seconds=60),
                digest_sha256=None,
            )
        )

    def manual_plan(self, case_id: str) -> CasePlan:
        return stage_plan(
            CasePlan(
                schema_version="0.1-draft",
                case_id=case_id,
                source_revision="demo-rev-1",
                target=self.target,
                breakpoints=(Breakpoint(file="/demo/repo/maybe_divide.py", line=7),),
                reproduction=ReproductionPlan(
                    mode="manual",
                    steps=("Developer manually invokes the division feature from the disposable test UI with b=0",),
                ),
                policy=CasePolicy(max_steps=5, max_inspection_seconds=60),
                digest_sha256=None,
            )
        )

    def create_and_stage(self, case_id, plan, adapter=None):
        adapter = adapter if adapter is not None else FakeAdapter()
        created = self.facade.autodebug_create_case(
            case_id=case_id,
            intake_source=IntakeSource.DEVELOPER_TEXT,
            intake_description="Synthetic bug: maybe_divide(a, 0) does not raise as expected",
            adapter=adapter,
            target=self.target,
        )
        self.assertTrue(created["ok"], created)
        staged = self.facade.autodebug_stage_plan(case_id=case_id, plan=plan)
        self.assertTrue(staged["ok"], staged)
        return adapter, staged["result"]["digest_sha256"]

    def issue_approval(self, case_id, digest, plan, scope=(SCOPE_ARM, SCOPE_STEP, SCOPE_CONTINUE, "op:wait_for_stop", "op:get_stack", "op:get_variables"), ttl_seconds=60.0):
        plan_with_digest = replace(plan, digest_sha256=digest)
        return self.broker.issue_approval(
            plan_with_digest,
            reviewer="developer@example.com",
            backend_kind="fake",
            target_identity=target_identity_for(self.target),
            scope=scope,
            ttl_seconds=ttl_seconds,
            human_presence_confirmed=True,
        )

    def arm(self, case_id, approval, adapter):
        return self.facade.autodebug_arm_case(
            case_id=case_id,
            approval=approval,
            capability_report=adapter.probe_capabilities(FULL_SUPPORT),
            reviewed_configuration=None,
            process_running=False,
        )


class TestConfirmedApiScriptDemonstration(T14DemoBase):
    """RP-01-RP-07 + DE-01-DE-06: a reviewed api_script plan is approved,
    armed, hits a real (fake) breakpoint, stack/variables are inspected,
    stepping is demonstrated, and the resulting report is CONFIRMED only
    because a causal_validation justification is supplied alongside cited
    evidence -- never from a single breakpoint hit alone (DE-06)."""

    def test_confirmed_report_requires_cited_evidence_and_causal_validation(self):
        case_id = "T14-CONFIRMED-DEMO"
        plan = self.api_script_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        approval = self.issue_approval(case_id, digest, plan)

        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)
        self.assertEqual(armed["result"]["state"], "awaiting_developer_reproduction")

        # RP-07: AutoDebug itself never runs the reviewed script. The
        # "developer" (this test, standing in for one) is the one invoking
        # the fake adapter's stop simulation -- nothing in src/autodebug
        # calls simulate_stop.
        session_id = armed["result"]["session"]["debug_session_id"]
        adapter.simulate_stop(session_id)

        waited = self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        self.assertTrue(waited["ok"], waited)
        self.assertEqual(waited["result"]["state"], "paused")

        stack = self.facade.autodebug_get_stack(case_id=case_id, frame_limit=2)
        self.assertTrue(stack["ok"], stack)
        self.assertEqual(len(stack["result"]["frames"]), 2)

        variables = self.facade.autodebug_get_variables(
            case_id=case_id, frame_id="frame-0", selected_names=("local_var", "api_key")
        )
        self.assertTrue(variables["ok"], variables)
        self.assertEqual(variables["result"]["variables"]["local_var"], "42")
        # DE-07: a sensitive-named variable is redacted even though this
        # demo plan never asked for one -- defense in depth.
        self.assertEqual(variables["result"]["variables"]["api_key"], REDACTED_PLACEHOLDER)

        # RP-08: api_script-mode observations are, at best, developer-
        # reported -- no instrumentation anywhere in this project confirms
        # the script actually ran.
        events = self.facade._cases[case_id].evidence_store.read_events()
        self.assertTrue(events)
        self.assertTrue(all(e.execution_confidence == ExecutionConfidence.DEVELOPER_REPORTED for e in events))

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertTrue(stepped["ok"], stepped)
        self.assertEqual(stepped["result"]["steps_taken"], 1)

        resumed = self.facade.autodebug_continue(case_id=case_id, approval=approval)
        self.assertTrue(resumed["ok"], resumed)

        # DE-06: CONFIRMED is refused without both a cited evidence ID and
        # a causal_validation justification -- a bare breakpoint hit is not
        # enough, by construction, not by convention.
        under_evidenced = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="maybe_divide does not raise ZeroDivisionError when b == 0",
            confidence=RootCauseConfidence.CONFIRMED,
            evidence_ids=(),
            reproduced=True,
        )
        self.assertFalse(under_evidenced["ok"], under_evidenced)
        self.assertEqual(under_evidenced["error"]["code"], "INTERNAL_ERROR")

        completed = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="maybe_divide does not raise ZeroDivisionError when b == 0 because its guard was inverted",
            confidence=RootCauseConfidence.CONFIRMED,
            evidence_ids=(events[0].evidence_id,),
            reproduced=True,
            causal_validation="Re-ran the reviewed script after flipping the guard back to `if b == 0:` and the "
            "exception was raised as expected; re-ran once more with the guard reverted and the bug recurred.",
        )
        self.assertTrue(completed["ok"], completed)
        self.assertEqual(completed["result"]["state"], "finalized")

        report_text = (self.base_dir / case_id / "report.md").read_text()
        self.assertIn("CONFIRMED", report_text)
        self.assertIn(events[0].evidence_id, report_text)
        self.assertIn("Causal validation", report_text)


class TestManualPlanLikelyDemonstration(T14DemoBase):
    """RP-07: a manual-mode plan's reproduction steps are never
    automated -- the facade has no tool that executes them -- and its
    resulting observations are NOT_APPLICABLE for execution confidence
    (there is no script whose execution could be developer-reported or
    independently verified at all). The report is labeled LIKELY, not
    CONFIRMED, since no causal_validation is supplied."""

    def test_manual_plan_observations_are_not_applicable_and_report_is_likely(self):
        case_id = "T14-MANUAL-LIKELY-DEMO"
        plan = self.manual_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        approval = self.issue_approval(case_id, digest, plan)

        # RP-07: nothing in AutoDebug performs "Developer manually invokes
        # the division feature..." -- that step's text is never passed to
        # any execution primitive anywhere in src/autodebug. Confirmed
        # structurally: the facade exposes no tool that takes a
        # ReproductionPlan.steps string and runs it.
        import inspect

        facade_source = inspect.getsource(type(self.facade))
        self.assertNotIn("steps[", facade_source)
        self.assertNotIn(".steps)", facade_source)

        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        adapter.simulate_stop(session_id)  # stands in for the developer's own manual action

        waited = self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)
        self.assertTrue(waited["ok"], waited)

        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="frame-0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)

        events = self.facade._cases[case_id].evidence_store.read_events()
        self.assertTrue(events)
        self.assertTrue(all(e.execution_confidence == ExecutionConfidence.NOT_APPLICABLE for e in events))

        completed = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="maybe_divide appears not to raise when b == 0",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=(events[0].evidence_id,),
            reproduced=True,
            uncertainties=("Only one manual run was observed; no controlled re-run was performed.",),
        )
        self.assertTrue(completed["ok"], completed)
        report_text = (self.base_dir / case_id / "report.md").read_text()
        self.assertIn("LIKELY", report_text)
        self.assertNotIn("CONFIRMED", report_text)


class TestInconclusiveWithoutSufficientEvidenceDemonstration(T14DemoBase):
    """DE-06: INCONCLUSIVE is the only confidence level that never requires
    a cited evidence ID -- genuinely insufficient evidence must be reported
    honestly as such, not stretched into LIKELY/CONFIRMED."""

    def test_inconclusive_accepts_zero_evidence_ids(self):
        case_id = "T14-INCONCLUSIVE-DEMO"
        plan = self.manual_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        approval = self.issue_approval(case_id, digest, plan)
        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        adapter.simulate_stop(session_id)
        self.assertTrue(self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)["ok"])
        self.assertTrue(self.facade.autodebug_get_stack(case_id=case_id, frame_limit=1)["ok"])

        completed = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="The breakpoint was reached and the stack was inspected, but no variable "
            "evidence was collected and the cause of the reported behavior could not be determined.",
            confidence=RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=(),
            reproduced=False,
            uncertainties=("No variable evidence was collected before the investigation ended.",),
        )
        self.assertTrue(completed["ok"], completed)
        report_text = (self.base_dir / case_id / "report.md").read_text()
        self.assertIn("INCONCLUSIVE", report_text)
        self.assertIn("(none cited)", report_text)


class TestAuthorizationFailureDemonstration(T14DemoBase):
    """GW-04/T05: an unapproved or forged plan/scope can never arm a
    session, even for this demo's own disposable case -- re-verifying,
    not assuming, that T14's integration work has not loosened the gate."""

    def test_arming_without_any_approval_scope_for_step_is_refused(self):
        case_id = "T14-AUTHZ-FAIL-DEMO"
        plan = self.api_script_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        # Waiting is allowed; stepping is not.
        approval = self.issue_approval(case_id, digest, plan, scope=(SCOPE_ARM, "op:wait_for_stop"))
        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        adapter.simulate_stop(session_id)
        self.assertTrue(self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)["ok"])

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"], stepped)
        self.assertEqual(stepped["error"]["code"], "PERMISSION_DENIED")
        # T14 security review: an authorization-scope failure happens after
        # _verify_session already passed and never touches
        # _mark_incomplete -- the case must remain PAUSED, not INCOMPLETE.
        self.assertEqual(self.facade._cases[case_id].case.state.value, "paused")

    def test_a_real_backend_kind_is_refused_even_for_this_demos_own_case(self):
        """T14 integration must not loosen the still-OPEN T05 gate, even
        for this demo's own disposable case: a fully-scoped approval issued
        for a real adapter's `ide_id` ("vscode") is still refused with
        PERMISSION_DENIED, never silently treated as the fake backend."""
        case_id = "T14-AUTHZ-REAL-BACKEND-DEMO"
        plan = self.api_script_plan(case_id)
        real_adapter = VSCodeAdapter()  # no client attached; never contacts a real IDE
        _, digest = self.create_and_stage(case_id, plan, adapter=real_adapter)
        plan_with_digest = replace(plan, digest_sha256=digest)
        approval = self.broker.issue_approval(
            plan_with_digest,
            reviewer="developer@example.com",
            backend_kind="vscode",
            target_identity=target_identity_for(self.target),
            scope=(SCOPE_ARM, SCOPE_STEP, SCOPE_CONTINUE),
            ttl_seconds=60.0,
            human_presence_confirmed=True,
        )
        armed = self.arm(case_id, approval, real_adapter)
        self.assertFalse(armed["ok"], armed)
        self.assertEqual(armed["error"]["code"], "PERMISSION_DENIED")


class TestCancellationDemonstration(T14DemoBase):
    """DE-09: a developer-initiated cancellation stops a pending wait
    promptly, revokes the approval, and preserves whatever partial evidence
    already exists -- distinct from DE-08's disconnect-triggered
    INCOMPLETE labeling, exercised separately below."""

    def test_cancel_during_wait_for_stop_is_prompt_and_preserves_state(self):
        case_id = "T14-CANCEL-DEMO"
        plan = self.api_script_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        approval = self.issue_approval(case_id, digest, plan)
        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)

        result_holder = {}

        def wait_in_background():
            result_holder["waited"] = self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=30.0)

        thread = threading.Thread(target=wait_in_background)
        thread.start()
        cancelled = self.facade.autodebug_cancel_case(case_id=case_id)
        thread.join(timeout=5.0)
        self.assertFalse(thread.is_alive(), "cancellation did not interrupt the wait promptly")

        self.assertTrue(cancelled["ok"], cancelled)
        self.assertEqual(cancelled["result"]["state"], "cancelled")
        self.assertFalse(result_holder["waited"]["ok"])
        self.assertEqual(result_holder["waited"]["error"]["code"], "CANCELLED")

        case_json_path = self.base_dir / case_id / "case.json"
        self.assertTrue(case_json_path.exists())
        self.assertIn('"cancelled"', case_json_path.read_text())


class TestTimeoutDemonstration(T14DemoBase):
    """DE-01: if the fake breakpoint is never hit, waiting fails closed
    with TIMEOUT rather than hanging or fabricating a pause."""

    def test_wait_for_stop_times_out_when_breakpoint_never_hits(self):
        case_id = "T14-TIMEOUT-DEMO"
        plan = self.api_script_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        approval = self.issue_approval(case_id, digest, plan)
        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)

        clock_ticks = iter([2000.0, 2000.5, 2001.0, 2001.5])

        def ticking_now():
            return next(clock_ticks, 2002.0)

        self.facade._now = ticking_now
        waited = self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=1.0)
        self.assertFalse(waited["ok"], waited)
        self.assertEqual(waited["error"]["code"], "TIMEOUT")


class TestRedactionDemonstration(T14DemoBase):
    """DE-07: a secret-shaped value never reaches events.jsonl or
    report.md unredacted, including when embedded in free-text root-cause
    prose rather than a single variable value."""

    def test_secret_variable_and_secret_shaped_prose_never_reach_disk(self):
        case_id = "T14-REDACTION-DEMO"
        plan = self.api_script_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        approval = self.issue_approval(case_id, digest, plan)
        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        adapter.simulate_stop(session_id)
        self.assertTrue(self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)["ok"])

        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="frame-0", selected_names=("password",))
        self.assertTrue(variables["ok"], variables)
        self.assertEqual(variables["result"]["variables"]["password"], REDACTED_PLACEHOLDER)

        events_path = self.base_dir / case_id / "events.jsonl"
        self.assertNotIn("hunter2", events_path.read_text())

        events = self.facade._cases[case_id].evidence_store.read_events()
        completed = self.facade.autodebug_complete_case(
            case_id=case_id,
            root_cause_statement="Investigation touched a credential sk-abcdefghijklmnopqrstuvwxyz012345 during setup",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=(events[0].evidence_id,),
            reproduced=True,
        )
        self.assertTrue(completed["ok"], completed)
        report_text = (self.base_dir / case_id / "report.md").read_text()
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz012345", report_text)
        self.assertIn(REDACTED_PLACEHOLDER, report_text)


class TestIncompleteInvestigationDemonstration(T14DemoBase):
    """DE-08: a disconnect mid-investigation (the fake IDE "exits") stops
    further privileged actions, preserves whatever partial evidence
    already exists, and labels the case INCOMPLETE -- never silently
    treated as a normal finish."""

    def test_disconnect_mid_investigation_labels_case_incomplete_and_preserves_evidence(self):
        case_id = "T14-INCOMPLETE-DEMO"
        plan = self.api_script_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        approval = self.issue_approval(case_id, digest, plan)
        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        adapter.simulate_stop(session_id)
        self.assertTrue(self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)["ok"])

        variables = self.facade.autodebug_get_variables(case_id=case_id, frame_id="frame-0", selected_names=("local_var",))
        self.assertTrue(variables["ok"], variables)
        evidence_before = self.facade._cases[case_id].evidence_store.read_events()
        self.assertTrue(evidence_before)

        # Simulate the IDE/process exiting mid-investigation.
        ctx = self.facade._cases[case_id]
        self.registry.unregister(ctx.session)

        stack = self.facade.autodebug_get_stack(case_id=case_id, frame_limit=1)
        self.assertFalse(stack["ok"], stack)
        self.assertEqual(stack["error"]["code"], "SESSION_STALE")
        self.assertEqual(ctx.case.state.value, "incomplete")

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"], stepped)
        self.assertEqual(stepped["error"]["code"], "NOT_PAUSED")

        case_json_text_after_first_stale_call = (self.base_dir / case_id / "case.json").read_text()
        self.assertIn('"incomplete"', case_json_text_after_first_stale_call)

        # T14 security review: a *second* SESSION_STALE-triggering call
        # (get_variables, which -- unlike step/continue -- always calls
        # _verify_session rather than gating on case.state first) must be
        # handled idempotently: Case.mark_incomplete() raises on an
        # already-terminal case and _mark_incomplete swallows it, but
        # EvidenceStore.finalize() is safe to call again -- it rewrites the
        # same honest snapshot rather than corrupting or duplicating it.
        variables_after_disconnect = self.facade.autodebug_get_variables(
            case_id=case_id, frame_id="frame-0", selected_names=("local_var",)
        )
        self.assertFalse(variables_after_disconnect["ok"], variables_after_disconnect)
        self.assertEqual(variables_after_disconnect["error"]["code"], "SESSION_STALE")
        self.assertEqual(ctx.case.state.value, "incomplete")

        case_json_text_after_second_stale_call = (self.base_dir / case_id / "case.json").read_text()
        self.assertEqual(
            case_json_text_after_first_stale_call,
            case_json_text_after_second_stale_call,
            "DE-08: repeated stale-session handling must not corrupt the persisted case state",
        )

        evidence_after = self.facade._cases[case_id].evidence_store.read_events()
        self.assertEqual(
            evidence_before,
            evidence_after,
            "DE-08: partial evidence must be preserved, not erased or duplicated, across repeated disconnect handling",
        )

    def test_step_as_the_first_call_after_disconnect_also_reports_session_stale_and_marks_incomplete(self):
        """Order independence: whichever privileged tool is called *first*
        after a disconnect is the one that observes SESSION_STALE and
        triggers the INCOMPLETE transition -- not only `get_stack`/
        `get_variables`. `autodebug_step` still checks `case.state` before
        `_verify_session`, but immediately after a pause the case is still
        PAUSED, so that gate passes through to the session-identity check."""
        case_id = "T14-INCOMPLETE-STEP-FIRST-DEMO"
        plan = self.api_script_plan(case_id)
        adapter, digest = self.create_and_stage(case_id, plan)
        approval = self.issue_approval(case_id, digest, plan)
        armed = self.arm(case_id, approval, adapter)
        self.assertTrue(armed["ok"], armed)
        session_id = armed["result"]["session"]["debug_session_id"]
        adapter.simulate_stop(session_id)
        self.assertTrue(self.facade.autodebug_wait_for_stop(case_id=case_id, timeout_seconds=5.0)["ok"])

        ctx = self.facade._cases[case_id]
        self.assertEqual(ctx.case.state.value, "paused")
        self.registry.unregister(ctx.session)

        stepped = self.facade.autodebug_step(case_id=case_id, approval=approval, kind="step_over")
        self.assertFalse(stepped["ok"], stepped)
        self.assertEqual(stepped["error"]["code"], "SESSION_STALE")
        self.assertEqual(ctx.case.state.value, "incomplete")

        case_json_text = (self.base_dir / case_id / "case.json").read_text()
        self.assertIn('"incomplete"', case_json_text)
