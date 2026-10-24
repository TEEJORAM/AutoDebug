# How the AutoDebug specs are organized

This folder uses a plain-Markdown OpenSpec-style structure that works without installing OpenSpec. The `/opsx:*` commands work only if the OpenSpec CLI is installed separately.

- `changes/autodebug-foundation/proposal.md` — why this product exists and initial scope.
- `changes/autodebug-foundation/specs/*/spec.md` — testable requirements for this proposed change, using Given/When/Then.
- `changes/autodebug-foundation/design.md` — implementation choices, interfaces, alternatives and constraints.
- `changes/autodebug-foundation/tasks.md` — implementation sequence and approval gates.
- `specs/` (not created yet) — canonical capability specs once the change is closed.

The foundation change was approved (G00, 2026-10-22) and implemented through T14; T15 awaits independent sign-off. Later changes live alongside it: `publication-hardening/` and `technical-closure/`.

For future changes, create a new `changes/<feature>/` directory rather than continuously extending the giant foundation proposal. Where requirements change, update the relevant capability spec and reference a new design decision record.

## The four documents, and the question each answers

| Document | Question answered | Example |
|---|---|---|
| `proposal.md` | **Why** is this needed? What is included/excluded? | "One native debugger interface; five IDE families." |
| `specs/<capability>/spec.md` | **What must users observe?** | "If a breakpoint doesn't bind, don't say ready." |
| `design.md` | **How** will it be implemented? | "Session registry + adapter router + approval broker." |
| `tasks.md` | **Which small, testable piece comes next?** | "T03: stale PID/session tests and router." |

## Workflow for a Claude session

1. **Explore (read-only):** open `CLAUDE.md`, `proposal.md`, the four capability specs, `design.md` and `docs/security.md`; list ambiguity and likely blockers.
2. **Edit spec:** modify only Markdown where needed; review the diff.
3. **Human approve:** record reviewer/date/commit SHA under `proposal.md` and `design.md`; check **G00** in `tasks.md`.
4. **Implement one task only:** exactly the acceptance criteria in that task's `tasks.md` entry, nothing more.
5. **Test and review:** show actual test output; commit only after human review.
6. **Repeat:** one bounded task per session/PR. If a requirement changes, open a new change proposal first rather than editing behavior silently.
7. **Close the change:** once implementation and tests are complete, promote the reviewed specs to canonical `openspec/specs/` and archive the foundation change.

## Avoid these mistakes

- Don't paste every spec into every Claude message — point Claude at the repository and ask it to read the relevant files.
- Don't ask for "the entire AutoDebug project" in one prompt; one task at a time.
- Don't start a source-code task while `G00` is unapproved.
- Don't believe "I tested this" unless execution output/test results exist.
- Don't treat a backend's advertised tool names as current truth; capability discovery must verify them at runtime.
- Don't let generated code silently change the specifications — a behavior change needs a spec change first.
