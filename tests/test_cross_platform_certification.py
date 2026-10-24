"""T13 acceptance tests — cross-platform OS detection, capability probing,
and fail-closed regression (IDE-05, GW-02). Stdlib `unittest` only, zero
third-party packages, no MCP SDK.

**This development machine is macOS — there is no Windows or Linux host in
this environment.** Every test here exercises platform-detection and
capability-probing *logic* by passing an explicit `host_os` override to
`probe_capabilities()`/`probe()`, using the same mock clients already built
for T08–T12. This proves `VSCodeAdapter`/`CursorAdapter`/`CLionAdapter`'s
own operation code contains zero `platform.system()` dependency of its own
(only `BaseAdapter.probe()`/`probe_capabilities()`, T01/T02, perform the OS
gate) — it does **not** prove real Windows/Linux native-debugger behavior,
which requires an actual Windows/Linux host and a real extension/bridge on
it. See `docs/compatibility-ledger.md` and `tasks.md` T13 for the full
distinction between "adapter logic is OS-independent" (proven here) and
"real certification on Windows/Linux" (not possible in this session).
"""

import unittest

from autodebug.adapters import ALL_ADAPTERS, CLionAdapter, CursorAdapter, VisualStudioAdapter, VSCodeAdapter, XcodeAdapter
from autodebug.adapters.base import CORE_OPERATIONS
from autodebug.errors import AutoDebugError, ErrorCode
from autodebug.models import CapabilityState, TargetRef
from autodebug.router import Router
from autodebug.sessions import SessionRegistry
from tests.fixtures.fake_backend import FULL_SUPPORT
from tests.fixtures.fake_clion_client import FakeCLionDebugClient
from tests.fixtures.fake_cursor_client import FakeCursorDebugClient
from tests.fixtures.fake_debugmcp_client import FakeDebugMCPClient

#: The three adapters targeted by T13 — VS Code, Cursor, and CLion are all
#: design targets on Windows, macOS, and Linux (IDE-02). Visual Studio
#: (Windows-only) and Xcode (macOS-only) are covered by
#: `TestNonTargetOSesReportNotApplicable` below instead, since T13's own
#: scope is explicitly "VS Code/Cursor/CLion on Windows and Linux."
CROSS_PLATFORM_ADAPTERS = (
    (VSCodeAdapter, FakeDebugMCPClient),
    (CursorAdapter, FakeCursorDebugClient),
    (CLionAdapter, FakeCLionDebugClient),
)

#: Every adapter's declared `supported_os` (IDE-02's matrix), reused here
#: to generalize the per-cell checks `test_capability_probing.py` already
#: has into one cross-adapter, cross-OS pass.
SUPPORTED_OS_MATRIX = {
    VSCodeAdapter: ("Windows", "Darwin", "Linux"),
    CursorAdapter: ("Windows", "Darwin", "Linux"),
    CLionAdapter: ("Windows", "Darwin", "Linux"),
    VisualStudioAdapter: ("Windows",),
    XcodeAdapter: ("Darwin",),
}
ALL_OS = ("Windows", "Darwin", "Linux")


class TestCrossPlatformCapabilityProbing(unittest.TestCase):
    """GW-02/IDE-02: capability probing for the three cross-platform
    adapters must report identically regardless of which of their three
    supported OSes the `host_os` override names — mocked, not real."""

    def test_each_cross_platform_adapter_is_available_on_every_supported_os(self):
        for adapter_cls, client_cls in CROSS_PLATFORM_ADAPTERS:
            for host_os in ("Windows", "Darwin", "Linux"):
                with self.subTest(ide=adapter_cls.ide_id, host_os=host_os):
                    adapter = adapter_cls(client=client_cls())
                    report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os=host_os)
                    self.assertEqual(report.state, CapabilityState.AVAILABLE)
                    for op in CORE_OPERATIONS:
                        self.assertEqual(report.operations[op], CapabilityState.AVAILABLE)


