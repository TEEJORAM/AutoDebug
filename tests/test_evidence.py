"""T06 acceptance tests — evidence persistence and redaction (DE-02, DE-05,
DE-06, DE-07, DE-08, DE-09). Stdlib `unittest` and `tempfile` only, zero
third-party packages, zero real debugger contact."""

import json
import tempfile
import unittest
from pathlib import Path

from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.evidence import (
    DEFAULT_MAX_EVIDENCE_PER_CASE,
    REDACTED_PLACEHOLDER,
    EvidenceStore,
    build_investigation_report,
    cap_value,
    redact_text,
    redact_value,
    render_report,
    sanitize_observation,
)
from autodebug.models import ExecutionConfidence, RootCauseConfidence
from autodebug.workflow import BreakpointBindingResult, Case
from tests.test_plans import make_plan


class TestRedactValue(unittest.TestCase):
    """DE-07: a sensitive name or value is always redacted."""

    def test_sensitive_name_is_redacted_regardless_of_value(self):
        value, redacted = redact_value("api_token", "totally-ordinary-looking-string")
        self.assertTrue(redacted)
        self.assertEqual(value, REDACTED_PLACEHOLDER)

    def test_password_name_variants_are_redacted(self):
        for name in ("password", "Password", "user_password", "PASSWD"):
            with self.subTest(name=name):
                _, redacted = redact_value(name, "hunter2")
                self.assertTrue(redacted)

    def test_aws_key_shaped_value_is_redacted_even_with_an_innocuous_name(self):
        value, redacted = redact_value("config_value", "AKIAABCDEFGHIJKLMNOP")
        self.assertTrue(redacted)
        self.assertEqual(value, REDACTED_PLACEHOLDER)

    def test_openai_style_key_shaped_value_is_redacted(self):
        value, redacted = redact_value("header", "sk-" + "a" * 32)
        self.assertTrue(redacted)

    def test_github_pat_shaped_value_is_redacted(self):
        value, redacted = redact_value("header", "ghp_" + "a" * 36)
        self.assertTrue(redacted)

    def test_pem_private_key_is_redacted(self):
        value, redacted = redact_value("payload", "-----BEGIN RSA PRIVATE KEY-----\nMIIB...")
        self.assertTrue(redacted)

    def test_ordinary_value_is_not_redacted(self):
        value, redacted = redact_value("body_count", "3")
        self.assertFalse(redacted)
        self.assertEqual(value, "3")


class TestCapValue(unittest.TestCase):
    """DE-02: bounded output, never a full memory dump."""

    def test_short_value_is_untouched(self):
        value, truncated = cap_value("short")
        self.assertFalse(truncated)
        self.assertEqual(value, "short")

    def test_long_value_is_truncated_and_marked(self):
        huge = "x" * 10_000
        value, truncated = cap_value(huge, max_length=500)
        self.assertTrue(truncated)
        self.assertLess(len(value), len(huge))
        self.assertIn("truncated", value)


class TestSanitizeObservationPipeline(unittest.TestCase):
    def test_redaction_takes_priority_over_truncation(self):
        # A sensitive value that is also huge must come back fully redacted,
        # never partially truncated in a way that could leak a prefix.
        huge_secret = "sk-" + ("a" * 10_000)
        sanitized, note = sanitize_observation("api_key_blob", huge_secret)
        self.assertEqual(sanitized, REDACTED_PLACEHOLDER)
        self.assertIn("redacted", note)

    def test_ordinary_huge_value_is_truncated_not_redacted(self):
        sanitized, note = sanitize_observation("counter", "9" * 10_000)
        self.assertIn("truncated", note)
        self.assertLess(len(sanitized), 10_000)


