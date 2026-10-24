# Requirements delta

- GW-01: implement JSON-RPC MCP stdio initialization, tools and typed errors,
  bounded messages, concurrent cancellation and an executable entry point.
  No network listener, self-approval, shell or expression-evaluation tool.
- RP-03/04/05: include full UTF-8 script content and recompute SHA-256 at
  staging/approval. Manual plans cannot carry scripts. Bind all modeled review
  fields, scopes, target and session identity. Reject nonfinite expiry/budgets
  and duplicate approval tokens.
- GW-03/05, DE-01/03/08/09: require explicit process-start and stop snapshots
  where the adapter can supply verified identities; unsupported interfaces fail
  closed. Detect resume/re-stop during inspection, not only a running boolean.
  Bound synchronous facade waits, signal cancellation and quarantine a backend
  that fails its cooperative contract; never let a late result authorize reuse.
- RP-06: bound results must cover the exact requested breakpoint multiset.
- DE-02/05/06/07: recursively sanitize structured variables as well as stacks;
  persist stop/stack evidence with identities, execution confidence and stable
  citations. Complete successful and incomplete reports honestly; never infer
  script execution from script generation or a pause.
- IDE-01..05: a standalone synthetic backend supports isolated end-to-end use.
  Real IDEs remain unapproved, unavailable or uncertified; no invented APIs.
- Publication: record current/history classifications, exact proposed artifact
  and unresolved ownership/OSSA/Legal/data-routing decisions without claiming
  authorization. Preserve legitimate provenance and original private history.
