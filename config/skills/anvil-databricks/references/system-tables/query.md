# Query history

**Verified:** 2026-10-16. Official reference: [Query history system table](https://docs.databricks.com/aws/en/admin/system-tables/query-history).

`system.query.history` captures queries on SQL warehouses and serverless compute, including notebook/job/pipeline cases; 365 days free retention, regional. Records are typically available within one hour, longer for new workspaces. By default, access is restricted; check grants rather than inferring missing data.

Useful fields include `workspace_id`, `statement_id`, `execution_status`, `compute.type`, `compute.warehouse_id`, `statement_type`, `total_duration_ms`, `waiting_for_compute_duration_ms`, `waiting_at_capacity_duration_ms`, `execution_duration_ms`, `start_time`, and `end_time`. `query_source` can include job/run/task IDs; those relationships identify workload context, not necessarily direct per-query cost.

Filter `start_time` to the requested interval, select only aggregate metrics, and avoid `statement_text`, user IDs, and raw query rows unless explicitly necessary. Group by warehouse/type/status and report run counts, p50/p95 duration, queue time, and failures. Do not use classic node metrics as a proxy for warehouse internals.
