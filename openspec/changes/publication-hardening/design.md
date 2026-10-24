# Bounded repair design

Keep the facade and adapter contracts, error-code set and fake-only broker gate.
Use the stored arm approval for inspection, but verify its distinct operation
scope each time. Lease the whole synchronous check/call/output boundary.
Revalidate on every wait poll. A monotonic deadline limits new operations and
rejects late responses; synchronous backend calls cannot be forcibly interrupted
and that remains a blocker, not a fabricated cancellation guarantee.

Reserve evidence storage before any debugger call. Existing descriptor-relative
no-follow persistence and exclusive creation are retained; Windows persistence
remains unavailable until an independently reviewed implementation exists.
Session operation locks survive unregister/re-register so an old lease cannot
be replaced while it is active. Registry lifetime lock retention is deliberate.

No new dependencies, transport, debugger integration, license or ownership claim.

## Strict-review repair design - 2026-10-24

Use registry arming locks per host/IDE to serialize resolution/launch, and retain
the existing session lease across binding. Within a facade, cases own their
session until finalized or a recovery terminal state; a busy/shared session is
refused before binding. Preserve sessions that predate an arm request on rollback.
Track confirmed stops and arming start separately from the inspection deadline.
Recheck authorization after every synchronous call; this rejects late results
but cannot interrupt a blocked call.

Serialize completion against session operations. Write the report and metadata
before committing FINALIZED in memory; use atomic artifact replacements so a
failed write does not truncate the previous snapshot. Cancellation still signals
its event and revokes immediately; terminal transitions are checked again at the
output boundary. Whole-tree sanitizer budgets bound total UTF-8 bytes and visited
nodes, not only each leaf. Reject case IDs changed by sanitization at intake.
