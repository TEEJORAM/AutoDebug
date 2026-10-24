# Security policy

## Current scope

AutoDebug provides a local fake-only MCP stdio server and synthetic demonstration,
not an authorized production deployment or native-debugger integration.
All five native IDE adapters lack real-debugger validation; the real-debugger
approval gate remains **OPEN / NOT APPROVED**. No production-supported release,
security certification, response SLA, or supported-version maintenance policy is
established here. See `docs/status.md` and `docs/security.md`.

## Report privately

**Do not publish exploit details, proof-of-concept code, secrets, debugger captures,
or internal information in public issues, pull requests, discussions, or logs.**

No project-specific private mailbox or public repository reporting URL has been
approved. Authorized collaborators should use an existing organization-approved
private security channel or contact the project owner through an already-known
private channel to arrange secure intake. If no verified private channel is
available, do not upload sensitive details; first obtain one from the owner.
If the repository is later published with private vulnerability reporting enabled,
use that verified facility only after the owner documents it here.

In the private report, provide the affected revision, minimal synthetic
reproduction, expected versus observed behavior, impact, and relevant platform
versions. Exclude real credentials, customer/company data, local identity details,
and raw memory captures. Coordinate any disclosure with the authorized security
and ownership reviewers; this policy grants no permission to test third-party or
production systems and promises no disclosure deadline or bounty.

## Operating restrictions

Preserve independent human approval bound to plan/script/target/expiration,
fail-closed session routing, nonproduction defaults, and denied-by-default
expression evaluation. Use no real debugger under fake approvals. Fusion remains
a historical safety example: existing scripting UI or already-approved supported
facilities only, never a new helper or undocumented injection.

Localhost does not prevent an AI client from sending observations to a model
provider. Autodesk data-handling, third-party package/MCP, and model-routing
approvals remain required. Publication additionally needs ownership/copyright,
OSSA/Legal, license, and full-history review; no `LICENSE` is assigned.
