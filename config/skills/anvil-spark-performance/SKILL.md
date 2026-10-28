---
name: anvil-spark-performance
description: Use when this task diagnoses Spark execution performance from plans, stages, task distributions, shuffle, skew, spill, AQE or runtime evidence. Do not use for simple config/name edits, Delta correctness, or ingestion design unless execution performance is at issue.
---

# Spark performance diagnosis

A config-key rename or local typo stays on the direct engineering path; a Spark repository or dependency alone does not call for deep performance analysis. Load only the references needed by the current evidence, and return to the local loop once the bottleneck decision is made.

Follow symptom → execution evidence → physical mechanism → competing hypotheses → discriminating evidence → intervention → benchmark. A slow job alone does not justify more workers, partitions or caching. Establish code/query, source/input shape, runtime/version, executor layout and repeat conditions. Distinguish measured facts (OBSERVED), corroborated mechanisms (SUPPORTED), hypotheses (INFERRED) and missing evidence (UNKNOWN).

Locate time and bytes through logical plan → Catalyst → physical/adaptive plan → jobs/stages/tasks → JVM/Python/Photon → memory/network/disk → source/storage. Compare task counts and quantiles, not only averages. Confirm cache/warmup/repeated reads and retries before attributing latency. Keep scope on dominant work; architecture ownership remains a system-design decision.

Load only references selected by evidence:

- Jobs/stages, driver/executor/startup or columnar/row boundaries: [execution-model](references/execution-model.md).
- Plans, statistics, joins or adaptive decisions: [catalyst-aqe](references/catalyst-aqe.md).
- Task sizing/source distribution: [partitioning](references/partitioning.md); exchange/fetch costs: [shuffle](references/shuffle.md); long tails: [skew](references/skew.md).
- Memory pressure, GC, spill or serialization: [memory-spill](references/memory-spill.md).
- Python/JVM, Arrow conversion or `mapInArrow`: [arrow](references/arrow.md).
- Database/source bottleneck and read concurrency: [jdbc](references/jdbc.md).
- Connector pushdowns/planning interfaces: [datasource-v2](references/datasource-v2.md).
- Databricks native execution applicability: [photon](references/photon.md).
- Delta reads/writes/files: [delta](references/delta.md); state/checkpoints: [streaming](references/streaming.md).
- Evidence gaps and controlled experiments: [diagnostics](references/diagnostics.md).

For mssql-python plus `mapInArrow`, begin with execution-model, Arrow and JDBC; add memory-spill only if evidence warrants it. Do not load unrelated streaming/Delta guidance. Prefer the query, partition or data-path correction supported by the mechanism. Change one relevant factor, compare equivalent inputs/outputs and repeated measurements, and retain correctness/recovery checks. Verify version-sensitive APIs/settings against the deployed official documentation. Never infer proprietary internals or a measured speedup from a configuration recommendation.
