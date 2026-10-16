-- Percentages are per-node telemetry. Keep driver and worker populations separate.
SELECT
  cluster_id,
  driver,
  COUNT(*) AS node_minute_samples,
  COUNT(DISTINCT instance_id) AS observed_instances,
  AVG(cpu_user_percent + cpu_system_percent) AS cpu_avg_pct,
  PERCENTILE_APPROX(cpu_user_percent + cpu_system_percent, 0.50) AS cpu_p50_pct,
  PERCENTILE_APPROX(cpu_user_percent + cpu_system_percent, 0.95) AS cpu_p95_pct,
  MAX(cpu_user_percent + cpu_system_percent) AS cpu_max_pct,
  PERCENTILE_APPROX(cpu_wait_percent, 0.95) AS cpu_wait_p95_pct,
  PERCENTILE_APPROX(mem_used_percent, 0.95) AS memory_p95_pct,
  MAX(mem_used_percent) AS memory_max_pct
FROM system.compute.node_timeline
WHERE cluster_id = :cluster_id
  AND start_time >= :start_time
  AND start_time < :end_time
GROUP BY cluster_id, driver
LIMIT 10;
