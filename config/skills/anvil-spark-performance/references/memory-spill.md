# Memory, spill and serialization

Identify where memory lives: JVM execution/storage, Python worker, Arrow/native buffers, driver and container overhead are different budgets. Executor heap metrics alone do not describe Python/native pressure. Correlate peak use, GC pauses, spilled bytes, task size, retries and process/container exits before increasing memory.

Spill can be a valid bounded execution path; establish whether it dominates time. Large joins/sorts, oversized batches and skew can cause different pressure. Cache competes with execution and adds serialization/materialization cost; prove reuse and eviction behavior before introducing it.

For serialization/deserialization, locate CPU and copies across source driver, Python objects, Arrow batches and JVM rows/columns. Changing a serializer for one boundary may not change another. Compare batch/task size and type coverage while keeping workload and concurrency stable; reducing one copy is not an end-to-end throughput guarantee.

Source: [Spark tuning and memory guidance](https://spark.apache.org/docs/latest/tuning.html).
