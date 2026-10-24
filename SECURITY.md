# Security policy

## Scope

AutoDebug is a local, fake-only MCP stdio server with a synthetic demo. It is
not a production deployment: no IDE adapter is validated against a real
debugger, the real-debugger approval gate is **OPEN / NOT APPROVED**, and there
is no supported-version or response-time commitment. See
[docs/security.md](docs/security.md).

## Reporting a vulnerability

**Do not post exploit details, proof-of-concept code, secrets, debugger captures
or internal information in public issues, pull requests or discussions.**

No dedicated reporting address has been approved yet. Use an existing
organization-approved private security channel, or contact the project owner
privately to arrange one. If GitHub private vulnerability reporting is enabled
and documented here later, use that.

Include the affected revision, a minimal synthetic reproduction, expected versus
observed behaviour, impact and platform versions. Leave out real credentials,
customer or company data and memory captures. This policy grants no permission
to test third-party or production systems.

## Operating rules

Keep human approval bound to plan, script, target and expiry; fail closed on
session routing; keep non-production defaults; keep expression evaluation
denied. Localhost does not stop an AI client from sending observations to its
model provider, so Autodesk data-handling and model-routing approvals still
apply.