class TestRedactText(unittest.TestCase):
    """DE-07 — free-form prose scanning, distinct from redact_value's
    whole-value replacement for a single named observation."""

    def test_secret_shaped_substring_is_masked_in_place(self):
        text = f"the token was {'sk-' + 'a' * 32} when it crashed"
        redacted, was_redacted = redact_text(text)
        self.assertTrue(was_redacted)
        self.assertNotIn("sk-" + "a" * 32, redacted)
        self.assertIn(REDACTED_PLACEHOLDER, redacted)
        # Surrounding narrative is preserved, unlike redact_value's
        # whole-value replacement.
        self.assertIn("the token was", redacted)
        self.assertIn("when it crashed", redacted)

    def test_plain_prose_with_no_secret_shape_is_untouched(self):
        text = "the password field was never populated before the crash"
        redacted, was_redacted = redact_text(text)
        self.assertFalse(was_redacted)
        self.assertEqual(redacted, text)

    def test_multiple_secrets_in_one_string_are_all_masked(self):
        text = f"keys {'AKIAIOSFODNN7EXAMPLE'} and {'ghp_' + 'c' * 36} both leaked"
        redacted, was_redacted = redact_text(text)
        self.assertTrue(was_redacted)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", redacted)
        self.assertNotIn("ghp_" + "c" * 36, redacted)


class TestBuildReportRedactsFreeTextFields(unittest.TestCase):
    """Security regression: root_cause_statement/causal_validation/
    uncertainties/next_steps previously bypassed redaction entirely, since
    only `EvidenceStore.record_evidence` sanitized anything. A raw secret
    embedded directly in report prose must now be masked."""

    def test_secret_in_root_cause_statement_is_redacted(self):
        secret = "sk-" + "d" * 32
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement=f"the leaked key {secret} caused the crash",
            confidence=RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=(),
            reproduced=False,
        )
        self.assertNotIn(secret, report.root_cause_statement)
        self.assertIn(REDACTED_PLACEHOLDER, report.root_cause_statement)

    def test_secret_in_causal_validation_is_redacted(self):
        secret = "ghp_" + "e" * 36
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement="null pointer traced to a missing check",
            confidence=RootCauseConfidence.CONFIRMED,
            evidence_ids=("E0001",),
            reproduced=True,
            causal_validation=f"re-ran with token {secret} and the fix held",
        )
        self.assertNotIn(secret, report.root_cause_statement)
        self.assertIn(REDACTED_PLACEHOLDER, report.root_cause_statement)
        self.assertIn("Causal validation:", report.root_cause_statement)

    def test_secret_in_uncertainties_is_redacted(self):
        secret = "AKIAIOSFODNN7EXAMPLE"
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement="inconclusive",
            confidence=RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=(),
            reproduced=False,
            uncertainties=(f"could be related to key {secret}",),
        )
        self.assertNotIn(secret, report.uncertainties[0])
        self.assertIn(REDACTED_PLACEHOLDER, report.uncertainties[0])

    def test_secret_in_next_steps_is_redacted(self):
        secret = "-----BEGIN RSA PRIVATE KEY-----"
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement="inconclusive",
            confidence=RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=(),
            reproduced=False,
            next_steps=(f"rotate the key starting with {secret}",),
        )
        self.assertNotIn(secret, report.next_steps[0])
        self.assertIn(REDACTED_PLACEHOLDER, report.next_steps[0])

    def test_secret_never_reaches_rendered_markdown_via_statement(self):
        secret = "sk-" + "f" * 32
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement=f"caused by {secret}",
            confidence=RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=(),
            reproduced=False,
        )
        rendered = render_report(report, case_state="finalized")
        self.assertNotIn(secret, rendered)

    def test_hand_constructed_report_is_still_redacted_by_render_report(self):
        # Defense in depth: even bypassing build_investigation_report
        # entirely (InvestigationReport is a plain dataclass, nothing stops
        # direct construction), render_report must still catch it.
        from autodebug.models import InvestigationReport

        secret = "ghp_" + "g" * 36
        hand_built = InvestigationReport(
            case_id="CASE-2026-001",
            root_cause_statement=f"direct construction leaking {secret}",
            confidence=RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=(),
            reproduced=False,
            uncertainties=(f"also mentions {secret} here",),
            next_steps=(),
        )
        rendered = render_report(hand_built, case_state="finalized")
        self.assertNotIn(secret, rendered)
        self.assertIn(REDACTED_PLACEHOLDER, rendered)


