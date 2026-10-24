"""T05 acceptance tests — the human-approval broker prototype (RP-04, RP-05,
DE-07, DE-09). Stdlib `unittest` only, zero third-party packages.

These tests prove the *mechanism* works against the fake backend. They do
NOT, and cannot, prove the unresolved security gate is closed: see
`test_human_presence_confirmation_is_not_itself_a_security_boundary` below,
which exists specifically to keep that limitation visible and tested rather
than silently assumed away.
"""

import unittest
from dataclasses import replace

from autodebug.adapters import VSCodeAdapter
from autodebug.approvals import FAKE_BACKEND_KIND, ApprovalBroker, authorize_and_arm, reject_prohibited_target
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.models import ApprovalRecord, Breakpoint, CasePlan, CasePolicy, ReproductionPlan, TargetRef
from autodebug.plans import stage_plan
from autodebug.router import Router
import hashlib
from autodebug.sessions import SessionRegistry
from tests.fixtures.fake_adapter import FakeAdapter
from tests.fixtures.fake_backend import FULL_SUPPORT


def make_plan(**overrides) -> CasePlan:
    defaults = dict(
        schema_version="0.1-draft",
        case_id="CASE-2026-001",
        source_revision="abc123",
        target=TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None),
        breakpoints=(Breakpoint(file="/repo/src/file.cpp", line=42),),
        reproduction=ReproductionPlan(mode="manual", steps=("Open a disposable design", "Invoke command X")),
        policy=CasePolicy(max_steps=20, max_inspection_seconds=300),
        digest_sha256=None,
    )
    defaults.update(overrides)
    return stage_plan(CasePlan(**defaults))


def make_broker(start_time: float = 1000.0):
    """A deterministic clock/token source — no wall-clock, no randomness
    smuggled in as "the real security mechanism"."""
    clock = {"t": start_time}
    tokens = iter(f"token-{i}" for i in range(1, 1000))

    def now():
        return clock["t"]

    def make_token():
        return next(tokens)

    return ApprovalBroker(now=now, make_token=make_token), clock


class TestIssueApproval(unittest.TestCase):
    def test_requires_explicit_human_presence_confirmation(self):
        broker, _ = make_broker()
        plan = make_plan()
        with self.assertRaises(AutoDebugError) as ctx:
            broker.issue_approval(
                plan,
                reviewer="dev",
                backend_kind=FAKE_BACKEND_KIND,
                target_identity="t1",
                scope=("arm",),
                ttl_seconds=60,
                human_presence_confirmed=False,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.NOT_APPROVED)

    def test_requires_a_staged_plan_with_a_digest(self):
        broker, _ = make_broker()
        unstaged = CasePlan(
            schema_version="0.1-draft",
            case_id="CASE-2026-001",
            source_revision="abc123",
            target=TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None),
            breakpoints=(Breakpoint(file="a.cpp", line=1),),
            reproduction=ReproductionPlan(mode="manual", steps=("step",)),
            policy=CasePolicy(max_steps=20, max_inspection_seconds=300),
            digest_sha256=None,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.issue_approval(
                unstaged,
                reviewer="dev",
                backend_kind=FAKE_BACKEND_KIND,
                target_identity="t1",
                scope=("arm",),
                ttl_seconds=60,
                human_presence_confirmed=True,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.NOT_APPROVED)

    def test_valid_issuance_then_verification_succeeds(self):
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        broker.verify_approval(
            approval, plan=plan, backend_kind=FAKE_BACKEND_KIND, target_identity="session-A", required_scope="arm"
        )  # must not raise


