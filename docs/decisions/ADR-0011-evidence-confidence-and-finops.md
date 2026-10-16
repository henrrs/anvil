# ADR-0011: Keep FinOps recommendations evidence-driven and deterministic

## Status

Accepted for Anvil 2.2.

## Context

Databricks system tables are optional, time-lagged, region-scoped in places, and may not support precise cost attribution for shared resources. A low average utilization metric alone does not establish that production compute is safely oversized.

## Decision

Use version-controlled aggregate SQL recipes selected by workload type and requested time window. Prefer evidence from relevant run metadata, historical compute configuration, node telemetry, warehouse events/query history, and billing/pricing sources. Aggregate and bound results in Databricks. Mark shared all-purpose attribution approximate and Databricks list-cost separately from total cloud cost.

Emit a deterministic 0–100 Evidence Confidence Score from sample size, telemetry coverage, freshness, attribution quality, independent signals, and configuration history, with explicit penalties for missing/weak/conflicting evidence. Call it evidence quality, never success probability. Strong recommendations require low utilization across averages and peaks, sufficient coverage/sample, relevant history, and no pressure signals; weaker evidence becomes a test candidate or no conclusion.

## Consequences

- Anvil can explain which evidence supports a recommendation and where the evidence is incomplete.
- Missing system-table access produces a limitation instead of a fabricated conclusion.
- SQL warehouse findings use warehouse/query/billing metrics and never treat classic node telemetry as warehouse internals.
- Recommendations cannot mutate remote settings; production changes remain subject to direct user approval and controlled validation.
- Deterministic fixtures validate scoring and decision gates without claiming model benchmark gains.
