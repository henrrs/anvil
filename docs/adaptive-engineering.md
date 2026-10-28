# Adaptive engineering depth

Anvil 2.10 keeps Long-Horizon Engineering as its continuity and quality capability. Adaptive Engineering Execution governs when to activate each part. It replaces structured engineering by default with a task-local loop:

```text
Understand enough → locate relevant evidence → act when the next safe step is clear
                 → verify proportionally → stop
```

## Assess the requested change

Repository size, project age, number of existing requirements, and an active Work Model do not classify the current task. A focused bug fix inside an ingestion engine, a public contract change in a small utility, and a request to resume a multi-milestone project need different evidence even if they occur in the same checkout.

Keep the next safe action direct when the change is local, reversible, understood, and bounded. Read only the relevant implementation, caller, and focused test. A focused action can involve a few files without requiring persistent state or architecture review. Do not create a large plan, load requirements, resume project state, or run broad verification just because those facilities exist.

Expand only the branch that materially changes the next safe decision:

| Evidence in this task | Expand into |
| --- | --- |
| Acceptance or required scope is changing/unclear | Relevant Requirements slice |
| Responsibility, public contract, dependency direction, state/runtime ownership, or failure semantics change | Relevant Architecture boundary and, when useful, System Design guidance |
| Several dependent milestones, migration ordering, interruption, or explicit project continuation | Relevant Work state and resume evidence |
| Domain mechanism is unclear or performance diagnosis needs evidence | Only the relevant Spark, Delta, Databricks, or ingestion references |
| Shared contract or meaningful blast radius | Focused regressions first, then broader verification if evidence warrants it |

Depth can change within one task. Preserve useful evidence when escalating. After resolving a boundary or migration decision, narrow the active context to implementation details and focused checks. If inspection shows the apparent complexity was not real, de-escalate without keeping a plan or state workflow alive by inertia. A user request for deep review is honored; a request for a focused fix and relevant test keeps the path shallow when safe.

## Risk signals, not a score

Anvil uses model judgment with a small set of observable task signals: uncertainty about the next safe action, public/component boundary changes, dependency or ownership movement, durable state/schema/migration, runtime/provider seams, distributed/failure/retry behavior, and explicit long-horizon continuation. There is no numeric risk score, repository-size threshold, mandatory user mode, second agent, or model router.

The optional `engineering.py assess` helper accepts supplied signals without scanning the repository or creating state. It returns `DIRECT` or `EXPAND`; the latter means choose a relevant evidence branch. It does not itself create a plan, load every model, or initialize task state. Project-size counts and request length appear only as context hints.

## Long-horizon guarantees remain

For work that truly spans dependent milestones or needs safe interruption recovery, Requirements still measure completeness; Architecture still constrains design; Work still records progress. Resume remains read-only, stale evidence still blocks unverified completion, uncertain external effects are inspected before reconciliation, and the same completion gates remain strict. Task state remains atomic, checksummed and separate from memory. Existing OpenCode 1/2 profiles and lifecycle semantics do not change.

Architecture evidence is tied to its declared files and patterns. An unrelated local file edit does not erase valid invariant evidence. A milestone-scoped checkpoint evaluates only that milestone's missing or invalid mechanical invariants and reuses still-valid PASS results. `checkpoint` without a milestone remains an explicit full audit. Semantic responsibility/retry judgments remain UNKNOWN until a person/model attributes an evidence-based review.

Each explicit helper mutation writes an atomic generation because it is a recovery boundary. This release keeps those durability semantics. Avoid invoking the helper for direct/local work and avoid extra state transitions for investigation notes, intermediate edits, or local work that does not affect the tracked project. Replay state-write counts describe the deterministic harness protocol; they are not a count of writes made by a live model using the CLI.

## Evaluation limits

Offline paired cases cover ingestion-engine and unrelated utility tasks, direct/focused fixes, contracts, persistence, architecture changes, resume, Spark diagnosis, and negative capability. Deterministic protocol replay measures actual state writes, architecture checks, verification commands, completion, and invariant outcomes. It does not simulate an LLM's semantic choices. Tool calls, source files read, model tests, model latency, and tokens require live OpenCode runs and are **NOT MEASURED** without a runtime/provider. See [evaluation evidence](engineering-evaluation.md).
