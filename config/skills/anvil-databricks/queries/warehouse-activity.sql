-- Query history contains regional query aggregates; do not apply classic node metrics.
SELECT
  compute.warehouse_id AS warehouse_id,
  COUNT(*) AS query_count,
  SUM(CASE WHEN execution_status = 'FINISHED' THEN 1 ELSE 0 END) AS finished_queries,
  SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed_queries,
  PERCENTILE_APPROX(total_duration_ms / 1000.0, 0.50) AS duration_p50_seconds,
  PERCENTILE_APPROX(total_duration_ms / 1000.0, 0.95) AS duration_p95_seconds,
  PERCENTILE_APPROX(waiting_at_capacity_duration_ms / 1000.0, 0.95) AS queue_p95_seconds
FROM system.query.history
WHERE compute.type = 'WAREHOUSE'
  AND start_time >= :start_time
  AND start_time < :end_time
  AND compute.warehouse_id = :warehouse_id
GROUP BY compute.warehouse_id
LIMIT 20;
