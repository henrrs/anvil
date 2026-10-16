---
name: anvil-spark-performance
description: Use when a Spark workload is slow, unstable, resource-heavy, or needs performance review using plans, stages, task distributions, shuffle, skew, spill, AQE, and executor/runtime evidence. Do not use for Delta transaction correctness or source-ingestion design unless Spark execution performance is the question.
---

# Spark performance diagnosis

Keep diagnosis scoped to the slow query and the stages that dominate wall time. Compare task quantiles and counts, not only averages: a few outliers can dominate completion. Check whether input is cached, repeated, or spilling before attributing cost to the source. For joins, confirm actual cardinality, build-side size, and whether a broadcast decision is safe for executor memory. For partition changes, estimate bytes per task and downstream file counts. Record runtime, data scale, and repeat conditions so a benchmark remains interpretable.

Start from the workload and evidence: query or code, input size and shape, runtime/version, cluster or executor layout, and observed latency or resource symptoms. Avoid recommending settings before identifying where time and data move.

Use a focused sequence:

1. Read the physical and, when useful, logical execution plan. Identify scans, joins, exchanges, sorts, and repeated work.
2. Compare stage durations and task distributions. Look for long tails, uneven input/output, retries, GC, executor loss, and oversized or tiny tasks.
3. Inspect shuffle read/write, fetch wait, spill, partition counts, and skew. Distinguish a true data-skew problem from slow I/O or insufficient parallelism.
4. Check Adaptive Query Execution (AQE): whether it is active, which decisions were made, and whether post-shuffle partitions or skew handling match the evidence.
5. Relate findings to executor/runtime behavior and workload size. Change one relevant factor at a time and compare repeatable measurements.

Prefer a query, join, partition, or data-layout correction when the plan supports it. Treat configuration knobs as hypotheses, not defaults to apply blindly. Verify version-sensitive behavior against the deployed Spark/Databricks runtime documentation. Report the measured bottleneck, evidence, change, and before/after result; label anything not measured as a hypothesis.
