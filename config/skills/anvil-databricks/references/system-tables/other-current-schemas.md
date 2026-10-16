# Other current system schemas

**Verified:** 2026-10-16. The [official current catalog](https://docs.databricks.com/aws/en/admin/system-tables) was checked for this release; its table-by-table status, retention, and scope snapshot is in [the index](../system-tables-index.md).

Other documented areas include:

- `access`: audit, assistant, clean-room, inbound/outbound network, lineage, and workspace metadata.
- `alert`: alert definitions and evaluation history.
- `data_classification` and `data_quality_monitoring`: classification/quality results.
- `ai_gateway` and `serving`: request/token/spend and served-entity data. Usage tracking or feature enablement may be required.
- `lakebase`: short-retention Postgres observability, currently Beta.
- `marketplace`, `mlflow`, `replication`, `sharing`, `storage`, and `tags`.
- `lakeflow_pipeline_events_preview` and Zerobus tables for preview/Beta pipeline and ingestion events.
- `system.information_schema` is a separate metadata interface and does not behave like the operational system tables in the catalog index.

Availability can depend on cloud/region, account enablement, Unity Catalog, grants, and preview/Beta enrollment. A global table may span regions while an operational table may be regional. A table marked available in the documentation is not proof that the selected workspace can query it. Use live `SHOW SCHEMAS`, `SHOW TABLES`, then `DESCRIBE TABLE` as needed.
