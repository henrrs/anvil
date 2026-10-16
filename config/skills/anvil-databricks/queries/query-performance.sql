-- Excludes statement_text and user-level fields; result is aggregated by type/status.
SELECT
  compute.warehouse_id AS warehouse_id,
  statement_type,
  execution_status,
  COUNT(*) AS query_count,
  PERCENTILE_APPROX(execution_duration_ms / 1000.0, 0.50) AS execution_p50_seconds,
  PERCENTILE_APPROX(execution_duration_ms / 1000.0, 0.95) AS execution_p95_seconds,
  PERCENTILE_APPROX(waiting_at_capacity_duration_ms / 1000.0, 0.95) AS queue_p95_seconds
FROM system.query.history
WHERE start_time >= :start_time
  AND start_time < :end_time
  AND compute.type = 'WAREHOUSE'
  AND compute.warehouse_id = :warehouse_id
GROUP BY compute.warehouse_id, statement_type, execution_status
ORDER BY query_count DESC
LIMIT 100;
