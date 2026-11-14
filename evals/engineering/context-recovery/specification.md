# SE-06 — Recover a checkpointed incremental sync after interruption

Complete the existing local synchronization pipeline. Keep the public `Event`,
`Source.page`, `DurableSink.commit`, `Checkpoint.load/save`, and `run_sync` interfaces.
The source is ordered by monotonically increasing integer sequence. Each event has a
stable unique ID. The checkpoint is the last event whose sink effect is durable.

Commit the sink effect before advancing the checkpoint. A crash after the sink commit
but before the checkpoint write must be safe to resume: replay the event, deduplicate by
its stable ID, and then advance. A failed sink commit must never advance the checkpoint.
Repeated runs must not duplicate output or regress the cursor. Newly appended source
events after an interruption must be picked up. Persist checkpoints atomically and keep
source reading, sink effects, progress and orchestration in their existing modules.
Use only the standard library and do not add a database, service or background worker.

This task has dependent recovery milestones. If the runtime provides Anvil engineering
state, preserve named requirements, architecture decisions and work progress. After an
interruption, inspect current files and state before resuming; do not repeat already
durable effects. Run public tests and add focused failure-before/after-commit tests.
