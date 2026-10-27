# Local job scheduler

## Public intent

Build a small local scheduler with immutable job identity/payload and positive retry
budget. Public contracts must not depend on queue policy, handlers or progress storage.
Reject malformed identities and budgets. Keep this service local; no leader election,
distributed lease, plugin framework or cloud dependency is required.

## Queue policy

Select ready, unfinished jobs deterministically with bounded batch size. The policy
does not execute handlers or mutate progress. Completed jobs are excluded. Preserve
input order for equal readiness. Validate the admission bound.

## Execution and recovery

Two real injected handlers justify a minimal callable boundary. Do not build a speculative
Factory/Registry framework. One executor owns retry accounting; handlers do not retry.
Successful jobs are acknowledged only after their effect returns. Failure increments
attempt count, retains pending work below the budget, and blocks exhausted jobs.
Resume never reexecutes acknowledged jobs. Handler effects must be idempotent for an
ambiguous crash window; the fixture does not promise generic exactly-once effects.

## Acceptance

Test job validation, deterministic capacity, policy/execution separation, distinct
handlers, success, bounded failures and replay of acknowledged jobs. Preserve ownership
under interruption and external source edits. Report requirements and architecture
conformance separately. No network, daemon, timer or real production action is needed.
