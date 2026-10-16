# Billing system tables

**Verified:** 2026-10-16. Official references: [usage](https://docs.databricks.com/aws/en/admin/system-tables/billing) and [pricing](https://docs.databricks.com/aws/en/admin/system-tables/pricing).

## `system.billing.usage`

Global billable usage. Important fields include `workspace_id`, `sku_name`, `cloud`, `usage_start_time`, `usage_end_time`, `usage_date`, `usage_unit`, `usage_quantity`, `usage_metadata`, `identity_metadata`, `record_type`, `billing_origin_product`, and `usage_type`. The catalog lists 365 days free retention. Records are typically available within 12 hours; new workspaces can take longer.

Useful `usage_metadata` keys include `cluster_id`, `warehouse_id`, `job_id`, and `job_run_id`. Job/run IDs are populated for dedicated job and serverless jobs, not jobs that run on all-purpose compute. `cluster_id` supports shared cluster-level cost analysis; it does not make per-job attribution precise. Usage on all-purpose compute is attributed to the compute creator in `identity_metadata.run_as`, not necessarily its current owner.

Do not filter out corrections. Retraction rows negate old quantities and restatements carry corrected quantities. Sum quantities across `record_type` to preserve corrections. Filter `usage_start_time`/`usage_end_time` with a precise UTC window and aggregate before returning results.

## `system.billing.list_prices`

Global historical SKU price log with `sku_name`, `cloud`, `currency_code`, `usage_unit`, `price_start_time`, `price_end_time`, and `pricing.default` (plus promotional/effective list fields). Match each usage interval to the price effective at `usage_start_time`; avoid joining every price row in a long period. This yields a list-cost estimate in the listed currency, not an invoiced discounted cost or complete cloud bill.

## Useful analytical joins

- Dedicated job usage to run timeline: `workspace_id`, `job_id`, and `usage_metadata.job_run_id = run_id`.
- Cluster usage to historical cluster config: `workspace_id` plus `usage_metadata.cluster_id = cluster_id`; apply effective config time.
- Warehouse usage to query history: `usage_metadata.warehouse_id = compute.warehouse_id`, with workspace and time window where applicable.
- For all-purpose shared clusters, state the allocation method and approximate attribution explicitly.