class TestEvidenceStoreRedactionOnDisk(unittest.TestCase):
    """DE-07-A, the exact acceptance scenario: a secret fixture is never
    present on disk or in serialized output."""

    def test_secret_fixture_is_absent_from_the_jsonl_file_on_disk(self):
        secret_fixture = "AKIAIOSFODNN7EXAMPLE"  # exactly matches the AKIA+16-char shape
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001")
            record = store.record_evidence(
                event_type="paused",
                session_id="native-session-1",
                source_revision="abc123",
                frame="foo() in file.cpp:10",
                observation_name="aws_key",
                observation_value=secret_fixture,
                expected="not a secret",
                confidence="observation-only",
            )
            # Not present in the returned, serialized record...
            self.assertNotIn(secret_fixture, record.observation)
            # ...and not present anywhere in the actual file on disk.
            raw_file_contents = store.events_path.read_text(encoding="utf-8")
            self.assertNotIn(secret_fixture, raw_file_contents)
            self.assertIn(REDACTED_PLACEHOLDER, raw_file_contents)

    def test_secret_fixture_is_absent_even_when_read_back(self):
        secret_fixture = "ghp_" + "b" * 36
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001")
            store.record_evidence(
                event_type="paused",
                session_id="s1",
                source_revision="abc123",
                frame="f()",
                observation_name="token",
                observation_value=secret_fixture,
                expected="n/a",
                confidence="observation-only",
            )
            records = store.read_events()
            self.assertEqual(len(records), 1)
            self.assertNotIn(secret_fixture, records[0].observation)


