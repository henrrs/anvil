# Portable ingestion slice

## Intent and contracts

Build an offline representative ingestion slice. Contracts express source/dataset identity,
load intent and correctness invariants. They must not import Spark, Databricks, physical
planning, execution or progress implementations. Reject missing identity and unsupported
load modes. Parse environment input through a separate adapter; future YAML input must
not change the contract. Do not persist credentials or assume Python/Spark concepts in
the public intent merely because this fixture uses Python.

## Source pressure and planning

Source profiling describes available ranges and safe concurrency. It must not select a
runtime or physical strategy. Planning owns that decision using explicit runtime
capabilities and source capacity. A physical plan is immutable execution intent, not a
checkpoint. Reject unusable capabilities. Provide two local source implementations and
preserve a seam for SQL Server, Oracle, MySQL, MongoDB, Kafka, files and APIs. Only fake
SQL Server and file reads are required in this slice; live services are out of scope.

The initial runtime is represented by a Databricks capability label, while a second
local-runtime capability must work through the same planner contract. Neither label
may leak into source selection or the generic contract. Future runtime-specific
execution adapters belong beyond that boundary.

## Execution and progress

Runtime executes a chosen plan through injected source and sink behavior. Progress
stores committed unit identities only. It must contain no planner, runtime or strategy
selection. One execution owner handles retries/replay; sources do not retry independently.
Commit a sink effect before advancing progress. A failed sink commit must not advance it.
An interrupted execution may repeat a unit only through an idempotent sink identity.
Already committed units must not be read or committed again on resume.

## Data behavior and verification

Represent Landing as preserved source rows, Bronze as append-only committed unit history,
and Silver as the latest value by stable key. Replay cannot duplicate Bronze or regress
Silver. Cover success, failure before commit, failure after commit before progress,
and resume. Keep source capacity and runtime decisions observable as explicit plan
fields without placing secrets in evidence. Run local behavior checks and architecture
invariants separately; report required coverage and semantic uncertainty.

## Evolution pressures and deferred scope

Backfills, CDC/delete semantics, schema evolution, source snapshot guarantees, richer
profiling and a YAML adapter are explicit future pressures. They justify preserving
ownership seams, not building all implementations in this benchmark. No live Databricks,
database, broker, compute mutation, cloud identity, package download or network access
is part of acceptance. Do not add a plugin framework or workflow scheduler.