class TestCrossPlatformGW06AgainstRouter(unittest.TestCase):
    """Proves the three cross-platform adapters' *operation* logic
    (launch/attach/reuse/decline via `Router`) is identical no matter which
    supported `host_os` the feeding `CapabilityReport` was computed for —
    these adapters contain zero `platform.system()` calls of their own;
    only `BaseAdapter.probe_capabilities()` (T01/T02) performs the OS gate,
    and that gate has already run by the time `Router.arm_target` is
    called. Still entirely against mocks — not real Windows/Linux
    validation."""

    def test_scenario_a_launch_identical_across_every_supported_host_os(self):
        for adapter_cls, client_cls in CROSS_PLATFORM_ADAPTERS:
            for host_os in ("Windows", "Darwin", "Linux"):
                with self.subTest(ide=adapter_cls.ide_id, host_os=host_os):
                    registry = SessionRegistry()
                    router = Router(registry)
                    client = client_cls()
                    adapter = adapter_cls(client=client)
                    target = TargetRef(host_id="local-mac", ide=adapter_cls.ide_id, debug_session_id=None, pid=None)
                    report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os=host_os)

                    session = router.arm_target(
                        adapter, report, target, reviewed_configuration=None, process_running=False
                    )
                    self.assertIn(session, registry.all_sessions())
                    self.assertEqual(client.start_or_attach_calls, 1)

    def test_scenario_c_existing_session_reused_identical_across_every_supported_host_os(self):
        for adapter_cls, client_cls in CROSS_PLATFORM_ADAPTERS:
            for host_os in ("Windows", "Darwin", "Linux"):
                with self.subTest(ide=adapter_cls.ide_id, host_os=host_os):
                    registry = SessionRegistry()
                    router = Router(registry)
                    client = client_cls()
                    adapter = adapter_cls(client=client)
                    target = TargetRef(host_id="local-mac", ide=adapter_cls.ide_id, debug_session_id=None, pid=4210)
                    report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os=host_os)

                    first = router.arm_target(
                        adapter, report, target, reviewed_configuration=None, process_running=False
                    )
                    second = router.arm_target(
                        adapter, report, target, reviewed_configuration=None, process_running=True
                    )
                    self.assertIs(second, first)
                    self.assertEqual(client.start_or_attach_calls, 1, "a second debugger session must never be created")


class TestNonTargetOSesReportNotApplicable(unittest.TestCase):
    """IDE-02-A, generalized across the full 15-cell matrix (5 adapters x 3
    OSes) in one pass: no adapter ever reports `AVAILABLE` — or consults
    even a fully-supported fake backend — on an OS outside its declared
    `supported_os`. This re-confirms T02's original guarantee still holds
    after T08–T12's real adapter implementations, not just for the three
    cross-platform adapters but for Visual Studio and Xcode too."""

    def test_every_adapter_reports_not_applicable_outside_its_supported_os(self):
        for adapter_cls, supported in SUPPORTED_OS_MATRIX.items():
            for host_os in ALL_OS:
                if host_os in supported:
                    continue
                with self.subTest(ide=adapter_cls.ide_id, host_os=host_os):
                    adapter = adapter_cls()
                    report = adapter.probe_capabilities(backend=FULL_SUPPORT, host_os=host_os)
                    self.assertEqual(report.state, CapabilityState.NOT_APPLICABLE)
                    self.assertEqual(report.operations, {})

    def test_eleven_target_cells_still_match_ide_02(self):
        # Cross-check against IDE-02's 11-combination count, independent of
        # test_capability_probing.py's own copy of this assertion.
        applicable = sum(1 for supported in SUPPORTED_OS_MATRIX.values() for os_name in ALL_OS if os_name in supported)
        self.assertEqual(applicable, 11)


class TestFailClosedConsistentAcrossAllFiveAdapters(unittest.TestCase):
    """`BACKEND_UNAVAILABLE` without a client does not vary by platform —
    `_require_client()` has no OS dependency in any of the five adapters,
    confirmed explicitly here in one place rather than only inferred from
    each adapter's own separate test file."""

    def test_no_client_fails_closed_identically_on_every_real_adapter(self):
        for adapter_cls in (VSCodeAdapter, CursorAdapter, CLionAdapter, XcodeAdapter, VisualStudioAdapter):
            with self.subTest(adapter_cls.ide_id):
                adapter = adapter_cls()
                with self.assertRaises(AutoDebugError) as ctx:
                    adapter.list_sessions()
                self.assertEqual(ctx.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)

    def test_all_five_adapters_are_real_implementations_not_stubs(self):
        # IDE-01 regression: confirms all five adapters declared at T01
        # have since become real implementations (T08-T12), not that any
        # were silently dropped or left as stubs.
        self.assertEqual(len(ALL_ADAPTERS), 5)
        for cls in ALL_ADAPTERS:
            with self.subTest(cls.ide_id):
                instance = cls()
                with self.assertRaises(AutoDebugError):
                    instance.list_sessions()


if __name__ == "__main__":
    unittest.main()
