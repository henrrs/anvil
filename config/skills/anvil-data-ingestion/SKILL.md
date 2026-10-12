---
name: anvil-data-ingestion
description: Design or debug ingestion from JDBC/ODBC and other source systems, including partitioning, source pressure, retries, idempotency, bulk reads, Arrow paths, distributed ingestion, and checkpoint recovery.
---

# Ingestion reasoning

Treat source pressure as an explicit capacity constraint: identify query cost, concurrent sessions, rate limits, locking, and maintenance windows through owner input or measured telemetry. Bound parallelism and retry bursts; a retry storm can turn a recoverable outage into source saturation. For incremental loads, define watermark ordering and late-arrival behavior, and checkpoint only after the destination commit is durable. For bulk ingestion, test representative nulls, decimals, timestamps, large values, and schema drift through the actual driver and Arrow path. Compare committed rows and recovery behavior, not only the fastest extraction stage.

Clarify correctness and service constraints first: source technology/version, query or extraction boundary, data volume and change rate, consistency requirements, acceptable source load, latency target, and recovery point. Trace the full path from source through driver/connector, partitions, workers, serialization, storage, and checkpoint.

Choose partitioning from source capabilities and measured query behavior. Check bounds, partition-column distribution, connection limits, transaction/snapshot semantics, and whether parallel reads overload the source. More partitions or executors can increase contention without increasing useful throughput. For bulk and Arrow paths, verify type coverage, batch sizing, memory pressure, and fallback behavior in the deployed versions.

Design retries around duplicate delivery and partial completion. Define stable keys, idempotent writes, commit/checkpoint order, and recovery after a worker or source failure. Distinguish at-least-once from exactly-once guarantees across the actual connector and destination; do not claim exactly-once from a checkpoint alone.

Measure source query time, rows/bytes per partition, connection count, transfer rate, serialization, task skew, retries, and destination commit time. Optimize the observed bottleneck while protecting the source system. Verify connector and runtime-specific behavior in current official documentation and report correctness trade-offs separately from throughput gains.
