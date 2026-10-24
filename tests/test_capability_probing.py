"""T02 acceptance tests — stdlib `unittest` only, zero third-party packages.

Covers tasks.md T02's acceptance criteria: platform-matrix tests (IDE-02) and
unknown/unsupported-tool contract tests (GW-02), all against the deterministic
`FakeBackend` fixture. No real IDE, debugger, or network is contacted.
"""

import unittest

from autodebug.adapters import ALL_ADAPTERS, CLionAdapter, CursorAdapter, VisualStudioAdapter, VSCodeAdapter, XcodeAdapter
from autodebug.adapters.base import CORE_OPERATIONS
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.models import CapabilityState
from tests.fixtures.fake_backend import FULL_SUPPORT, NO_STACK_SUPPORT, NOT_INSTALLED, UNREACHABLE

# IDE-02's exact OS availability matrix: one row per adapter class, columns are
# ("Windows", "Darwin", "Linux") -> True if that cell is a target, else False.
IDE_02_MATRIX = {
    VSCodeAdapter: (True, True, True),
    CursorAdapter: (True, True, True),
    CLionAdapter: (True, True, True),
    VisualStudioAdapter: (True, False, False),
    XcodeAdapter: (False, True, False),
}
OS_COLUMNS = ("Windows", "Darwin", "Linux")


class TestPlatformMatrix(unittest.TestCase):
    """IDE-02: the 11-target OS availability matrix, all 15 cells (5 adapters
    x 3 OSes), independent of which machine actually runs this test."""

    def test_eleven_target_cells_are_applicable(self):
        applicable = sum(1 for cols in IDE_02_MATRIX.values() for is_target in cols if is_target)
        self.assertEqual(applicable, 11)

    def test_every_cell_matches_the_documented_matrix(self):
        for cls, expectation in IDE_02_MATRIX.items():
            instance = cls()
            for host_os, is_target in zip(OS_COLUMNS, expectation):
                with self.subTest(ide=cls.ide_id, host_os=host_os):
                    result = instance.probe(host_os=host_os)
                    if is_target:
                        self.assertNotEqual(result.state, CapabilityState.NOT_APPLICABLE)
                    else:
                        self.assertEqual(result.state, CapabilityState.NOT_APPLICABLE)

    def test_wrong_os_never_probes_a_backend_even_if_one_is_supplied(self):
        # IDE-02-A: "does not try to spawn xcrun" generalized — a wrong-OS
        # adapter must report NOT_APPLICABLE even when handed a fully
        # supported fake backend; it must never be consulted.
        xcode = XcodeAdapter()
        report = xcode.probe_capabilities(backend=FULL_SUPPORT, host_os="Linux")
        self.assertEqual(report.state, CapabilityState.NOT_APPLICABLE)
        self.assertEqual(report.operations, {})

        vs = VisualStudioAdapter()
        report = vs.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")
        self.assertEqual(report.state, CapabilityState.NOT_APPLICABLE)
        self.assertEqual(report.operations, {})


class TestCapabilityStatesAreDistinct(unittest.TestCase):
    """GW-02: UNKNOWN, UNSUPPORTED, UNAVAILABLE and NOT_APPLICABLE must all be
    independently reachable outcomes, never collapsed into one another."""

    def test_not_probed_yet_is_unknown(self):
        adapter = VSCodeAdapter()
        report = adapter.probe_capabilities(backend=None, host_os="Darwin")
        self.assertEqual(report.state, CapabilityState.UNKNOWN)

    def test_missing_backend_is_unavailable_with_a_reason_not_invented_tools(self):
        # GW-02-A: "Xcode is not installed" -> UNAVAILABLE with a reason, and
        # every operation is reported UNAVAILABLE, never AVAILABLE.
        adapter = XcodeAdapter()
        report = adapter.probe_capabilities(backend=NOT_INSTALLED, host_os="Darwin")
        self.assertEqual(report.state, CapabilityState.UNAVAILABLE)
        self.assertTrue(report.reason)
        self.assertEqual(set(report.operations.values()), {CapabilityState.UNAVAILABLE})

    def test_unreachable_backend_is_unavailable(self):
        adapter = CLionAdapter()
        report = adapter.probe_capabilities(backend=UNREACHABLE, host_os="Darwin")
        self.assertEqual(report.state, CapabilityState.UNAVAILABLE)

    def test_connected_backend_missing_one_operation_is_unsupported_for_that_operation_only(self):
        # GW-02-B: backend doesn't advertise stack inspection -> that specific
        # operation is UNSUPPORTED; every other advertised operation stays
        # AVAILABLE (no blanket failure, no fake stack).
        adapter = CursorAdapter()
        report = adapter.probe_capabilities(backend=NO_STACK_SUPPORT, host_os="Darwin")
        self.assertEqual(report.operations["get_stack"], CapabilityState.UNSUPPORTED)
        for op in CORE_OPERATIONS:
            if op != "get_stack":
                self.assertEqual(report.operations[op], CapabilityState.AVAILABLE)
        self.assertEqual(report.state, CapabilityState.UNSUPPORTED)

    def test_fully_supported_backend_is_available(self):
        adapter = VSCodeAdapter()
        report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")
        self.assertEqual(report.state, CapabilityState.AVAILABLE)
        self.assertEqual(set(report.operations.values()), {CapabilityState.AVAILABLE})
        self.assertEqual(report.ide_version, FULL_SUPPORT.ide_version)
        self.assertEqual(report.backend_version, FULL_SUPPORT.backend_version)


class TestRequireCapabilityContract(unittest.TestCase):
    """GW-02-B as an enforcement contract: requesting an unsupported operation
    raises CAPABILITY_UNSUPPORTED instead of returning a fabricated result —
    this is the "unknown-tool contract test" named in tasks.md T02."""

    def test_unsupported_operation_raises_capability_unsupported(self):
        adapter = CursorAdapter()
        report = adapter.probe_capabilities(backend=NO_STACK_SUPPORT, host_os="Darwin")
        with self.assertRaises(AutoDebugError) as ctx:
            adapter.require_capability(report, "get_stack")
        self.assertEqual(ctx.exception.detail.code, ErrorCode.CAPABILITY_UNSUPPORTED)

    def test_supported_operation_does_not_raise(self):
        adapter = CursorAdapter()
        report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")
        adapter.require_capability(report, "get_stack")  # must not raise

    def test_unknown_tool_name_is_treated_as_unsupported_not_fabricated(self):
        # A tool AutoDebug has never heard of must fail closed exactly like an
        # explicitly-unsupported one, never silently succeed.
        adapter = CursorAdapter()
        report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os="Darwin")
        with self.assertRaises(AutoDebugError) as ctx:
            adapter.require_capability(report, "evaluate_expression")
        self.assertEqual(ctx.exception.detail.code, ErrorCode.CAPABILITY_UNSUPPORTED)


class TestIDE01StillHoldsAfterT02(unittest.TestCase):
    """Regression guard: T02 must not weaken T01's IDE-01 guarantees."""

    def test_exactly_five_adapters_still_declared(self):
        self.assertEqual(len(ALL_ADAPTERS), 5)

    def test_probe_capabilities_never_claims_support_for_an_unprobed_adapter(self):
        for cls in ALL_ADAPTERS:
            adapter = cls()
            with self.subTest(cls.ide_id):
                report = adapter.probe_capabilities(backend=None, host_os=adapter.supported_os[0])
                self.assertIn(
                    report.state,
                    (CapabilityState.UNKNOWN, CapabilityState.NOT_APPLICABLE),
                )


if __name__ == "__main__":
    unittest.main()
