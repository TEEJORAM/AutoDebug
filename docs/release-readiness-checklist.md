# AutoDebug — T15 release readiness checklist

This maps T15's acceptance requirement ("independent reviewer signs off; no unsupported native IDE functionality described as implemented; approved case data handling") to tests, documentation, evidence, and remaining limitations. This is an AI-assisted self-review, including a separate security-review agent pass; **neither is independent human reviewer sign-off**.

## Publication preparation — 2026-10-24: pending authorization

**Publication is blocked.** Preparation of public-facing files is authorized;
publication, distribution, license assignment, and Git-history rewriting are not.
There is no assigned `LICENSE`. Historical technical assessments below do not
provide legal, ownership, security-policy, or publication clearance.

### Frozen fake-only publication: four external decisions

- [ ] Permission to publish or transfer this Autodesk-developed repository.
- [ ] Approved copyright, license and required notices.
- [ ] Approved exact public artifact/digest, GitHub destination and history
  treatment; do not push existing private history or checkpoint refs by default.
- [ ] Explicit permission for development on personal accounts/equipment;
  personal AI-service upload also needs explicit permission.

These are the finalization pass's remaining external publication decisions.
See the [approval request](ossa-legal-approval-request.md) and
[publication steps](installation.md#publication-after-permission).
Historical T15 records below are preserved, not silently signed off.
Native-debugger authorization, secure Windows evidence and unexecuted target
environments remain disclosed restrictions/limitations, not additional feature
work required to describe this release honestly as a fake-only foundation.

The provenance is Autodesk-related; do not infer personal ownership or a legal
verdict from synthetic fixtures or independently written adapter interfaces.
See [license and dependency review](license-and-dependency-review.md). No final
publication assessment is made by this preparation.

Current assessment: **BLOCKED**. The
[publication assessment](publication-readiness-assessment.md) and
[content classifications](publication-content-audit.md) supersede historical
technical conclusions below. The developer subsequently authorized comprehensive
implementation, including MCP stdio, script integrity, stop identity, bounded
operations and offline packaging. See the [complete requirement matrix and
closure report](technical-closure-report.md), [current exact results](status.md)
and [concrete approval request](ossa-legal-approval-request.md).
The earlier 425-test/39-file snapshot was superseded and removed in the
2026-10-24 cleanup (Git history (commit `435df13`, the initial import)). Real native capability, external approvals and
unexecuted target environments remain explicitly unverified.

## Items requiring independent reviewer sign-off

1. Whether the `GW-05`/`DE-08`/`DE-06` fixes and their regression tests are accepted as correctly scoped (not over- or under-reaching).
2. The three open case-data-handling policy decisions in `docs/security.md`'s "T15 case-data handling review" section.
3. Whether `.github/workflows/tests.yml` should be enabled as a required check once it has run successfully on a real PR.
4. Whether `T15`'s checkbox in `tasks.md` can be checked — per this task's own explicit instruction, it is being **left unchecked** pending this independent sign-off, regardless of the technical state above.