class TestDE07ProhibitedTargetRejection(unittest.TestCase):
    """DE-07, authorization scope: deny a prohibited (remote/production)
    target before any debugger call — independent of the backend_kind gate."""

    def test_production_looking_host_is_rejected_at_issuance(self):
        broker, _ = make_broker()
        plan = make_plan(target=TargetRef(host_id="prod-fusion-01", ide="fake", debug_session_id=None, pid=None))
        with self.assertRaises(AutoDebugError) as ctx:
            broker.issue_approval(
                plan,
                reviewer="dev",
                backend_kind=FAKE_BACKEND_KIND,
                target_identity="prod-fusion-01",
                scope=("arm",),
                ttl_seconds=60,
                human_presence_confirmed=True,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PERMISSION_DENIED)

    def test_remote_looking_host_is_rejected_at_issuance(self):
        broker, _ = make_broker()
        plan = make_plan(target=TargetRef(host_id="remote-build-farm", ide="fake", debug_session_id=None, pid=None))
        with self.assertRaises(AutoDebugError) as ctx:
            broker.issue_approval(
                plan,
                reviewer="dev",
                backend_kind=FAKE_BACKEND_KIND,
                target_identity="remote-build-farm",
                scope=("arm",),
                ttl_seconds=60,
                human_presence_confirmed=True,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PERMISSION_DENIED)

    def test_non_local_host_naming_is_rejected_by_default(self):
        broker, _ = make_broker()
        plan = make_plan(target=TargetRef(host_id="some-other-machine", ide="fake", debug_session_id=None, pid=None))
        with self.assertRaises(AutoDebugError) as ctx:
            broker.issue_approval(
                plan,
                reviewer="dev",
                backend_kind=FAKE_BACKEND_KIND,
                target_identity="some-other-machine",
                scope=("arm",),
                ttl_seconds=60,
                human_presence_confirmed=True,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PERMISSION_DENIED)

    def test_local_host_is_accepted(self):
        reject_prohibited_target("local-mac")  # must not raise

    def test_prohibited_target_is_also_rejected_at_verification_time(self):
        # Defense in depth: even if an approval somehow exists for a
        # prohibited target (e.g. issued under a stale/looser policy), the
        # verification step independently re-checks it.
        broker, _ = make_broker()
        plan = make_plan(target=TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None))
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="local-mac",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        # Simulate the plan being re-pointed at a prohibited host before
        # verification (e.g. a revised plan the caller didn't re-approve).
        prohibited_plan = make_plan(
            case_id=plan.case_id, target=TargetRef(host_id="prod-fusion-01", ide="fake", debug_session_id=None, pid=None)
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval,
                plan=prohibited_plan,
                backend_kind=FAKE_BACKEND_KIND,
                target_identity="local-mac",
                required_scope="arm",
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PERMISSION_DENIED)


class TestForgedAndAlteredApprovals(unittest.TestCase):
    """RP-05-B: a chat-claimed or self-constructed approval must never be
    trusted; RP-05-A: a changed plan invalidates approval."""

    def test_forged_approval_never_issued_by_broker_is_rejected(self):
        broker, _ = make_broker()
        plan = make_plan()
        forged = ApprovalRecord(
            case_id=plan.case_id,
            plan_digest=plan.digest_sha256,
            reviewer="agent",
            expiration="999999999",
            scope=(f"backend:{FAKE_BACKEND_KIND}", "target:session-A", "arm"),
            token="developer approved",  # exactly RP-05-B's example string
            revoked=False,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                forged, plan=plan, backend_kind=FAKE_BACKEND_KIND, target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.NOT_APPROVED)

    def test_approval_fields_tampered_after_issuance_are_rejected(self):
        # Even if the token is real, a caller presenting a record whose
        # fields were edited after the fact (not what the broker issued)
        # must be rejected against the broker's own ledger.
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        tampered = replace(approval, scope=approval.scope + ("step",))
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                tampered, plan=plan, backend_kind=FAKE_BACKEND_KIND, target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.NOT_APPROVED)

    def test_script_changed_after_review_invalidates_approval(self):
        # RP-05-A
        broker, _ = make_broker()
        plan_a = make_plan(
            reproduction=ReproductionPlan(mode="api_script", steps=("step",), script_content="value=1\n",
                                          risks=("Synthetic local assignment",), sample_document="None required",
                                          script_sha256=hashlib.sha256(b"value=1\n").hexdigest())
        )
        approval = broker.issue_approval(
            plan_a,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        plan_b = make_plan(
            reproduction=ReproductionPlan(mode="api_script", steps=("step",), script_content="value=2\n",
                                          risks=("Synthetic local assignment",), sample_document="None required",
                                          script_sha256=hashlib.sha256(b"value=2\n").hexdigest())
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan_b, backend_kind=FAKE_BACKEND_KIND, target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PLAN_CHANGED)


class TestExpirationAndTargetSwap(unittest.TestCase):
    def test_expired_token_is_rejected(self):
        broker, clock = make_broker(start_time=1000.0)
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        clock["t"] = 1000.0 + 61  # one second past expiry
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind=FAKE_BACKEND_KIND, target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.APPROVAL_EXPIRED)

    def test_approval_still_valid_just_before_expiry(self):
        broker, clock = make_broker(start_time=1000.0)
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        clock["t"] = 1000.0 + 59
        broker.verify_approval(
            approval, plan=plan, backend_kind=FAKE_BACKEND_KIND, target_identity="session-A", required_scope="arm"
        )  # must not raise

    def test_target_swap_is_rejected(self):
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval,
                plan=plan,
                backend_kind=FAKE_BACKEND_KIND,
                target_identity="session-B",  # swapped
                required_scope="arm",
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.TARGET_MISMATCH)


