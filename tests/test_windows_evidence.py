"""WIN-01..03 (openspec/changes/windows-evidence-storage): native Windows
evidence storage keeps the POSIX guarantees. Runs only on Windows; the
platform-neutral escape tests in test_publication_evidence.py also run there."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from autodebug import cli
from autodebug.evidence import EvidenceStore, is_link, is_private_dir, secure_storage_supported

WINDOWS = os.name == "nt"


def junction(link: Path, target: Path) -> None:
    """Create a directory junction (no special privilege needed)."""
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


def grant_everyone(path: Path) -> None:
    subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:(OI)(CI)F"], check=True, capture_output=True)


def record(store, value="1"):
    return store.record_evidence(
        event_type="paused", session_id="s", source_revision="r", frame="f",
        observation_name="counter", observation_value=value, expected="1", confidence="observation-only",
    )


@unittest.skipUnless(WINDOWS, "Windows evidence backend")
class WindowsEvidenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="autodebug-win-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.base = self.tmp / "base"
        cli.make_private_dir(self.base)

    def test_storage_is_supported_and_round_trips(self):
        self.assertTrue(secure_storage_supported())
        store = EvidenceStore(self.base, "case")
        first, second = record(store, "1"), record(store, "2")
        self.assertEqual(store.read_events(), (first, second))
        store.finalize(case_state="cancelled", report=None)
        self.assertTrue(store.case_path.is_file())
        raw = store.events_path.read_bytes()
        self.assertNotIn(b"\r\n", raw)  # identical LF line endings on every platform
        self.assertEqual(raw.count(b"\n"), 2)

    def test_new_directories_are_private(self):
        store = EvidenceStore(self.base, "case")
        self.assertTrue(is_private_dir(self.base))
        self.assertTrue(is_private_dir(store.case_dir))

    def test_base_open_to_everyone_is_refused(self):
        public = self.tmp / "public"
        public.mkdir()
        grant_everyone(public)
        self.assertFalse(is_private_dir(public))
        with self.assertRaises(PermissionError):
            EvidenceStore(public, "case")
        self.assertFalse((public / "case").exists())

    def test_case_directory_replaced_by_junction_cannot_escape(self):
        store = EvidenceStore(self.base, "case")
        store.case_dir.rename(self.base / "moved")
        external = self.tmp / "external"
        external.mkdir()
        junction(store.case_dir, external)
        self.assertTrue(is_link(store.case_dir))
        for operation in (
            lambda: record(store),
            store.read_events,
            lambda: store.finalize(case_state="cancelled", report=None),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises((OSError, ValueError)):
                    operation()
        self.assertEqual(list(external.iterdir()), [])

    def test_artifact_replaced_by_junction_is_refused(self):
        store = EvidenceStore(self.base, "case")
        external = self.tmp / "external"
        external.mkdir()
        junction(store.case_path, external)
        with self.assertRaises((OSError, ValueError)):
            store.finalize(case_state="cancelled", report=None)
        self.assertEqual(list(external.iterdir()), [])

    def test_existing_case_name_as_junction_is_not_reused(self):
        target = self.tmp / "elsewhere"
        target.mkdir()
        junction(self.base / "case", target)
        with self.assertRaisesRegex(ValueError, "already exists"):
            EvidenceStore(self.base, "case")

    def test_failed_snapshot_leaves_no_temporary_file(self):
        store = EvidenceStore(self.base, "case")
        with self.assertRaises(RuntimeError):
            with store._open_file("case.json", "w") as stream:
                stream.write("partial")
                raise RuntimeError("interrupted")
        self.assertEqual(list(store.case_dir.iterdir()), [])

    def test_snapshot_replaces_previous_version(self):
        store = EvidenceStore(self.base, "case")
        store.finalize(case_state="cancelled", report=None)
        store.finalize(case_state="incomplete", report=None)
        self.assertIn('"incomplete"', store.case_path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(p.name for p in store.case_dir.iterdir()), ["case.json", "events.jsonl"])

    def test_cli_refuses_junction_evidence_root(self):
        target = self.tmp / "target"
        target.mkdir()
        root = self.tmp / "root"
        junction(root, target)
        with self.assertRaises(ValueError):
            cli.create_run_dir(root)
        self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
