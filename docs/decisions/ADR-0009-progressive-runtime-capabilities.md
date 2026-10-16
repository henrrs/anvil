# ADR 0009: Use capability-gated runtime enhancements

- **Status:** Accepted
- **Date:** 2026-10-16

## Context

OpenCode runtime generations expose different config schemas and native features. Requiring every optional V2 feature would reintroduce the runtime lock-in removed by ADR 0008. Forking Anvil's commands and memory implementations would also create avoidable drift.

## Decision

Keep common Anvil behavior runtime-independent and ask the central runtime adapter for native capabilities. OpenCode 2 uses its local memory-search plugin, Knowledge Reference, ordered permission schema, bounded tool output and structured stats. OpenCode 1 uses its native singular config and stats text output, the shared Python lexical memory helper, and direct file reads for named knowledge documents.

Feature gaps are visible in `make capabilities` and `make doctor`. `make stats` uses native output when available and reports unavailable values without inference. An unavailable native feature does not disable `/remember`, `/recall`, `/distill`, file memory, source registry, or source freshness checks.

## Consequences

The V2 plugin remains narrowly scoped and optional. Markdown stays the portable memory source of truth. Runtime support requires maintaining two config templates and testing each profile, but avoids duplicating Anvil's user-facing workflows or requiring a model/provider choice.
