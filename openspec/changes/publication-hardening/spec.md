# Requirements clarification / delta

- RP-04/05: case, plan, approval and routed target must agree before arming.
  Stored approval must be verified on every wait/stack/variable request, using
  `op:wait_for_stop`, `op:get_stack`, `op:get_variables` respectively. Arm
  permission alone does not grant inspection.
- DE-01, GW-05: inspect and mutate only under the session lease, revalidating
  identity, authorization, cancellation, budget and live pause inside it.
  Continue invalidates the case's cached pause until a new wait confirms a stop.
- DE-03: the monotonic inspection deadline begins at successful arming,
  includes waiting and is never reset by another stop. Positive finite wait
  limits and positive integer plan budgets are required.
- DE-02/07: bound frame/name selection and sanitize stack metadata and variable
  names as well as values before any response or persistence.
- DE-05/06: exclusive case-directory creation rejects previous investigations;
  no symlink/hardlink artifact traversal; concurrent appends cannot share IDs.
  Unsupported secure file APIs must fail explicitly, never use weaker opens.
- DE-08/09: persistence initialization fails before arming; later arming failure
  revokes approval and disconnects without terminating the application.

## Strict final review delta - approved 2026-10-24

- Arming is serialized by host/IDE and by existing session. An active case owns
  its session exclusively; another case cannot replace its breakpoints.
  Rollback disconnects only a session newly created by that arm request.
- Validate the adapter-returned host, IDE, PID and specified session/instance
  before setting breakpoints. Recheck expiry/revocation, cancellation and the
  arming deadline after launch and before each subsequent backend action.
- Stack sanitization applies sensitive-name rules recursively. Total output
  is limited to 64 KiB UTF-8 and 4,096 visited nodes, with explicit truncation.
  The final authorization/deadline check follows pause verification and output
  preparation, not before them.
- A backend disconnect marks an active investigation INCOMPLETE. Cancellation
  and completion cannot admit more operations after terminal status.
- Completion requires a confirmed pause before `reproduced=True`. Only mark
  FINALIZED after successful artifact persistence; failed completion can retry.
  An empty event log is created for zero-observation finalization.
- Case IDs must survive sanitization unchanged; reject incompatible IDs before
  creating case state or storage. Never redact an identity and then use the
  altered value for isolation/citation validation.

The developer explicitly approved these decisions. This is not native-debugger,
publication, ownership, license, data-policy or independent-human clearance.
