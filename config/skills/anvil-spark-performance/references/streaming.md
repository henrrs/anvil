# Stateful execution and recovery

Locate time in trigger scheduling, source/offset discovery, processing, state-store operations, sink effect and checkpoint commit. Inspect input/processed rate, batch/trigger duration, lag, state size, watermark and commit evidence. Increasing throughput without preserving recovery semantics is not an optimization.

Define late-data policy, state retention, output mode, checkpoint ownership and sink idempotency. A checkpoint records progress, not arbitrary planner policy. Replay/backfill can interact with live traffic and duplicate effects. Exactly-once claims depend on source replay and sink commit/deduplication at a stated boundary; test interruption before and after the durable effect.

Compare steady-state runs under equivalent input rate and state size. An ever-growing state or sink bottleneck can be hidden by short benchmarks. Do not alter checkpoint contents or start/reconfigure running resources without authorization.

Source: [Spark Structured Streaming guide](https://spark.apache.org/docs/latest/streaming/apis-on-dataframes-and-datasets.html).
