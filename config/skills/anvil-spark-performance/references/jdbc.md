# Source-read and database capacity

Separate the database query plan/waits, network, driver fetch/decoding, Python/Arrow conversion and Spark task timing. Measure source concurrency, sessions, CPU/I/O/locks and query latency with owner-approved bounded tests. More Spark partitions can saturate the database while leaving executor CPU low.

Inspect predicates/projection, partition column distribution/nulls, bounds, fetch/batch behavior, consistency and per-connection overhead. Spark JDBC lower/upper bounds define partition stride rather than a general row filter; inspect generated predicates and validate row coverage. A Python/ODBC reader inside a task is a different path from Spark's JDBC connector; settings for one do not automatically control the other.

Benchmark source-only reads at controlled concurrency, then compare conversion-only and integrated paths. Retries need one owner and a source-capacity budget. Validate credentials through supported provider storage, never copied into task evidence.

Source: [Spark JDBC data source](https://spark.apache.org/docs/latest/sql-data-sources-jdbc.html). Database-specific limits require that database's deployed evidence/documentation.