class TestEvidenceStoreBasics(unittest.TestCase):
    def test_evidence_ids_are_stable_and_monotonic(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001")
            r1 = store.record_evidence(
                event_type="paused", session_id="s1", source_revision="a", frame="f1",
                observation_name="x", observation_value="1", expected="1", confidence="observation-only",
            )
            r2 = store.record_evidence(
                event_type="paused", session_id="s1", source_revision="a", frame="f2",
                observation_name="y", observation_value="2", expected="2", confidence="observation-only",
            )
            self.assertEqual(r1.evidence_id, "E0001")
            self.assertEqual(r2.evidence_id, "E0002")

    def test_evidence_cap_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001", max_events=2)
            for i in range(2):
                store.record_evidence(
                    event_type="paused", session_id="s1", source_revision="a", frame=f"f{i}",
                    observation_name="x", observation_value=str(i), expected=str(i), confidence="observation-only",
                )
            with self.assertRaises(AutoDebugError) as ctx:
                store.record_evidence(
                    event_type="paused", session_id="s1", source_revision="a", frame="f3",
                    observation_name="x", observation_value="3", expected="3", confidence="observation-only",
                )
            self.assertEqual(ctx.exception.detail.code, ErrorCode.POLICY_LIMIT)

    def test_cap_rejects_the_new_write_without_discarding_prior_evidence(self):
        # Explicit check that hitting the cap never silently drops history:
        # all evidence recorded before the cap was hit must still be present
        # and intact, both via read_events() and on disk.
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001", max_events=3)
            for i in range(3):
                store.record_evidence(
                    event_type="paused", session_id="s1", source_revision="a", frame=f"f{i}",
                    observation_name="x", observation_value=str(i), expected=str(i), confidence="observation-only",
                )
            with self.assertRaises(AutoDebugError):
                store.record_evidence(
                    event_type="paused", session_id="s1", source_revision="a", frame="f-overflow",
                    observation_name="x", observation_value="overflow", expected="overflow", confidence="observation-only",
                )
            records = store.read_events()
            self.assertEqual(len(records), 3)
            self.assertEqual([r.evidence_id for r in records], ["E0001", "E0002", "E0003"])
            # The file itself has exactly 3 lines — the rejected 4th write
            # never touched disk at all, partially or otherwise.
            with store.events_path.open("r", encoding="utf-8") as f:
                self.assertEqual(sum(1 for _ in f), 3)

    def test_default_cap_matches_documented_constant(self):
        self.assertEqual(DEFAULT_MAX_EVIDENCE_PER_CASE, 200)

    def test_new_investigation_cannot_reopen_previous_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_a = EvidenceStore(Path(tmp), "CASE-2026-001")
            store_a.record_evidence(
                event_type="paused", session_id="s1", source_revision="a", frame="f1",
                observation_name="x", observation_value="1", expected="1", confidence="observation-only",
            )
            with self.assertRaisesRegex(ValueError, "already exists"):
                EvidenceStore(Path(tmp), "CASE-2026-001")
            record = store_a.record_evidence(
                event_type="paused", session_id="s1", source_revision="a", frame="f2",
                observation_name="y", observation_value="2", expected="2", confidence="observation-only",
            )
            self.assertEqual(record.evidence_id, "E0002")
            self.assertEqual(len(store_a.read_events()), 2)


class TestFinalizeDE05DE08DE09(unittest.TestCase):
    """DE-05 (artifacts exist), DE-08/DE-09 (cancelled/incomplete cases keep
    their partial evidence and honest state, never silently marked complete).
    """

    def test_finalize_writes_case_json_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001")
            store.record_evidence(
                event_type="paused", session_id="s1", source_revision="a", frame="f1",
                observation_name="x", observation_value="null", expected="initialized", confidence="observation-only",
            )
            report = build_investigation_report(
                case_id="CASE-2026-001",
                root_cause_statement="x was unexpectedly null",
                confidence=RootCauseConfidence.INCONCLUSIVE,
                evidence_ids=("E0001",),
                reproduced=True,
            )
            store.finalize(case_state="finalized", report=report)

            self.assertTrue(store.case_path.exists())
            self.assertTrue(store.report_path.exists())
            case_data = json.loads(store.case_path.read_text(encoding="utf-8"))
            self.assertEqual(case_data["state"], "finalized")
            self.assertEqual(case_data["evidence_count"], 1)
            self.assertIn("E0001", store.report_path.read_text(encoding="utf-8"))

    def test_cancelled_case_retains_partial_evidence_and_honest_state(self):
        # DE-09-A/C: cancellation retains whatever was captured and marks
        # the case CANCELLED — never silently "finalized".
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001")
            store.record_evidence(
                event_type="paused", session_id="s1", source_revision="a", frame="f1",
                observation_name="x", observation_value="1", expected="1", confidence="observation-only",
            )
            store.finalize(case_state="cancelled", report=None)

            case_data = json.loads(store.case_path.read_text(encoding="utf-8"))
            self.assertEqual(case_data["state"], "cancelled")
            self.assertEqual(case_data["evidence_count"], 1)
            self.assertFalse(store.report_path.exists())  # no report claimed for an incomplete case
            self.assertEqual(len(store.read_events()), 1)  # partial evidence still readable

    def test_repeated_cancellation_finalize_is_idempotent(self):
        # DE-09-B applied to the evidence layer: finalizing "cancelled" twice
        # must not duplicate evidence or error.
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001")
            store.record_evidence(
                event_type="paused", session_id="s1", source_revision="a", frame="f1",
                observation_name="x", observation_value="1", expected="1", confidence="observation-only",
            )
            store.finalize(case_state="cancelled", report=None)
            store.finalize(case_state="cancelled", report=None)  # must not raise

            self.assertEqual(len(store.read_events()), 1)
            case_data = json.loads(store.case_path.read_text(encoding="utf-8"))
            self.assertEqual(case_data["state"], "cancelled")

    def test_incomplete_case_with_zero_evidence_still_finalizes_honestly(self):
        # DE-08: IDE exits mid-investigation before any observation was made.
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp), "CASE-2026-001")
            store.finalize(case_state="incomplete", report=None)

            case_data = json.loads(store.case_path.read_text(encoding="utf-8"))
            self.assertEqual(case_data["state"], "incomplete")
            self.assertEqual(case_data["evidence_count"], 0)


