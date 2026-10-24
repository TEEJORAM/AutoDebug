# AutoDebug — Architecture decision records (ADRs)

These record the *why* behind long-lived design choices. Changing a decision requires a reviewed new ADR and, where behavior changes, an updated capability spec.

## ADR-001 — One Python MCP gateway; no custom debugger engine
- **Status:** Proposed — part of G00 review.
- **Decision:** Build a typed, versioned gateway that routes to existing **native IDE debugger** bridges.
- **Reason:** Native IDEs differ; a full debugger implementation adds huge scope, while common contracts allow reuse.
- **Tradeoff:** Adapter capabilities depend on backend versions.

## ADR-002 — Five adapters at foundation; platform-specific certification
- **Status:** Proposed.
- **Decision:** Five module definitions from T01; support target of VS Code/Cursor/CLion on Windows/macOS/Linux, Visual Studio on Windows, Xcode on macOS.
- **Reason:** Architectural coverage from day one without claiming complete implementations.
- **Tradeoff:** Tenants without certain IDEs return not applicable/unavailable; 11-case matrix needs separate lab work.

## ADR-003 — AI investigator lives in client, not AutoDebug
- **Status:** Proposed.
- **Decision:** Client agent owns Jira/doc retrieval, source analysis, hypothesis evaluation and RCA narrative. Server owns tool execution, session safety and evidence storage.
- **Reason:** Any compliant AI client can use the same debugger tools; avoid embedding a second agent/model.

## ADR-004 — Developer owns application API-script execution
- **Status:** User-directed.
- **Decision:** No new Fusion helper. Developer runs reviewed Fusion API script through existing Scripts and Add-Ins UI; manual steps used otherwise.
- **Reason:** Avoid injecting unverified application runtime code or promising automation without a supported invocation path.

## ADR-005 — Explicit, bound approval and native session identity
- **Status:** Proposed, **requires security validation**.
- **Decision:** Agent cannot approve itself. Approvals are tied to immutable plan/script hash and selected native session with expiry.
- **Reason:** Wrong debugger/process or script can have destructive consequences.
- **Blocking tradeoff:** An agent with unrestricted same-user shell access can spoof naive approval files; OS-enforced trusted user-presence isolation must be designed before real process controls are enabled.

## ADR-006 — Separate external DebugMCP integration
- **Status:** User-directed.
- **Decision:** Never fork/copy/vend Microsoft DebugMCP implementation. Treat separately approved extension as an external tool that AutoDebug consumes through permitted interfaces.
- **Reason:** Originality, maintainability and controlled licensing/distribution.

## ADR-007 — Functional bugs before performance profiling
- **Status:** User-directed.
- **Decision:** Foundation workflow, evidence and adapters focus on reproducible functional bugs. Profiling is a separate later specification.
- **Reason:** Different measurement tools, timing effects, overhead and evidence requirements.

## ADR-008 — Local JSONL + Markdown investigation records
- **Status:** User-directed.
- **Decision:** Case records and root-cause report kept locally, redacted, append-only event IDs, private, ignored by Git.
- **Reason:** Auditable debugging with small evidence extracts; no need for database/server in v1.

## ADR-009 — Script execution is developer-attested, not AutoDebug-verified, absent instrumentation
- **Status:** User-directed — added in G00 revision 2.
- **Decision:** AutoDebug distinguishes script generated / approved / execution requested / developer-reported / independently verified / bug reproduced as separate states (`RP-08`). Without additional instrumentation, it never asserts an approved script ran unchanged merely because the developer says so.
- **Reason:** AutoDebug has no execution hook inside Fusion (no new helper allowed, ADR-004); overclaiming verified execution would misrepresent evidence confidence.
- **Tradeoff:** Reports must carry explicit `execution_confidence` labeling for API-script cases without instrumentation; a future change could add an optional Fusion-side confirmation signal.

## References — verify versions before integration

External sources cited by the decisions above. Record exact versions and integration results in `docs/test-plan.md` as they're confirmed; these links are starting points, not proof that a capability works on every release, OS or enterprise configuration.

**Claude / SDD**
- [Claude Desktop Code tab quickstart (official)](https://code.claude.com/docs/en/desktop-quickstart)
- [Claude project instructions via CLAUDE.md (official)](https://code.claude.com/docs/en/memory)
- Autodesk internal product-data spec-driven-development guidance (historical reference; internal locator omitted, access and reuse require approval)
- [OpenSpec](https://openspec.dev/) — optional tooling; do not assume installed

**MCP and IDE sources** (ADR-001, ADR-002, ADR-006)
- [Model Context Protocol — official](https://modelcontextprotocol.io/)
- [Official Python SDK for MCP](https://github.com/modelcontextprotocol/python-sdk) — prospective gateway library, pinned only at T07
- [Microsoft DebugMCP](https://github.com/microsoft/DebugMCP) — external VS Code extension; **do not copy** source into AutoDebug
- [VS Code Extension API](https://code.visualstudio.com/api/references/vscode-api)
- [Cursor API/extension documentation](https://docs.cursor.com/) — verify against the current Cursor version
- [JetBrains MCP server documentation](https://www.jetbrains.com/help/ai-assistant/mcp-server.html)
- [Apple Xcode external-agent access](https://developer.apple.com/documentation/xcode/giving-external-agents-access-to-xcode) — `xcrun mcpbridge`
- [Visual Studio SDK docs](https://learn.microsoft.com/en-us/visualstudio/extensibility/visual-studio-sdk)
- Any internal Autodesk Visual Studio bridge — internal approval required; never publish without authorization

**Autodesk Fusion / safety context** (ADR-004, ADR-007)
- [Autodesk Fusion API help](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-7A9E86CB-3F8A-44DC-86A2-B8C44B340F99) — verify actual API methods before generating scripts
- Internal Fusion build / IDE setup guidance (historical reference; internal locator omitted)
- Internal Fusion SDD guidance (historical reference; internal locator omitted)

These historical references preserve project provenance, not permission to disclose
their contents. Autodesk ownership/copyright and OSSA/Legal review remain required
before publication; no legal approval or personal ownership is asserted.
