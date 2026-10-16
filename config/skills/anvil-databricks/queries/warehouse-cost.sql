-- This reports Databricks list-cost estimates for the selected warehouse.
SELECT
  usage_metadata.warehouse_id AS warehouse_id,
  sku_name,
  usage_unit,
  p.currency_code,
  SUM(usage_quantity) AS usage_quantity,
  SUM(usage_quantity * CAST(p.pricing.default AS DOUBLE)) AS list_cost
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices p
  ON p.sku_name = u.sku_name
  AND p.cloud = u.cloud
  AND p.usage_unit = u.usage_unit
  AND p.price_start_time <= u.usage_start_time
  AND (p.price_end_time IS NULL OR p.price_end_time > u.usage_start_time)
WHERE usage_metadata.warehouse_id = :warehouse_id
  AND usage_start_time >= :start_time
  AND usage_start_time < :end_time
  AND usage_type = 'COMPUTE_TIME'
GROUP BY usage_metadata.warehouse_id, sku_name, usage_unit, p.currency_code
ORDER BY list_cost DESC
LIMIT 100;
