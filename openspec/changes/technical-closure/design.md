# Design

Extend existing frozen contracts and the facade rather than replacing the
architecture. Script bytes are review data, never executed. Native stop snapshots
are an explicit adapter contract; synthetic identities are labeled synthetic.
Unknown native stop/start identity is unsupported, never a fabricated generation.

Bound calls using cancellation/deadline contexts. If an injected implementation
fails to return, reject its result and quarantine its target/session before
releasing the calling operation. Do not pretend a Python thread can forcibly
undo an external debugger action; native enablement requires a separately
verified cooperative backend. Late launch results are cleaned up, not registered
as an authorized case.

Keep per-session ownership through registry refresh and validate it on every
operation. Serialize lifecycle transitions and snapshot writes. Reports preserve
terminal incomplete/cancelled state rather than relabeling it FINALIZED.
Persist sanitized versioned evidence, with exact stop/process context.

Use an original, stdlib-only MCP stdio implementation with bounded JSON and
strict decoding. Offline wheel generation must not download a build tool.
The CLI may seed only an explicitly selected isolated synthetic demonstration;
an MCP request cannot grant approval or select a native backend.
