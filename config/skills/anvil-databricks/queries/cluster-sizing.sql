-- Match each telemetry sample to the effective SCD2 compute configuration.
WITH configurations AS (
  SELECT
    workspace_id,
    cluster_id,
    create_time,
    LEAD(create_time) OVER (PARTITION BY workspace_id, cluster_id ORDER BY create_time) AS next_change,
    worker_node_type,
    driver_node_type,
    worker_count,
    min_autoscale_workers,
    max_autoscale_workers
  FROM system.compute.clusters
  WHERE cluster_id = :cluster_id
    AND create_time < :end_time
), bounded_nodes AS (
  SELECT
    n.workspace_id,
    n.cluster_id,
    n.start_time,
    n.driver,
    n.cpu_user_percent + n.cpu_system_percent AS cpu_pct,
    n.cpu_wait_percent,
    n.mem_used_percent,
    n.instance_id
  FROM system.compute.node_timeline n
  WHERE n.cluster_id = :cluster_id
    AND n.start_time >= :start_time
    AND n.start_time < :end_time
)
SELECT
  n.driver,
  c.worker_node_type,
  c.driver_node_type,
  c.worker_count,
  c.min_autoscale_workers,
  c.max_autoscale_workers,
  COUNT(*) AS samples,
  PERCENTILE_APPROX(n.cpu_pct, 0.95) AS cpu_p95_pct,
  MAX(n.cpu_pct) AS cpu_max_pct,
  PERCENTILE_APPROX(n.cpu_wait_percent, 0.95) AS cpu_wait_p95_pct,
  PERCENTILE_APPROX(n.mem_used_percent, 0.95) AS memory_p95_pct,
  MAX(n.mem_used_percent) AS memory_max_pct,
  COUNT(DISTINCT n.instance_id) AS observed_instances
FROM bounded_nodes n
JOIN configurations c
  ON n.workspace_id = c.workspace_id
  AND n.cluster_id = c.cluster_id
  AND n.start_time >= c.create_time
  AND (c.next_change IS NULL OR n.start_time < c.next_change)
GROUP BY n.driver, c.worker_node_type, c.driver_node_type, c.worker_count, c.min_autoscale_workers, c.max_autoscale_workers
LIMIT 20;
