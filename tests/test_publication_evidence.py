"""Publication regressions for DE-02, DE-05 and DE-07 persistence boundaries."""

import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from autodebug.errors import AutoDebugError
from autodebug.evidence import EvidenceStore, build_investigation_report, render_report
from autodebug.models import RootCauseConfidence


def record(store, **overrides):
    fields = dict(
        event_type="paused", session_id="session", source_revision="revision",
        frame="frame", observation_name="counter", observation_value="1",
        expected="1", confidence="observation-only",
    )
    fields.update(overrides)
    return store.record_evidence(**fields)


def report(**overrides):
    fields = dict(
        case_id="case", root_cause_statement="insufficient evidence",
        confidence=RootCauseConfidence.INCONCLUSIVE, evidence_ids=(),
        reproduced=False,
    )
    fields.update(overrides)
    return build_investigation_report(**fields)


class PublicationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="autodebug-evidence-tests-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name).resolve()
        self.store = EvidenceStore(self.base, "case")

    def test_file_symlinks_never_read_or_overwrite_external_files(self):
        for name, operation in (
            ("events.jsonl", lambda: record(self.store)),
            ("events.jsonl", self.store.read_events),
            ("case.json", lambda: self.store.finalize(case_state="cancelled", report=None)),
            ("report.md", lambda: self.store.finalize(case_state="finalized", report=report())),
        ):
            with self.subTest(name=name, operation=operation):
                destination = self.base / "external"
                destination.write_text("private external content", encoding="utf-8")
                link = self.store.case_dir / name
                link.symlink_to(destination)
                try:
                    with self.assertRaises((OSError, ValueError)):
                        operation()
                    self.assertEqual(destination.read_text(), "private external content")
                finally:
                    link.unlink()

    def test_replacement_directory_is_rejected_even_without_symlink(self):
        original = self.store.case_dir
        original.rename(self.base / "original")
        original.mkdir()
        for operation in (
            lambda: record(self.store),
            self.store.read_events,
            lambda: self.store.finalize(case_state="cancelled", report=None),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises((OSError, ValueError)):
                    operation()
        self.assertEqual(list(original.iterdir()), [])

    def test_replacement_directory_symlink_cannot_escape(self):
        original = self.store.case_dir
        original.rename(self.base / "original")
        external = self.base / "external"
        external.mkdir()
        original.symlink_to(external, target_is_directory=True)
        for operation in (
            lambda: record(self.store),
            self.store.read_events,
            lambda: self.store.finalize(case_state="finalized", report=report()),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises((OSError, ValueError)):
                    operation()
        self.assertEqual(list(external.iterdir()), [])

    def test_case_directory_is_exclusively_created_not_resumed(self):
        original = record(self.store)
        with self.assertRaises((OSError, ValueError)):
            EvidenceStore(self.base, "case")
        self.assertEqual(self.store.read_events(), (original,))
        (self.base / "empty").mkdir()
        with self.assertRaises((OSError, ValueError)):
            EvidenceStore(self.base, "empty")

    def test_simultaneous_creation_has_exactly_one_owner(self):
        barrier = threading.Barrier(2)

        def create():
            barrier.wait(timeout=5)
            try:
                return EvidenceStore(self.base, "contested")
            except (OSError, ValueError):
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            stores = list(pool.map(lambda _: create(), range(2)))
        self.assertEqual(sum(store is not None for store in stores), 1)

    def test_concurrent_records_have_unique_ids_and_enforce_cap(self):
        self.store.max_events = 1
        first_inside = threading.Event()
        second_inside = threading.Event()
        append = self.store._append_event

        def delayed_append(evidence):
            if not first_inside.is_set():
                first_inside.set()
                # Without serialization the second writer reaches this hook
                # before the first increments the ID or checks the cap again.
                second_inside.wait(timeout=0.5)
            else:
                second_inside.set()
            append(evidence)

        def write():
            try:
                return record(self.store)
            except AutoDebugError:
                return None

        with patch.object(self.store, "_append_event", side_effect=delayed_append):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(write)
                self.assertTrue(first_inside.wait(timeout=5))
                second = pool.submit(write)
                results = [first.result(timeout=5), second.result(timeout=5)]
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual([r.evidence_id for r in self.store.read_events()], ["E0001"])

    def test_concurrent_records_without_cap_do_not_duplicate_ids(self):
        first_inside = threading.Event()
        second_inside = threading.Event()
        append = self.store._append_event

        def delayed_append(evidence):
            if not first_inside.is_set():
                first_inside.set()
                second_inside.wait(timeout=0.5)
            else:
                second_inside.set()
            append(evidence)

        with patch.object(self.store, "_append_event", side_effect=delayed_append):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(record, self.store)
                self.assertTrue(first_inside.wait(timeout=5))
                second = pool.submit(record, self.store)
                results = [first.result(timeout=5), second.result(timeout=5)]
        self.assertEqual({r.evidence_id for r in results}, {"E0001", "E0002"})
        self.assertEqual([r.evidence_id for r in self.store.read_events()], ["E0001", "E0002"])

    def test_every_observation_field_is_redacted_before_return_and_storage(self):
        secret = "ghp_" + "a" * 36
        for field in (
            "event_type", "session_id", "source_revision", "frame",
            "observation_name", "expected", "confidence",
        ):
            with self.subTest(field=field):
                evidence = record(self.store, **{field: f"prefix_{secret}_suffix"})
                self.assertNotIn(secret, json.dumps(asdict(evidence)))
        self.assertNotIn(secret, self.store.events_path.read_text())

    def test_hardlinks_do_not_allow_external_artifact_writes(self):
        external = self.base / "external"
        external.write_text("unchanged", encoding="utf-8")
        for name, operation in (
            ("events.jsonl", lambda: record(self.store)),
            ("case.json", lambda: self.store.finalize(case_state="cancelled", report=None)),
        ):
            with self.subTest(name=name):
                artifact = self.store.case_dir / name
                os.link(external, artifact)
                try:
                    with self.assertRaises((OSError, ValueError)):
                        operation()
                    self.assertEqual(external.read_text(), "unchanged")
                finally:
                    artifact.unlink()

    def test_nonregular_artifacts_are_rejected_without_blocking(self):
        os.mkfifo(self.store.events_path)
        with self.assertRaises((OSError, ValueError)):
            record(self.store)
        with self.assertRaises((OSError, ValueError)):
            self.store.read_events()

    def test_missing_case_directory_is_not_treated_as_empty_evidence(self):
        self.store.case_dir.rmdir()
        with self.assertRaises((OSError, ValueError)):
            self.store.read_events()

    def test_failed_append_does_not_consume_an_id(self):
        with patch.object(self.store, "_append_event", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                record(self.store)
        self.assertEqual(record(self.store).evidence_id, "E0001")

    def test_read_and_finalize_wait_for_an_inflight_append(self):
        append_finished = threading.Event()
        release_append = threading.Event()
        read_started = threading.Event()
        finalize_started = threading.Event()
        read_finished = threading.Event()
        finalize_finished = threading.Event()
        append = self.store._append_event

        def delayed_append(evidence):
            append(evidence)
            append_finished.set()
            if not release_append.wait(timeout=5):
                raise AssertionError("append was not released")

        def read():
            read_started.set()
            result = self.store.read_events()
            read_finished.set()
            return result

        def finalize():
            finalize_started.set()
            self.store.finalize(case_state="cancelled", report=None)
            finalize_finished.set()

        with patch.object(self.store, "_append_event", side_effect=delayed_append):
            with ThreadPoolExecutor(max_workers=3) as pool:
                writer = pool.submit(record, self.store)
                self.assertTrue(append_finished.wait(timeout=5))
                reader = pool.submit(read)
                finalizer = pool.submit(finalize)
                try:
                    self.assertTrue(read_started.wait(timeout=5))
                    self.assertTrue(finalize_started.wait(timeout=5))
                    self.assertFalse(read_finished.wait(timeout=0.05))
                    self.assertFalse(finalize_finished.wait(timeout=0.05))
                finally:
                    release_append.set()
                evidence = writer.result(timeout=5)
                self.assertEqual(reader.result(timeout=5), (evidence,))
                finalizer.result(timeout=5)
        self.assertEqual(json.loads(self.store.case_path.read_text())["evidence_count"], 1)

    def test_metadata_and_observation_names_are_bounded(self):
        huge = "x" * 10000
        evidence = record(
            self.store, event_type=huge, session_id=huge, source_revision=huge,
            frame=huge, observation_name=huge, expected=huge, confidence=huge,
        )
        for name in ("event_type", "session_id", "source_revision", "frame",
                     "observation", "expected", "confidence"):
            self.assertLess(len(getattr(evidence, name)), 1200)

    def test_report_identifiers_and_state_are_sanitized(self):
        secret = "sk-" + "a" * 32
        result = report(case_id=secret, evidence_ids=(secret,))
        self.assertNotIn(secret, json.dumps(asdict(result)))
        self.assertNotIn(secret, render_report(result, case_state=secret))
        with self.assertRaisesRegex(ValueError, "another case"):
            self.store.finalize(case_state=secret, report=result)
        self.store.finalize(case_state=secret, report=report(case_id=self.store.case_id, evidence_ids=()))
        self.assertNotIn(secret, self.store.case_path.read_text())
        self.assertNotIn(secret, self.store.report_path.read_text())


if __name__ == "__main__":
    unittest.main()
