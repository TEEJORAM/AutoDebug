"""A deterministic, in-memory stand-in for a real IDE/debugger backend.

Used only by tests (see docs/architecture.md's recommended `tests/fixtures/`
layout and CLAUDE.md's "mock/fake backend for deterministic tests" rule).
No adapter imports this at runtime — adapters only know the
`BackendDescription` shape declared in `autodebug.adapters.base`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autodebug.adapters.base import CORE_OPERATIONS


@dataclass(frozen=True)
class FakeBackend:
    installed: bool = True
    reachable: bool = True
    ide_version: str | None = "1.0.0-fake"
    backend_version: str | None = "1.0.0-fake"
    supported_operations: frozenset[str] = field(default_factory=frozenset)


#: Backend not installed at all (GW-02-A, e.g. "Xcode is not installed").
NOT_INSTALLED = FakeBackend(installed=False, ide_version=None, backend_version=None)

#: Backend installed but currently unreachable (transport down).
UNREACHABLE = FakeBackend(reachable=False, backend_version=None)

#: Backend installed, reachable, and advertises every core operation.
FULL_SUPPORT = FakeBackend(supported_operations=frozenset(CORE_OPERATIONS))

#: Backend installed, reachable, but does not advertise stack inspection
#: (GW-02-B, "a connected backend does not advertise stack inspection").
NO_STACK_SUPPORT = FakeBackend(
    supported_operations=frozenset(CORE_OPERATIONS) - {"get_stack"}
)
