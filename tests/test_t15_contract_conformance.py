"""T15 contract regression tests — `GW-01` and `docs/mcp-contract.md`.

These tests pin the implementation against the documented contract so
future drift (a renamed/removed error code, a changed envelope shape, an
undocumented case state) is caught automatically rather than discovered by
reading prose. They do not test behavior (covered elsewhere) — only shape
and naming stability of the externally observable surface.
"""

import dataclasses
import unittest

from autodebug.errors import ErrorCode
from autodebug.facade import AutoDebugFacade
from autodebug.models import CaseState, EvidenceRecord, ExecutionConfidence, RootCauseConfidence

#: Exact set documented in docs/mcp-contract.md's "Error codes" line.
DOCUMENTED_ERROR_CODES = {
    "CAPABILITY_UNSUPPORTED",
    "BACKEND_UNAVAILABLE",
    "SESSION_AMBIGUOUS",
    "SESSION_STALE",
    "TARGET_MISMATCH",
    "NOT_APPROVED",
    "PLAN_CHANGED",
    "APPROVAL_EXPIRED",
    "BREAKPOINT_UNBOUND",
    "NOT_PAUSED",
    "TIMEOUT",
    "PERMISSION_DENIED",
    "POLICY_LIMIT",
    "SENSITIVE_OUTPUT_BLOCKED",
    "CANCELLED",
    "INTERNAL_ERROR",
}

#: Exact set documented in design.md's "Case workflow states" line, plus the
#: explicitly named terminal/recovery states (CANCELLED/FAILED/TIMED_OUT/
#: INCOMPLETE).
DOCUMENTED_CASE_STATES = {
    "new",
    "plan_staged",
    "awaiting_approval",
    "approved",
    "starting_or_attaching",
    "session_verified",
    "breakpoints_bound",
    "awaiting_developer_reproduction",
    "paused",
    "inspecting",
    "finalized",
    "cancelled",
    "failed",
    "timed_out",
    "incomplete",
}

#: Exact field set from docs/mcp-contract.md's "Evidence record" example.
DOCUMENTED_EVIDENCE_RECORD_FIELDS = {
    "schema_version",
    "case_id",
    "evidence_id",
    "event_type",
    "session_id",
    "source_revision",
    "frame",
    "observation",
    "expected",
    "sanitization",
    "confidence",
    "execution_confidence",
    "stop_id",
    "frame_generation",
    "process_start_id",
    "plan_digest",
}

#: Exact set from docs/mcp-contract.md's "execution_confidence" paragraph.
DOCUMENTED_EXECUTION_CONFIDENCE_VALUES = {"not_applicable", "developer_reported", "independently_verified"}

#: DE-06's three named confidence levels.
DOCUMENTED_ROOT_CAUSE_CONFIDENCE_VALUES = {"confirmed", "likely", "inconclusive"}

#: The 15 autodebug_* tools documented in docs/mcp-contract.md's "Minimal
#: tool set" table.
DOCUMENTED_FACADE_TOOLS = {
    "autodebug_health",
    "autodebug_probe_adapters",
    "autodebug_list_sessions",
    "autodebug_create_case",
    "autodebug_stage_plan",
    "autodebug_get_plan",
    "autodebug_arm_case",
    "autodebug_case_status",
    "autodebug_wait_for_stop",
    "autodebug_get_stack",
    "autodebug_get_variables",
    "autodebug_step",
    "autodebug_continue",
    "autodebug_complete_case",
    "autodebug_cancel_case",
    "autodebug_request_approval",
    "autodebug_wait_for_approval",
}


class TestErrorCodeContract(unittest.TestCase):
    def test_error_code_enum_matches_the_documented_contract_exactly(self):
        actual = {code.value for code in ErrorCode}
        self.assertEqual(actual, DOCUMENTED_ERROR_CODES)


class TestCaseStateContract(unittest.TestCase):
    def test_case_state_enum_matches_design_doc_exactly(self):
        actual = {state.value for state in CaseState}
        self.assertEqual(actual, DOCUMENTED_CASE_STATES)


class TestEvidenceRecordContract(unittest.TestCase):
    def test_evidence_record_fields_match_the_documented_example_exactly(self):
        actual = {f.name for f in dataclasses.fields(EvidenceRecord)}
        self.assertEqual(actual, DOCUMENTED_EVIDENCE_RECORD_FIELDS)

    def test_execution_confidence_values_match_the_documented_contract(self):
        actual = {v.value for v in ExecutionConfidence}
        self.assertEqual(actual, DOCUMENTED_EXECUTION_CONFIDENCE_VALUES)

    def test_root_cause_confidence_values_match_de06(self):
        actual = {v.value for v in RootCauseConfidence}
        self.assertEqual(actual, DOCUMENTED_ROOT_CAUSE_CONFIDENCE_VALUES)


class TestFacadeToolSurfaceContract(unittest.TestCase):
    """GW-01: a stable, documented tool list -- confirms the facade exposes
    exactly the 15 documented tools, no more and no fewer, as plain public
    methods (never renamed/removed without an intentional contract
    change)."""

    def test_facade_exposes_exactly_the_documented_tool_methods(self):
        public_methods = {
            name
            for name in dir(AutoDebugFacade)
            if not name.startswith("_") and callable(getattr(AutoDebugFacade, name))
        }
        self.assertEqual(public_methods, DOCUMENTED_FACADE_TOOLS)


class TestStandardResponseEnvelopeContract(unittest.TestCase):
    """Every facade tool returns the documented `{"ok", "case_id",
    "result"|"error"}` envelope -- spot-checked here against a read-only
    tool that needs no setup; full behavioral coverage of success/failure
    envelopes exists per-tool elsewhere."""

    def test_health_check_returns_the_documented_success_envelope_shape(self):
        from autodebug.approvals import ApprovalBroker
        from autodebug.sessions import SessionRegistry
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            facade = AutoDebugFacade(
                registry=SessionRegistry(),
                broker=ApprovalBroker(now=lambda: 0.0, make_token=lambda: "t"),
                evidence_base_dir=Path(tmp),
            )
            result = facade.autodebug_health()
            self.assertEqual(set(result.keys()), {"ok", "case_id", "result"})
            self.assertTrue(result["ok"])

    def test_unknown_case_id_returns_the_documented_error_envelope_shape(self):
        from autodebug.approvals import ApprovalBroker
        from autodebug.sessions import SessionRegistry
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            facade = AutoDebugFacade(
                registry=SessionRegistry(),
                broker=ApprovalBroker(now=lambda: 0.0, make_token=lambda: "t"),
                evidence_base_dir=Path(tmp),
            )
            result = facade.autodebug_case_status(case_id="CASE-DOES-NOT-EXIST")
            self.assertEqual(set(result.keys()), {"ok", "case_id", "error"})
            self.assertFalse(result["ok"])
            self.assertEqual(set(result["error"].keys()), {"code", "message", "recoverable"})
