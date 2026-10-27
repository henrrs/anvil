# Execution localization

Map actions to jobs, wide dependencies to stage boundaries, and partitions to tasks. Use the actual SQL/event-log timeline rather than assuming one source call equals one stage. Driver planning, file listing, task scheduling and application startup can dominate a short job while executors remain underutilized. Separate startup from steady-state processing in a benchmark.

Logical optimizations and physical execution are different evidence. Identify scans, filters, exchanges, sorts, joins, row/columnar transitions and Python operators. Whole-stage/code-generated JVM execution and memory/serialization mechanisms associated with Tungsten do not imply that arbitrary Python or external I/O runs in that engine. Photon requires its own operator evidence.

Compare input/output bytes/rows, task quantiles, CPU time, wait, retries and executor loss. Low CPU may mean source/network/storage wait, scheduling or blocked Python; it does not prove spare useful parallelism. A driver-side loop cannot be fixed by increasing executor count until the work distribution actually changes.

Source: [Spark RDD execution guide](https://spark.apache.org/docs/latest/rdd-programming-guide.html). Check the deployed SQL/runtime plan for concrete operator behavior.
