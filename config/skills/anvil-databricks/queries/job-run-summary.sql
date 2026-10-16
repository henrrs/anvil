-- Timeline rows are hourly slices for long runs. Aggregate slices per run first.
WITH run_summary AS (
  SELECT
    workspace_id,
    job_id,
    run_id,
    SUM(UNIX_TIMESTAMP(period_end_time) - UNIX_TIMESTAMP(period_start_time)) AS runtime_seconds,
    MAX(result_state) AS result_state
  FROM system.lakeflow.job_run_timeline
  WHERE job_id = :job_id
    AND period_start_time >= :start_time
    AND period_start_time < :end_time
  GROUP BY workspace_id, job_id, run_id
)
SELECT
  workspace_id,
  job_id,
  COUNT(*) AS run_count,
  SUM(CASE WHEN result_state = 'SUCCEEDED' THEN 1 ELSE 0 END) AS succeeded_runs,
  SUM(CASE WHEN result_state IN ('FAILED', 'ERROR', 'TIMED_OUT') THEN 1 ELSE 0 END) AS failed_runs,
  PERCENTILE_APPROX(runtime_seconds, 0.50) AS runtime_p50_seconds,
  PERCENTILE_APPROX(runtime_seconds, 0.95) AS runtime_p95_seconds
FROM run_summary
GROUP BY workspace_id, job_id
LIMIT 100;
