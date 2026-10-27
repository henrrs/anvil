# Partition strategy

Distinguish source-read partitions, shuffle partitions and output files. They have different owners and constraints. Estimate bytes/rows and skew per task against executor concurrency, memory and source connection capacity. Too few large partitions may serialize work; many tiny partitions can amplify scheduling and file costs. A count without distribution is incomplete evidence.

For source partitions inspect predicate coverage, nulls, boundary values, snapshot semantics and source query plans. For repartition/coalesce inspect whether an exchange occurs and whether reduced parallelism extends the critical path. For output changes verify actual files, sizes and downstream scan behavior. Partitioning by a high-cardinality key may create many directories/files rather than useful pruning.

Keep one variable stable at a time: source sessions, row shape, executor resources and adaptive execution affect the interpretation. Correctness checks must prove coverage without gaps or duplicate ranges.

Source: [Spark SQL partition tuning](https://spark.apache.org/docs/latest/sql-performance-tuning.html#tuning-partitions).
