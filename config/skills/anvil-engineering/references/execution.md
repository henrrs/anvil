# Execute, verify, replan

Use the state helper only after the current task warrants long-horizon continuity. A local task in a repository with existing engineering state does not need `resume`, `start`, a Work Model update or architecture checks unless its evidence reaches that boundary. Explicitly continuing an interrupted long task does require `resume`; it executes nothing.

For structured work, select one coherent ready unit. Load its relevant requirements, decisions and named files; stop searching once the next safe action is clear. `start --id TASK --revision N --task T1` records interruption-sensitive work before its effects. Implement the unit, then `implement --task T1 --files src/file.py ...` records its actual paths. Do not turn exploration, every edit or every tool call into a persistent progress event.

`check --task T1 --check C1` runs only the registered argv array with bounded time/output and no shell interpolation. Choose the smallest checks that could falsify the implementation hypothesis. It records command-definition hash, relevant file hashes, result, output digest and timing, not raw output. Inspect failures and revise evidence or hypothesis before retrying. A pass supports only that check's scope. `review` records an explicit semantic judgment; it cannot impersonate a test. Missing evidence is UNKNOWN.

Architecture is a guardrail, not per-edit supervision. Run `checkpoint` when a public/component boundary, dependency direction, state/runtime ownership, persistence or failure/retry decision changes; after a risky stateful action; or to close a milestone whose declared gates require it. Do not checkpoint private helpers, local conditionals, fixtures, formatting or other changes inside an established boundary. Deterministic invariants remain scoped to their declared files; semantic ownership/retry judgments need explicit review.

Requirements reconciliation is for changed scope, acceptance or interpretation, not every implementation edit. Update the Work Model when the tracked unit's meaningful status, dependency, blocker or milestone changes. Replan when evidence changes feasibility, required scope, ordering, architecture or requirement meaning; one transient test failure is not a reason to rebuild the plan. Reducing required scope requires the user's actual authorization reference.

Use focused tests first. Broaden verification for shared contracts, significant dependency radius, failed assumptions, architecture/state/migration semantics, milestone completion or a release gate. Never run the broadest suite merely because it exists. If a cheap check fails, inspect its result before expanding.

`complete` still enforces required coverage, task/milestone/project gates, valid architecture evidence, blocking unknowns and recovery status. Do not weaken these gates to reduce overhead. If new evidence shows the work is local after all, de-escalate, preserve the applicable safety check, and archive unnecessary state only when appropriate.

Expose concise progress only for meaningful decisions, blockers, unexpected scope and verification. Report evidence and uncertainty, not private reasoning. Stop when the requested outcome and its risk-proportionate checks are complete.