class TestRP05CFakeApprovalReplayedAgainstRealAdapter(unittest.TestCase):
    def test_fake_backend_approval_rejected_against_a_real_adapter_route(self):
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        real_adapter = VSCodeAdapter()
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval,
                plan=plan,
                backend_kind=real_adapter.ide_id,  # "vscode", not "fake"
                target_identity="session-A",
                required_scope="arm",
            )
        self.assertIn(ctx.exception.detail.code, (ErrorCode.TARGET_MISMATCH, ErrorCode.PERMISSION_DENIED))

    def test_real_backend_kind_is_refused_even_with_a_perfectly_matched_scope(self):
        # Defense in depth: construct a broker-issued approval whose scope
        # was (hypothetically) bound to "vscode" directly, to prove the
        # explicit backend_kind check rejects it independently of the scope
        # match — never just one layer of defense for this gate.
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind="vscode",
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind="vscode", target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PERMISSION_DENIED)


class TestSpoofedBackendIdentitiesAreRejected(unittest.TestCase):
    """Security review (this session): confirm the backend_kind gate is an
    exact match, not case-insensitive or substring-based, so no naming trick
    lets a real backend masquerade as "fake"."""

    def test_uppercase_fake_is_not_accepted_as_the_fake_backend(self):
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind="FAKE",
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind="FAKE", target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PERMISSION_DENIED)

    def test_fake_as_a_substring_of_a_real_backend_name_is_not_accepted(self):
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind="fake-vscode-bridge",
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind="fake-vscode-bridge", target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PERMISSION_DENIED)

    def test_trailing_whitespace_on_fake_is_not_accepted(self):
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind="fake ",
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind="fake ", target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.PERMISSION_DENIED)

    def test_mismatched_backend_kind_between_issuance_and_verification_is_rejected(self):
        # Issued as "fake", but verification is attempted with a spoofed
        # real-looking kind -> rejected at the scope-match layer first.
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind="clion", target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.TARGET_MISMATCH)


