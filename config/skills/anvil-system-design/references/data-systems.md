# Data-system decisions

Derive batch, micro-batch or streaming from latency, ordering, replay, source capability and operational cost. Distinguish extraction/ingestion, transformation, storage, compute, metadata and progress ownership. Source profiling may supply statistics to planning; it should not silently select the execution runtime. Generic contracts should survive a change in runtime/provider or environment/YAML input adapter.

For incremental data, define stable identity, watermark order, late arrivals, deletes/CDC semantics and schema evolution. State records a durable committed boundary, not an execution plan. Advance it after the destination effect is durable; test a crash on both sides of that boundary. Replay/backfill must state deduplication, affected range, concurrent live traffic, retention and reconciliation. Append-only history, current-state tables and SCD history have different invariants; choose from requested semantics.

Separate metadata/control planes from data movement when the project requires it. Make lineage, contract version, checkpoint compatibility, source pressure and end-to-end validation observable. Credentials remain provider-owned. Distributed execution and columnar conversion can improve a physical path, but must not leak Spark/Databricks concepts into a generic interface merely because the first implementation uses them.

For a slow workload, establish whether time belongs to source/database, driver/serialization, Spark stages, storage/sink or startup. Use the existing Spark, ingestion and Delta skills for the mechanism that the evidence actually implicates. Preserve the system-design ownership decision while testing that mechanism.
