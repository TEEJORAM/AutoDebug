"""T04 acceptance tests — plan validation and canonical digest (RP-03).
Stdlib `unittest` only, zero third-party packages."""

import unittest
import hashlib
from dataclasses import replace

from autodebug.models import Breakpoint, CasePlan, CasePolicy, ReproductionPlan, TargetRef
from autodebug.plans import compute_plan_digest, stage_plan, validate_case_plan


def make_plan(**overrides) -> CasePlan:
    defaults = dict(
        schema_version="0.1-draft",
        case_id="CASE-2026-001",
        source_revision="abc123",
        target=TargetRef(host_id="local-mac", ide="clion", debug_session_id=None, pid=None),
        breakpoints=(Breakpoint(file="/repo/src/file.cpp", line=42),),
        reproduction=ReproductionPlan(mode="manual", steps=("Open a disposable design", "Invoke command X")),
        policy=CasePolicy(max_steps=20, max_inspection_seconds=300),
        digest_sha256=None,
    )
    defaults.update(overrides)
    return CasePlan(**defaults)


class TestReproductionPlanValidation(unittest.TestCase):
    """RP-03: exactly one of api_script or manual, never a hybrid or a
    fabricated automation claim."""

    def test_manual_plan_without_script_digest_is_valid(self):
        plan = make_plan()
        validate_case_plan(plan)  # must not raise

    def test_api_script_plan_with_digest_is_valid(self):
        plan = make_plan(
            reproduction=ReproductionPlan(
                mode="api_script", steps=("Create two bodies", "Combine", "Hide body 2", "Undo"),
                script_content="pass\n", script_sha256=hashlib.sha256(b"pass\n").hexdigest(),
                risks=("No application side effects; synthetic no-op",), sample_document="None required",
            )
        )
        validate_case_plan(plan)  # must not raise

    def test_api_script_without_digest_is_rejected(self):
        plan = make_plan(reproduction=ReproductionPlan(mode="api_script", steps=("step 1",), script_sha256=None))
        with self.assertRaises(ValueError):
            validate_case_plan(plan)

    def test_manual_plan_with_a_script_digest_is_rejected(self):
        # No automation claim is allowed on a manual plan.
        plan = make_plan(reproduction=ReproductionPlan(mode="manual", steps=("step 1",), script_sha256="a" * 64))
        with self.assertRaises(ValueError):
            validate_case_plan(plan)

    def test_unknown_mode_is_rejected(self):
        plan = make_plan(reproduction=ReproductionPlan(mode="automagic", steps=("step 1",)))
        with self.assertRaises(ValueError):
            validate_case_plan(plan)

    def test_empty_steps_are_rejected(self):
        plan = make_plan(reproduction=ReproductionPlan(mode="manual", steps=()))
        with self.assertRaises(ValueError):
            validate_case_plan(plan)


class TestCasePlanStructuralValidation(unittest.TestCase):
    def test_missing_case_id_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_case_plan(make_plan(case_id=""))

    def test_missing_source_revision_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_case_plan(make_plan(source_revision=""))

    def test_no_breakpoints_is_rejected(self):
        # RP-06 has nothing to bind without at least one requested breakpoint.
        with self.assertRaises(ValueError):
            validate_case_plan(make_plan(breakpoints=()))


class TestCanonicalDigest(unittest.TestCase):
    def test_digest_is_deterministic(self):
        plan = make_plan()
        self.assertEqual(compute_plan_digest(plan), compute_plan_digest(plan))

    def test_digest_ignores_its_own_field(self):
        plan = make_plan()
        with_digest = replace(plan, digest_sha256="irrelevant-placeholder")
        self.assertEqual(compute_plan_digest(plan), compute_plan_digest(with_digest))

    def test_digest_changes_when_content_changes(self):
        # This is the mechanism RP-05 depends on: "a modified field SHALL
        # invalidate approval" requires the digest to actually change.
        plan_a = make_plan(source_revision="abc123")
        plan_b = make_plan(source_revision="def456")
        self.assertNotEqual(compute_plan_digest(plan_a), compute_plan_digest(plan_b))

    def test_one_character_script_edit_changes_the_digest(self):
        base = make_plan(
            reproduction=ReproductionPlan(mode="api_script", steps=("step",), script_sha256="a" * 64)
        )
        edited = replace(
            base, reproduction=ReproductionPlan(mode="api_script", steps=("step",), script_sha256="b" + "a" * 63)
        )
        self.assertNotEqual(compute_plan_digest(base), compute_plan_digest(edited))


class TestStagePlan(unittest.TestCase):
    def test_stage_plan_populates_digest_without_mutating_the_original(self):
        original = make_plan()
        staged = stage_plan(original)
        self.assertIsNone(original.digest_sha256)  # frozen dataclass, never mutated
        self.assertIsNotNone(staged.digest_sha256)
        self.assertEqual(staged.digest_sha256, compute_plan_digest(original))

    def test_stage_plan_rejects_a_malformed_plan(self):
        with self.assertRaises(ValueError):
            stage_plan(make_plan(breakpoints=()))


if __name__ == "__main__":
    unittest.main()
