# ADR-0018 — Adaptive Engineering Execution

**Status:** Accepted

## Context

Anvil 2.9 delivered reliable long-horizon requirements, architecture, verification and resume state. Its deterministic scope assessment still treated repository/request counts and request length as automatic activation signals, and engineering guidance could keep a session in structured mode after the architectural question had been resolved. The engine also invalidated every architecture invariant after any named file changed, even when the invariant's declared evidence scope was untouched. Removing long-horizon capability or its recovery guarantees would trade away the quality Anvil was meant to protect.

## Decision

Keep one model-neutral agent and the existing direct inner loop. Use task-local activation: evaluate the requested task, not project complexity; use explicit risk signals and model judgment to expand only the evidence branch that affects the next safe decision. Allow local depth to rise/fall within a task, keep Requirements/Architecture/Work available but dormant when irrelevant, and use domain skills only when domain evidence changes the outcome. Do not add a scoring engine, required user modes, agents, model routing or workflow framework.

Keep schema-1 atomic state, stale detection, resume, and completion gates unchanged. Invalidate mechanical architecture evidence only when a changed path intersects the evidence scope or a declared file pattern's match set changes. Add milestone-scoped checkpointing that evaluates missing/invalid declared invariants and reuses valid PASS evidence; an unscoped explicit checkpoint remains a full audit. Persisted mutations remain atomic.

The offline eval compares prior deterministic route thresholds against 18 paired task rubrics and replays the same long-horizon ingestion/scheduler protocols. Its results distinguish helper routing and protocol measurements from unmeasured live-model behavior. Semantic model choices, real tool count, context/tokens and user latency require a live OpenCode evaluation.

## Consequences

Small local tasks in complex repositories no longer become long-horizon merely from file, requirement, milestone or request-size signals. Architecture check work falls when evidence scopes are unaffected, while changed boundaries still invalidate and recheck the right invariants. Requirements completeness, user-authorized scope reduction, crash safety, stale-state review, explicit recovery, runtime independence, OpenCode 1/2 support and one-agent operation remain in force.

The helper's assessment recommendation changes from `LONG_HORIZON` to `EXPAND`, meaning selective reasoning and not automatic state creation. The task-state schema does not change. Live-model performance claims remain unavailable until the optional paired evaluation is run with comparable model/runtime budgets.
