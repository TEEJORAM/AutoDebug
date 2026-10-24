# AutoDebug — License, ownership, and dependency review (T15)

**Inventory only; publication blocked pending authorization.** Preparation of
publication-facing files does not authorize publication, distribution, a license
assignment, or any claim of personal ownership. No `LICENSE` file is assigned.
Autodesk ownership/copyright and OSSA/Legal review must determine release rights,
license choice, notices, and attribution before any public release.

## Recorded dependency inventory

| Item | Recorded role | Review status |
|---|---|---|
| Python standard library | Runtime and `unittest` tests; `pyproject.toml` declares `dependencies = []` | No third-party runtime package is declared. This is not an exemption from copyright, license, enterprise, or release review. |
| Original `build_backend.py` | Stdlib-only PEP 517 wheel/sdist builder; no build requirements | No third-party build dependency. Exact candidate archive still requires ownership, notices and release review. |
| MCP SDK / real adapter client libraries | Not declared; original MCP 2025-11-25 stdio binding uses stdlib | No installation authorized here. Review and pin any future external packages; native integrations remain unapproved. |

No package was installed or license selected during this publication-preparation
step. Do not infer "nothing needs approval" from an empty runtime dependency list.
Python and build tooling have their own license/notice terms, to be verified for
the exact approved distribution rather than guessed from this inventory.

## External integrations and originality

The project records independently written adapter abstractions and a prohibition
on copying/forking/vendoring Microsoft DebugMCP or internal Autodesk bridge source.
All five adapters have been validated only against mocks; no native IDE integration
is certified. Historical local checks found required backends unavailable or
untestable; private workstation and configuration details are omitted.

| Referenced integration | Boundary requiring review |
|---|---|
| Microsoft DebugMCP | External, separately installed MCP service only after approval; public API access is not permission to copy implementation. |
| Cursor native-debugger surface | Actual backend/schema and permitted use remain unverified. |
| JetBrains / CLion MCP | Verify advertised tools, installed version, terms, and enterprise permissions before real integration. |
| Apple / Xcode tooling | Verify supported facilities and applicable terms; no legal exemption is assumed for vendor tooling. |
| Visual Studio bridge / public SDK | Internal bridge reuse/distribution requires maintainer and Autodesk authorization; public SDK use also requires terms review. |

These are references, not installed dependencies or a legal finding that no
obligation exists. No repository import inventory can establish ownership or
prove legal clearance.

## Provenance, data, and full-history approval

AutoDebug originated in an Autodesk-related development context. Internal source,
Jira data, company documents, and bridge code must not be published without
authorization. Historical Fusion examples retain their original safety boundary:
existing scripting UI or already-approved supported facilities only, with no new
helper or undocumented injection. Those examples do not establish product access
or permission to disclose company information.

Current-tree edits generalize internal repository/wiki locators, reviewer identity,
workstation paths, and operational configuration. They do **not** remove historical
blobs or commit authors, committers, messages, email addresses, and trailers. The
local history audit is sensitive review material, not a public artifact.

Before publication, authorized reviewers must record:

1. Autodesk ownership/copyright and OSSA/Legal release authorization.
2. Approved license choice and any required notices/attribution; then, and only
   then, an authorized `LICENSE` assignment.
3. Third-party dependency, referenced-code provenance, distribution/reuse, and
   trademark/terms review as applicable.
4. Full Git-history and metadata disposition, including any separately approved
   sanitization/rewrite or approved clean export. No history rewrite is authorized
   or performed by this preparation.
5. Security/data-handling and independent T15 sign-off, plus explicit authorization
   of the exact publication artifact and destination.

Passing tests, retaining approval quotes for implementation, or removing internal
URLs does not satisfy any of these release approvals. See the
[release checklist](release-readiness-checklist.md).
