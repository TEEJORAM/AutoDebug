# IDE debug bridge tasks

Do not start B1 until B0 is signed off. One task per change; each lists the
requirement IDs, tests and the observed test result.

- [ ] B0 — Developer sign-off on proposal decisions 1–3 (T05 gate for
  `vscode-bridge`, own extension, report location).
- [ ] B1 — Plan schema 0.3 and extended digest (BR-03).
- [ ] B2 — Bridge protocol, discovery and Python fake bridge (BR-01, BR-02, BR-11).
- [ ] B3 — `VSCodeBridgeAdapter`: launch, breakpoints, stop, stack, variables,
  step, continue, end (BR-06, BR-07, BR-08).
- [ ] B4 — Bridge-issued approval, allowlist entry, new approval tools
  (BR-04, BR-12 allowlist part).
- [ ] B5 — Build step (BR-05).
- [ ] B6 — Report sections and workspace export (BR-09).
- [ ] B7 — MCP instructions and tool descriptions; `list_variables` (BR-07, BR-10).
- [ ] B8 — Bridge extension and `autodebug bridge install` (BR-01, BR-12).
- [ ] B9 — AutoDebugDemo: plan 0.3; manual run on Windows VS Code; ledger entry
  (BR-11). **Phase 1 done.**
- [ ] B10 — C++ build task and launch configurations; manual run (phase 2).
- [ ] B11 — Docs: README, getting-started, security, status, release notes.