class TestCancellationRevokesApproval(unittest.TestCase):
    """DE-09, authorization scope only."""

    def test_revoked_approval_is_rejected(self):
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        broker.revoke(approval.token)
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind=FAKE_BACKEND_KIND, target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.CANCELLED)

    def test_repeated_revocation_is_idempotent(self):
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        broker.revoke(approval.token)
        broker.revoke(approval.token)  # must not raise
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind=FAKE_BACKEND_KIND, target_identity="session-A", required_scope="arm"
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.CANCELLED)

    def test_revoke_for_case_revokes_every_approval_for_that_case(self):
        broker, _ = make_broker()
        plan = make_plan(case_id="CASE-2026-001")
        approval_1 = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        approval_2 = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-B",
            scope=("step",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        broker.revoke_for_case("CASE-2026-001")
        for approval, target_identity, scope in (
            (approval_1, "session-A", "arm"),
            (approval_2, "session-B", "step"),
        ):
            with self.subTest(target_identity=target_identity):
                with self.assertRaises(AutoDebugError) as ctx:
                    broker.verify_approval(
                        approval,
                        plan=plan,
                        backend_kind=FAKE_BACKEND_KIND,
                        target_identity=target_identity,
                        required_scope=scope,
                    )
                self.assertEqual(ctx.exception.detail.code, ErrorCode.CANCELLED)

    def test_revoke_for_case_does_not_affect_other_cases(self):
        broker, _ = make_broker()
        plan_1 = make_plan(case_id="CASE-2026-001")
        plan_2 = make_plan(case_id="CASE-2026-002")
        approval_2 = broker.issue_approval(
            plan_2,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-B",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        broker.revoke_for_case(plan_1.case_id)
        broker.verify_approval(
            approval_2, plan=plan_2, backend_kind=FAKE_BACKEND_KIND, target_identity="session-B", required_scope="arm"
        )  # must not raise


class TestZeroOperationsWithoutValidAuthorization(unittest.TestCase):
    """The T05 acceptance bar: the fake backend sees zero operations
    without valid authorization."""

    def test_adapter_never_invoked_when_authorization_is_forged(self):
        adapter = FakeAdapter()
        registry = SessionRegistry()
        router = Router(registry)
        broker, _ = make_broker()
        plan = make_plan()
        target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)
        capability_report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")

        forged = ApprovalRecord(
            case_id=plan.case_id,
            plan_digest=plan.digest_sha256,
            reviewer="agent",
            expiration="999999999",
            scope=(f"backend:{FAKE_BACKEND_KIND}", "target:local-mac", "arm"),
            token="not-a-real-token",
            revoked=False,
        )

        with self.assertRaises(AutoDebugError):
            authorize_and_arm(
                broker,
                forged,
                plan=plan,
                target_identity="local-mac",
                required_scope="arm",
                router=router,
                adapter=adapter,
                capability_report=capability_report,
                target=target,
                reviewed_configuration=None,
                process_running=False,
            )
        self.assertEqual(adapter.launch_or_attach_calls, 0)

    def test_adapter_is_invoked_only_after_valid_authorization(self):
        adapter = FakeAdapter()
        registry = SessionRegistry()
        router = Router(registry)
        broker, _ = make_broker()
        plan = make_plan()
        target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)
        capability_report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")

        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="local-mac",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )
        authorize_and_arm(
            broker,
            approval,
            plan=plan,
            target_identity="local-mac",
            required_scope="arm",
            router=router,
            adapter=adapter,
            capability_report=capability_report,
            target=target,
            reviewed_configuration=None,
            process_running=False,
        )
        self.assertEqual(adapter.launch_or_attach_calls, 1)


class TestBypassPathIsIdentifiedAndDocumented(unittest.TestCase):
    """Security review finding (this session): `Router.arm_target` has no
    built-in coupling to `ApprovalBroker`. `authorize_and_arm` is the fix for
    *intended* callers, but calling `Router.arm_target` directly still
    works — Python cannot prevent that. This test documents the residual
    bypass explicitly rather than leaving it implicit, and the companion
    test proves `authorize_and_arm` is itself not bypassable internally."""

    def test_calling_router_arm_target_directly_skips_authorization_entirely(self):
        # This is the known, documented residual risk: nothing here claims
        # bare Router.arm_target is safe to expose to agent-reachable code.
        adapter = FakeAdapter()
        registry = SessionRegistry()
        router = Router(registry)
        target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)
        capability_report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")

        # No ApprovalBroker involved at all, yet this succeeds:
        router.arm_target(adapter, capability_report, target, reviewed_configuration=None, process_running=False)
        self.assertEqual(adapter.launch_or_attach_calls, 1)
        # Conclusion recorded in tasks.md: T07's future MCP facade MUST call
        # authorize_and_arm exclusively and must never expose arm_target
        # directly to the agent's tool-calling surface.

    def test_authorize_and_arm_cannot_be_made_to_skip_its_own_verification_step(self):
        adapter = FakeAdapter()
        registry = SessionRegistry()
        router = Router(registry)
        broker, _ = make_broker()
        plan = make_plan()
        target = TargetRef(host_id="local-mac", ide="fake", debug_session_id=None, pid=None)
        capability_report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")
        forged = ApprovalRecord(
            case_id=plan.case_id,
            plan_digest=plan.digest_sha256,
            reviewer="agent",
            expiration="999999999",
            scope=(f"backend:{FAKE_BACKEND_KIND}", "target:local-mac", "arm"),
            token="forged",
            revoked=False,
        )
        with self.assertRaises(AutoDebugError) as ctx:
            authorize_and_arm(
                broker,
                forged,
                plan=plan,
                target_identity="local-mac",
                required_scope="arm",
                router=router,
                adapter=adapter,
                capability_report=capability_report,
                target=target,
                reviewed_configuration=None,
                process_running=False,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.NOT_APPROVED)
        self.assertEqual(adapter.launch_or_attach_calls, 0)


