# Connector boundary

Distinguish generic source intent, connector capabilities, scan/partition planning and runtime reader execution. DataSource V2 offers interfaces for those concerns, including optional pushdowns; availability depends on API/runtime/connector version. A connector claiming support is not proof that this query pushed down filtering, columns, aggregates or limits: inspect its physical plan and actual source requests.

Evaluate partition readers, columnar versus row paths, type semantics, cancellation, retries and cleanup. For streaming, identify offset/commit ownership separately from batch partition planning. Unsupported capabilities need an explicit fallback, not silent changes in correctness.

A future connector implementation can justify an adapter boundary, but Spark interfaces must not become the generic ingestion contract solely because Spark is first. Keep source profiling/planning ownership singular and test both pushdown correctness and failure cleanup.

Source: [Spark Data Source V2](https://spark.apache.org/docs/latest/sql-data-sources-v2.html); verify relevant interfaces in the deployed Spark API.
