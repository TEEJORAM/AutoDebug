"""Run the unittest suite in CI and surface failures as GitHub annotations,
so failures are readable from the run summary without downloading logs."""

import os
import sys
import unittest

sys.path.insert(0, os.getcwd())  # same import roots as `python -m unittest`
names = sys.argv[1:]
loader = unittest.defaultTestLoader
suite = loader.loadTestsFromNames(names) if names else loader.discover("tests")
result = unittest.TextTestRunner(verbosity=1).run(suite)
# Annotations are capped at 10 per step: report the most specific modules first.
problems = sorted(result.failures + result.errors, key=lambda item: ("windows" not in item[0].id(), "evidence" not in item[0].id()))
for test, trace in problems[:10]:
    message = trace[-3000:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={test.id()}::{message}")
skipped = sorted({reason for _, reason in result.skipped})
print(f"::notice title=Test summary::ran {result.testsRun}, failures {len(result.failures)}, "
      f"errors {len(result.errors)}, skipped {len(result.skipped)} ({'; '.join(skipped) or 'none'})")
sys.exit(0 if result.wasSuccessful() else 1)
