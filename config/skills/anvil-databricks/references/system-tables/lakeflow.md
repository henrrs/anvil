# Lakeflow system tables

**Verified:** 2026-10-16. Official reference: [Jobs and pipelines system tables](https://docs.databricks.com/aws/en/admin/system-tables/jobs).

Current job/pipeline tables include:

- `system.lakeflow.jobs` and `system.lakeflow.job_tasks`: slow-changing definitions. Select the latest row by `change_time` per `(workspace_id, job_id)` or `(workspace_id, job_id, task_key)`, then apply `delete_time IS NULL`.
- `system.lakeflow.job_run_timeline`: run intervals and outcome.
- `system.lakeflow.job_task_run_timeline`: task intervals, task keys, compute IDs, and outcomes.
- `system.lakeflow.pipelines`: pipeline definitions (SCD2), keyed by `(workspace_id, pipeline_id)`.
- `system.lakeflow.pipeline_update_timeline`: update interval and outcome.
- `system.lakeflow_pipeline_events_preview.pipeline_events`: currently Beta event details.

Timelines can contain multiple slices for a long run. Starting 2026-01-19, new rows use clock-hour-aligned slices. Aggregate by workspace and run/update identity before counting executions or deriving duration. Do not count timeline rows as run counts. A zero-length interval can represent a run that never began; inspect termination metadata.

For job cost, prefer dedicated job compute or serverless when `usage_metadata.job_id` and `job_run_id` exist. If the job shares all-purpose compute, run duration and cluster usage can support an explicitly approximate allocation, not measured per-job infrastructure cost. A job task may refer to multiple compute IDs; validate the relevant live schema and timeline coverage.

The current catalog also includes `system.lakeflow.zerobus_stream` and `system.lakeflow.zerobus_ingest` (Beta). They are outside the FinOps recipes unless a task specifically needs them.
