-- Parametrize :job_id, :start_time, and :end_time in the Statement Execution API.
-- Usage rows only carry job/run IDs for dedicated job or serverless compute.
WITH run_slices AS (
  SELECT
    workspace_id,
    job_id,
    run_id,
    SUM(UNIX_TIMESTAMP(period_end_time) - UNIX_TIMESTAMP(period_start_time)) AS runtime_seconds
  FROM system.lakeflow.job_run_timeline
  WHERE job_id = :job_id
    AND period_start_time >= :start_time
    AND period_start_time < :end_time
  GROUP BY workspace_id, job_id, run_id
), usage_by_run AS (
  SELECT
    workspace_id,
    usage_metadata.job_id AS job_id,
    usage_metadata.job_run_id AS run_id,
    usage_start_time,
    sku_name,
    usage_unit,
    cloud,
    SUM(usage_quantity) AS usage_quantity
  FROM system.billing.usage
  WHERE usage_start_time >= :start_time
    AND usage_start_time < :end_time
    AND usage_metadata.job_id = :job_id
    AND usage_metadata.job_run_id IS NOT NULL
  GROUP BY workspace_id, usage_metadata.job_id, usage_metadata.job_run_id, usage_start_time, sku_name, usage_unit, cloud
)
SELECT
  u.job_id,
  u.run_id,
  r.runtime_seconds,
  u.sku_name,
  u.usage_unit,
  u.usage_quantity,
  SUM(u.usage_quantity * CAST(p.pricing.default AS DOUBLE)) AS list_cost,
  p.currency_code
FROM usage_by_run u
LEFT JOIN run_slices r
  ON u.workspace_id = r.workspace_id AND u.job_id = r.job_id AND u.run_id = r.run_id
LEFT JOIN system.billing.list_prices p
  ON p.sku_name = u.sku_name
  AND p.cloud = u.cloud
  AND p.usage_unit = u.usage_unit
  AND p.price_start_time <= u.usage_start_time
  AND (p.price_end_time IS NULL OR p.price_end_time > u.usage_start_time)
GROUP BY u.job_id, u.run_id, r.runtime_seconds, u.sku_name, u.usage_unit, u.usage_quantity, p.currency_code
ORDER BY list_cost DESC
LIMIT 100;
