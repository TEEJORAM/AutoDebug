# Publication, license and release approvals

**Status: BLOCKED.** AutoDebug is an Autodesk-related fake-only foundation.
Publishing, transferring or licensing it needs the four decisions below, made
by authorized owners outside this repository. Passing tests and clean
documentation do not grant any of them. No `LICENSE` is assigned.

The GitHub repository `TEEJORAM/AutoDebug` is **public**. It was created on
2026-10-24 from the current tree only; the original private Git history was not
pushed. Whether it may stay public is the owner's decision under item 1.

## The four required decisions

- [ ] **Permission to publish or transfer** this Autodesk-developed source and
  documentation to the named audience. Implementation approval is not transfer
  permission.
- [ ] **Copyright, license and notices.** Determine Autodesk and other rights in
  original and AI-assisted work, then authorize a specific license. MIT and
  Apache-2.0 are options, not assignments.
- [ ] **Exact artifact, destination and history.** Approve the release tree and
  its digest, the GitHub account, repository name, visibility and owner, and
  how history is treated. The original private history contains internal
  locators, workstation paths and employee metadata and must not be published.
- [ ] **Personal accounts and equipment.** Explicitly permit or deny development
  on personal devices or GitHub accounts, and any personal AI-service use.
  Silence is not permission.

Record each decision outside the repository: signer role, date, reference in
the approved private system, approved digest, destination, license, history
treatment, conditions and any expiry. Do not copy private ticket URLs or
employee identities into the repository.

## Publishing after approval

1. Apply only the authorized license and notices; freeze the exact release tree.
2. Exclude credentials, evidence, logs, generated archives and private files.
3. Follow the approved history treatment (for example a clean snapshot export).
4. Publish to the approved destination, run CI there and record the results.

## Dependencies and external integrations

| Item | Role | Review needed |
|---|---|---|
| Python standard library | Runtime and tests; `dependencies = []` | Python's own terms for the exact distribution |
| `build_backend.py` (original) | Stdlib-only PEP 517 wheel/sdist builder | Ownership and notices of the built archive |
| MCP SDK / IDE client libraries | Not used; stdio binding is original | Pin and review before adding any |
| Microsoft DebugMCP | External extension, consumed only after approval | Never copy its source |
| Cursor, JetBrains/CLion, Apple/Xcode tooling | Unverified native backends | Terms and enterprise policy before use |
| Visual Studio bridge / SDK | Internal bridge or new public-SDK adapter | Maintainer and Autodesk authorization |

No copied DebugMCP or internal bridge code was identified; this is an
observation, not a legal warranty.

## Independent sign-off still outstanding (T15)

T15 stays unchecked until an independent human reviewer decides:

1. Whether the `GW-05`/`DE-08`/`DE-06` fixes and their tests are correctly scoped.
2. The case-data retention policy (see [security](security.md#case-data-policy)).
3. Whether `.github/workflows/tests.yml` becomes a required check after a real run.
4. Whether T15 can be checked in `tasks.md`.

The file-by-file content classification used for the publication review is in
[publication-content-audit.md](publication-content-audit.md).