class TestAuthorizeAndArmBindsToRealAdapterIdentity(unittest.TestCase):
    """Second-pass security regression (`RP-05-C`): `authorize_and_arm` must
    derive backend identity from the actual `adapter` object, never accept
    it as a second, independently-spoofable parameter. Before this fix, a
    caller could pass `adapter=VSCodeAdapter()` while the approval was only
    ever reviewed and issued for the fake backend, and the mismatch would
    not be caught here at all."""

    def test_real_vscode_adapter_cannot_be_armed_under_a_fake_backend_approval(self):
        broker, _ = make_broker()
        registry = SessionRegistry()
        router = Router(registry)
        real_adapter = VSCodeAdapter()  # ide_id == "vscode", a REAL adapter

        plan = make_plan(target=TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None))
        # Genuinely issued and reviewed for the FAKE backend only.
        approval = broker.issue_approval(
            plan,
            reviewer="dev",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="local-mac",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,
        )

        # probe_capabilities(backend=None) -> UNKNOWN, not AVAILABLE, so even
        # if the approval check were skipped, the router's own capability
        # gate would likely decline too — but we must not rely on that
        # second layer; the approval check itself must catch this first.
        capability_report = real_adapter.probe_capabilities(backend=None, host_os="Darwin")
        target = TargetRef(host_id="local-mac", ide="vscode", debug_session_id=None, pid=None)

        with self.assertRaises(AutoDebugError) as ctx:
            authorize_and_arm(
                broker,
                approval,
                plan=plan,
                target_identity="local-mac",
                required_scope="arm",
                router=router,
                adapter=real_adapter,  # backend_kind is derived as "vscode", not "fake"
                capability_report=capability_report,
                target=target,
                reviewed_configuration=None,
                process_running=False,
            )
        self.assertEqual(ctx.exception.detail.code, ErrorCode.TARGET_MISMATCH)
        self.assertEqual(registry.all_sessions(), ())

    def test_backend_kind_parameter_no_longer_exists_on_authorize_and_arm(self):
        # Structural guard: the fix removed backend_kind as a parameter
        # entirely, so it cannot be silently reintroduced as a spoofable
        # second channel without this test failing with a TypeError.
        import inspect

        signature = inspect.signature(authorize_and_arm)
        self.assertNotIn("backend_kind", signature.parameters)


class TestSecurityGateLimitationIsExplicit(unittest.TestCase):
    """This test exists to keep the unresolved limitation visible and
    tested, per design.md's threat model, rather than silently assumed
    solved because the rest of the suite passes."""

    def test_human_presence_confirmation_is_not_itself_a_security_boundary(self):
        # A caller — including, hypothetically, an agent that somehow
        # reached this function directly — can simply pass True. This
        # module has no way to verify a human actually clicked anything.
        # That is precisely why real-backend authorization stays refused
        # below regardless of this call succeeding.
        broker, _ = make_broker()
        plan = make_plan()
        approval = broker.issue_approval(
            plan,
            reviewer="agent-claiming-to-be-a-human",
            backend_kind=FAKE_BACKEND_KIND,
            target_identity="session-A",
            scope=("arm",),
            ttl_seconds=60,
            human_presence_confirmed=True,  # an unverified assertion, not a proof
        )
        self.assertIsNotNone(approval)  # issuance "succeeds" — the gate is NOT here

        # The gate is here instead: this same approval can never reach a
        # real adapter, no matter how it was obtained.
        with self.assertRaises(AutoDebugError) as ctx:
            broker.verify_approval(
                approval, plan=plan, backend_kind="clion", target_identity="session-A", required_scope="arm"
            )
        self.assertIn(ctx.exception.detail.code, (ErrorCode.TARGET_MISMATCH, ErrorCode.PERMISSION_DENIED))


if __name__ == "__main__":
    unittest.main()
