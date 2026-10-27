# Arrow and Python boundaries

`mapInArrow` maps iterators of Arrow record batches with an explicit output schema. It does not make arbitrary external calls distributed unless input partitions/tasks actually distribute them, and it does not prove zero-copy end to end. Locate conversion, Python worker execution, external driver buffers and serialization on both sides.

Collect batch rows/bytes, conversion duration, Python/native/JVM memory, task concurrency and source-call duration. Preserve null, decimal, timestamp/timezone, binary and large-value behavior through the actual versions. A row-count batch limit does not bound bytes for variable-width rows. Barrier/resource behavior is version-sensitive; inspect the deployed API.

Use discriminating experiments: identical input without the external read, conversion-only workload, bounded batch-size variation, and source-only extraction at the same concurrency. Separate conversion cost from source wait before choosing Arrow, vectorization or partition changes. Maintain output equivalence and backpressure.

Source: [PySpark mapInArrow API](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.mapInArrow.html).
