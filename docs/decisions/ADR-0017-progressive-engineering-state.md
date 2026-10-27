# ADR-0017 — Progressive engineering continuity

**Status:** Accepted

## Context

Anvil's direct loop is effective for small edits, but long specifications lose requirements, architectural decisions and operational progress across many work units or context compaction. Existing local stdlib cores, lazy native skills and separate memory/lifecycle stores provide extension points. Adding agents, a workflow framework or a large permanent prompt would add cost without addressing state ownership.

## Decision

Keep one model-neutral Anvil agent and both runtime adapters. Add an explicitly activated engineering package with three separate models in one atomic, checksummed task envelope under XDG_STATE_HOME/anvil/engineering. Requirements measure coverage, architecture constrains implementation, and work tracks progress. The core owns mechanical transitions, dependency checks, evidence, drift, resume and completion. Semantic extraction/design/review remain agent judgments and are labeled as such.

The permanent kernel adds one routing instruction; engineering/system-design entrypoints and deep Spark references load progressively. Direct tasks create no models/store. Resume executes nothing and uncertain partial effects require inspection. The task lock spans registered checks, revisions reject stale updates, and explicit recovery invalidates prior verification. Replanning preserves unaffected work and records changed scope/decisions rather than silently reinterpreting completion.

Anvil 2.9 retains the previously supported 2.6 source line by extending the lifecycle migration window from two to three prior minors. Legacy source auditing and introduction-version ownership remain unchanged; new skills/scripts cannot make a supported older source appear corrupted. No runtime migration or existing memory migration accompanies this release.

## Consequences

The release adds no third-party package, MCP, agent, runtime hook, vector store or automatic model call. Task state remains outside config/runtime snapshots and durable memory. Private JSON is inspectable but not an interchange format for blindly importing verification. A 24 KiB continuation budget requires concise models and work units. Mechanical PASS does not prove semantic truth, external idempotency or LLM task success. Deterministic ingestion and unrelated scheduler replays, fault injection, native runtime checks and optional model profiles keep those assurance boundaries explicit.
