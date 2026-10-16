---
name: anvil-delta-lake
description: Use when Delta Lake table semantics affect correctness or performance, including MERGE, transactions, concurrency, schema evolution, CDF, layout, clustering, file operations, or retention. Do not use for generic Spark tuning or source-ingestion design unless Delta behavior is part of the issue.
---

# Delta Lake workflow

When changing retention, establish the oldest supported reader and recovery window first; cleanup can remove files needed by time travel or a lagging CDF consumer. For concurrent writes, collect operation history and conflict details, then identify overlapping predicates and files instead of adding blind retries. Check whether a schema change is backward-compatible with downstream readers. Use a representative test or safe clone when semantics can affect production rows, then compare table history and row-level outcomes.

First identify the table, engine, deployed runtime and Delta version, table features, write pattern, and required correctness guarantees. Read the actual schema, properties, history, and relevant code or plans where access permits. Do not infer current behavior from an old memory entry.

For `MERGE`, establish source uniqueness and matching semantics, target scope, null handling, update/insert rules, and retry behavior. Check transaction isolation, concurrent writers, conflict handling, and idempotency before changing write logic. Treat schema evolution and column mapping as explicit compatibility decisions.

For change data feed (CDF), verify enablement, starting/ending versions, retention, delete/update representation, and consumer checkpoint semantics. For layout work, inspect file counts and sizes, partition keys, clustering or Z-order support, pruning, and actual scan/shuffle evidence. For optimize, vacuum, and retention operations, establish the safety window and downstream reader needs before acting.

Delta feature support and syntax vary by engine and runtime. Verify version-sensitive claims in official documentation for the deployed runtime before recommending or executing changes. Separate transactional correctness from throughput, preserve recovery paths, and state which behavior was observed versus assumed.
