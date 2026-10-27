# Distributed failure and control

First establish why coordination is required. A single-process atomic file or transaction is preferable when it satisfies the actual boundary. Distributed terminology does not justify a distributed service.

List failure domains and outcomes: before effect, after effect before acknowledgement, partial completion, timeout with unknown outcome, partition and stale owner. Assign retries to one layer with bounds, backoff/jitter, cancellation and source capacity. A timeout is not proof that the effect failed. Define idempotency keys, deduplication scope/retention and reconciliation for ambiguous outcomes. Separate deterministic failure from transient failure and authorization errors.

Specify state authority, consistency required by each operation, transaction boundary and the behavior during loss of availability. Partition keys determine contention, ordering and scale. Replication and eventual consistency need conflict/read-after-write semantics; do not promise a global order from per-partition ordering. Leases/heartbeats need expiry, fencing or equivalent stale-writer protection when ownership can overlap. Leader election alone does not prevent an old leader from writing.

Bound queues and concurrency, define backpressure and admission behavior, and observe lag, saturation, retries, duplicate suppression and recovery time. Recovery should replay only known-safe units. An exactly-once claim must identify source replay semantics, processing boundary, sink commit/deduplication and failure window; otherwise describe the narrower delivery/effect guarantee. Add a representative crash/partition/duplicate test at the actual boundary rather than substituting a successful happy path.