class TestDE06ConfidenceBar(unittest.TestCase):
    def test_confirmed_without_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            build_investigation_report(
                case_id="CASE-2026-001",
                root_cause_statement="x",
                confidence=RootCauseConfidence.CONFIRMED,
                evidence_ids=(),
                reproduced=True,
                causal_validation="re-ran with a fix and the crash stopped",
            )

    def test_confirmed_without_causal_validation_is_rejected(self):
        # The exact DE-06-B scenario: a single breakpoint hit is not enough.
        with self.assertRaises(ValueError):
            build_investigation_report(
                case_id="CASE-2026-001",
                root_cause_statement="null pointer observed once",
                confidence=RootCauseConfidence.CONFIRMED,
                evidence_ids=("E0001",),
                reproduced=True,
                causal_validation=None,
            )

    def test_confirmed_with_evidence_and_causal_validation_succeeds(self):
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement="x was null because of an unchecked return value",
            confidence=RootCauseConfidence.CONFIRMED,
            evidence_ids=("E0001", "E0002"),
            reproduced=True,
            causal_validation="applied a one-line null check and the crash no longer reproduces",
        )
        self.assertEqual(report.confidence, RootCauseConfidence.CONFIRMED)
        self.assertIn("Causal validation:", report.root_cause_statement)

    def test_likely_without_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            build_investigation_report(
                case_id="CASE-2026-001",
                root_cause_statement="x",
                confidence=RootCauseConfidence.LIKELY,
                evidence_ids=(),
                reproduced=False,
            )

    def test_inconclusive_with_no_evidence_is_allowed(self):
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement="insufficient evidence was captured before the session disconnected",
            confidence=RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=(),
            reproduced=False,
        )
        self.assertEqual(report.confidence, RootCauseConfidence.INCONCLUSIVE)


class TestRenderReport(unittest.TestCase):
    def test_report_cites_evidence_ids_not_raw_values(self):
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement="stated cause",
            confidence=RootCauseConfidence.LIKELY,
            evidence_ids=("E0001", "E0002"),
            reproduced=True,
            uncertainties=("alternate explanation X",),
            next_steps=("add a regression test",),
        )
        rendered = render_report(report, case_state="inspecting")
        self.assertIn("LIKELY", rendered)
        self.assertIn("E0001", rendered)
        self.assertIn("E0002", rendered)
        self.assertIn("alternate explanation X", rendered)
        self.assertIn("add a regression test", rendered)
        self.assertIn("inspecting", rendered)

    def test_report_with_no_evidence_notes_it_explicitly(self):
        report = build_investigation_report(
            case_id="CASE-2026-001",
            root_cause_statement="nothing conclusive",
            confidence=RootCauseConfidence.INCONCLUSIVE,
            evidence_ids=(),
            reproduced=False,
        )
        rendered = render_report(report, case_state="incomplete")
        self.assertIn("(none cited)", rendered)


class TestIntegrationWithWorkflowAndSessions(unittest.TestCase):
    """Composition check: EvidenceStore works naturally alongside T04's Case
    state machine without requiring any change to workflow.py."""

    def test_case_cancelled_mid_inspection_retains_evidence_via_the_real_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Case(case_id="CASE-2026-001")
            case.stage_plan(make_plan())
            case.mark_approved(case.plan.digest_sha256)
            case.begin_arming()
            case.confirm_session()
            case.bind_breakpoints((BreakpointBindingResult(file="/repo/src/file.cpp", line=42, bound=True),))
            case.begin_reproduction()
            case.pause()
            case.inspect()

            store = EvidenceStore(Path(tmp), case.case_id)
            store.record_evidence(
                event_type="paused", session_id="native-session-1", source_revision=case.plan.source_revision,
                frame="main() in file.cpp:42", observation_name="user_api_token",
                observation_value="sk-" + "z" * 32, expected="not a secret", confidence="observation-only",
                execution_confidence=ExecutionConfidence.DEVELOPER_REPORTED,
            )

            case.cancel()  # DE-09: developer cancels mid-inspection
            store.finalize(case_state=case.state.value, report=None)

            case_data = json.loads(store.case_path.read_text(encoding="utf-8"))
            self.assertEqual(case_data["state"], "cancelled")
            raw_file = store.events_path.read_text(encoding="utf-8")
            self.assertNotIn("sk-" + "z" * 32, raw_file)
            self.assertIn(REDACTED_PLACEHOLDER, raw_file)


if __name__ == "__main__":
    unittest.main()
