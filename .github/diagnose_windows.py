"""Temporary diagnostics for the Windows evidence backend."""
import os, sys, tempfile, traceback
from pathlib import Path
sys.path.insert(0, "src")
from autodebug import _winfs
from autodebug.evidence import EvidenceStore

def note(title, text):
    print(f"::error title={title}::" + text.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))

for label, make in (("tempdir", lambda: Path(tempfile.mkdtemp())), ("tempdir-sub", lambda: Path(tempfile.mkdtemp()) / "evidence")):
    try:
        base = make()
        store = EvidenceStore(base, "DIAG")
        store.record_evidence(event_type="e", session_id="s", source_revision="r", frame="f", observation_name="n",
                              observation_value="v", expected="", confidence="c")
        store.finalize(case_state="cancelled", report=None)
        note(f"{label} OK", repr(store.read_events()[0].evidence_id))
    except BaseException:
        info = ""
        try:
            info = f"private={_winfs.is_private_directory(str(make()))}"
        except BaseException as exc:
            info = repr(exc)
        note(f"{label} FAILED", info + "\n" + traceback.format_exc())

import subprocess
d = tempfile.mkdtemp()
note("icacls mkdtemp", subprocess.run(["icacls", d], capture_output=True, text=True).stdout)
