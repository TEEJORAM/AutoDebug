# IDE/OS compatibility ledger (`IDE-05`)

**VS Code and Cursor** now have a real path, the AutoDebug Bridge
([ide-debug-bridge](../openspec/changes/ide-debug-bridge/proposal.md); T05 gate
approved for `vscode-bridge` only on 2026-10-24). It has not yet run in a real
IDE window, so its cells below stay `NOT_TESTED`. The other adapters are tested
only against mocks. There are **zero `PASS` cells**.

## AutoDebug Bridge evidence — 2026-10-24

| Check | Environment | Result |
|---|---|---|
| Extension core over the real protocol, scripted debug session (`tests/test_bridge_extension.py`) | CI: Windows, macOS, Ubuntu; Python 3.11/3.12/3.14 with Node | Pass |
| Extension core with the **real Python debugger** debugpy 1.8.11 over real DAP on AutoDebugDemo (`tests/test_bridge_debugpy.py`) | Linux, Python 3.13, Node 22; stand-in IDE API | Pass: breakpoint bound at `geometry.py:15`, real stop, stack, variables, step over and continue, report written |
| Same in a real VS Code or Cursor window | — | `NOT_TESTED`: first run by the developer |

## Historical evidence summary — 2026-10-22, T08–T13

Read-only local availability checks recorded five blocked/unavailable validation
paths. Private workstation paths, extension inventories, and configuration contents
are omitted for publication preparation; these findings remain historical local
observations, not product-wide capability claims or fresh checks.

Six Windows/Linux targets were not tested. Mocked OS-parameter tests in
`tests/test_cross_platform_certification.py` exercise adapter logic, not real
platform integration. Eleven intended targets plus four `N/A` cells appear below.

| IDE | OS | Status | Check date | Recorded IDE/backend availability | Evidence and limitation |
|---|---|---|---|---|---|
| VS Code | macOS | `BLOCKED` | 2026-10-22 | DebugMCP not available; IDE version not recorded | T08 local availability check; `tests/test_ide_adapters.py` uses `FakeDebugMCPClient` only. 0/8 real `IDE-04-B` criteria verified. |
| VS Code | Windows | `NOT_TESTED` | — | No test host available | T13 mocked OS coverage only; no real version or native-session evidence. |
| VS Code | Linux | `NOT_TESTED` | — | No test host available | Same T13 limitation. |
| Cursor | macOS | `BLOCKED` | 2026-10-22 | Editor present; no native-debugger MCP backend available; IDE version not recorded | T09 independent local availability check; `tests/test_ide_adapters.py` uses `FakeCursorDebugClient` only. 0/8 real criteria verified. |
| Cursor | Windows | `NOT_TESTED` | — | No test host available | T13 mocked OS coverage only. |
| Cursor | Linux | `NOT_TESTED` | — | No test host available | Same T13 limitation. |
| CLion | macOS | `UNSUPPORTED` | 2026-10-22 | IDE not available | T10 local availability check; historical task used `UNSUPPORTED` for missing IDE, not a verdict on JetBrains product capabilities. `tests/test_ide_adapters.py` uses `FakeCLionDebugClient` only; 0/8 real criteria verified. |
| CLion | Windows | `NOT_TESTED` | — | No test host available | T13 mocked OS coverage only. |
| CLion | Linux | `NOT_TESTED` | — | No test host available | Same T13 limitation. |
| Visual Studio (full IDE) | Windows | `BLOCKED` | 2026-10-22 | No Windows test host available | T12 environment finding; `tests/test_ide_adapters.py` uses `FakeVisualStudioDebugClient` only; 0/8 real criteria verified. No claim that a native bridge cannot work. |
| Visual Studio (full IDE) | macOS | `N/A` | — | Not a target | `IDE-02`. |
| Visual Studio (full IDE) | Linux | `N/A` | — | Not a target | `IDE-02`. |
| Xcode | macOS | `UNSUPPORTED` | 2026-10-22 | Xcode 26.0.1, build 17A400; `mcpbridge` unavailable in that installation | T11 developer-tool availability check; `tests/test_ide_adapters.py` uses `FakeXcodeDebugClient` only; 0/8 real criteria verified. This is not a verdict on other Xcode versions/installations. |
| Xcode | Windows | `N/A` | — | Not a target | `IDE-02`. |
| Xcode | Linux | `N/A` | — | Not a target | `IDE-02`. |

The VS Code historical record inconsistently labeled the IDE itself absent while
describing an installed editor without DebugMCP. The table does not resolve that
ambiguity by inventing a version or current installation claim: the decisive
recorded blocker is the unavailable DebugMCP backend.

## States and update rules

`PASS` requires all eight `IDE-04-B` native-session criteria: exact session identity,
bound breakpoint, observed stop, stack, selected variables, supported step/continue,
unsupported-operation handling, and no hidden second debugger. A successful MCP
connection or tool list alone is insufficient. `PARTIAL` names verified operations
and gaps; `UNSUPPORTED` identifies unavailable tested capability; `BLOCKED` states
why testing cannot proceed; `NOT_TESTED` records no test; `N/A` is outside scope.

Only update a result after a real test actually runs. Record its date, exact OS,
IDE/backend versions, verified operations, sanitized evidence reference, and
limitations. Do not fill missing historical versions by guessing. See
`docs/test-plan.md` §4a and the relevant task in `tasks.md`.

Future tests require a disposable local application built solely for testing with
synthetic stack/variable data: never an Autodesk product, customer code/data, or
real credentials. Follow `docs/security-gate-closure-proposal.md` §6 and obtain the
required approvals before real debugger actions. Link safe evidence, not private
captures or workstation configuration, in this ledger.
