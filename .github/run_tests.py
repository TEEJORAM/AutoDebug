"""Run the unittest suite in CI and surface failures as GitHub annotations,
so failures are readable from the run summary without downloading logs."""

import sys
import unittest

names = sys.argv[1:]
loader = unittest.defaultTestLoader
suite = loader.loadTestsFromNames(names) if names else loader.discover("tests")
result = unittest.TextTestRunner(verbosity=1).run(suite)
for test, trace in (result.failures + result.errors)[:10]:
    message = trace[-3000:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={test.id()}::{message}")
sys.exit(0 if result.wasSuccessful() else 1)
