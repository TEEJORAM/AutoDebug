# Native Windows evidence storage

Requested by the developer on 2026-10-24 ("full Windows protection"). Evidence
storage refused to run on Windows because its safety checks used POSIX-only
calls, so no case could run on native Windows.

Scope: a Windows backend for `EvidenceStore` with the same guarantees as the
POSIX one, built only on the standard library (`ctypes` with `kernel32`,
`advapi32` and `ntdll`); private directory creation for the CLI; full test
suite on Windows CI.

Out of scope: native debugger integration, the T05 gate, new dependencies.
