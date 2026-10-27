# Shuffle and fetch cost

An exchange redistributes data; inspect why it is necessary before changing its partition count. Compare shuffle read/write bytes and records, local/remote fetch, fetch wait, task duration, disk spill and network/storage saturation. Large transferred volume, many tiny blocks, straggling upstream tasks and remote fetch stalls need different interventions.

Candidate changes include reducing data before exchange, removing repeated shuffles, correcting join/aggregation strategy or matching distribution to the operation. Validate semantics: filtering earlier or pre-aggregating is safe only if it preserves the requested result. Do not infer network saturation from shuffle bytes alone; correlate time and host/provider telemetry.

Benchmark the same plan/input shape and inspect downstream effects, including output size and executor memory. Raising parallelism can reduce per-task size while increasing scheduling/block overhead and source pressure.

Sources: [Spark monitoring](https://spark.apache.org/docs/latest/monitoring.html), [SQL tuning](https://spark.apache.org/docs/latest/sql-performance-tuning.html).
