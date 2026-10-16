# SQL warehouse system tables

**Verified:** 2026-10-16. Official references: [warehouse configuration history](https://docs.databricks.com/aws/en/admin/system-tables/warehouses), [warehouse events](https://docs.databricks.com/aws/en/admin/system-tables/warehouse-events), and [query history](https://docs.databricks.com/aws/en/admin/system-tables/query-history).

## `system.compute.warehouses`

SCD2 snapshots of warehouse configuration; 365 days free retention, regional. Fields include `workspace_id`, `warehouse_id`, `warehouse_name`, `warehouse_type` (`CLASSIC`, `PRO`, `SERVERLESS`), `warehouse_size`, `min_clusters`, `max_clusters`, `auto_stop_minutes`, `change_time`, and `delete_time`. Resolve effective configuration over the requested window.

## `system.compute.warehouse_events`

Start, stop, running, and scale transitions; 365 days free retention, regional. Common fields are `workspace_id`, `warehouse_id`, `event_type`, `cluster_count`, and `event_time`. Use event ordering to understand startup, uptime, scale behavior, and idle periods; validate how event coverage and transitions apply to the selected window.

## Analysis

Use warehouse configuration/events, `system.query.history`, and `system.billing.usage` plus `system.billing.list_prices` when available. Analyze query count, execution and queue duration, failures, scaling, running/idle intervals, auto-stop, size, usage, and list-cost evidence. Cost attribution to a shared warehouse is approximate at workload/query level. Never apply `system.compute.node_timeline` CPU or memory metrics to SQL warehouse internals.
