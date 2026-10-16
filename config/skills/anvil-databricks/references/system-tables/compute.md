# Compute system tables

**Verified:** 2026-10-16. Official reference: [Compute system tables](https://docs.databricks.com/aws/en/admin/system-tables/compute).

## `system.compute.clusters`

Slowly changing configuration history for all-purpose, jobs, Lakeflow pipeline, and maintenance compute; 365 days free retention, regional. Common fields: `workspace_id`, `cluster_id`, `cluster_name`, `owned_by`, `create_time`, `delete_time`, `driver_node_type`, `worker_node_type`, `worker_count`, `min_autoscale_workers`, `max_autoscale_workers`, and `auto_termination_minutes`. Resolve the configuration effective at each event/sample time; current settings may not match the analysis window.

## `system.compute.node_timeline`

Minute-granularity, per-instance records for all-purpose, jobs, pipelines, and pipeline-maintenance compute; 90 days free retention, regional. Common fields: `workspace_id`, `cluster_id`, `instance_id`, `start_time`, `end_time`, `driver`, `cpu_user_percent`, `cpu_system_percent`, `cpu_wait_percent`, `mem_used_percent`, `mem_swap_percent`, `network_sent_bytes`, `network_received_bytes`, and `node_type`.

Aggregate worker and driver rows separately. Report sample count and coverage alongside CPU average/p50/p95/max, CPU-wait p95, memory p95/max, worker-count distribution, and network signals where relevant. One low average is not evidence for a safe downsize; inspect peaks, memory, wait, run-duration distribution, sample size, config history, and SLA constraints.

## `system.compute.node_types`

Current available node type metadata: `node_type`, `core_count`, `memory_mb`, and `gpu_count`; indefinite retention, regional. It is a current dimension, not historical hardware inventory.

## Other compute tables

The current catalog also lists `system.compute.instance_events` and `system.compute.instance_pools` (Public Preview), and `system.compute.warehouses` / `system.compute.warehouse_events`. See [warehouse references](warehouses.md). Check each table's current availability in the live workspace.
