# Databricks system-table reference index

**Snapshot verified:** 2026-10-16 (UTC)
**Authority:** live workspace `SHOW SCHEMAS`, `SHOW TABLES`, and `DESCRIBE TABLE` for each task. This snapshot guides discovery and can become stale.
**Official source:** [System tables reference](https://docs.databricks.com/aws/en/admin/system-tables)

Availability markers below reproduce the status shown by the official catalog. An unmarked table had no Preview/Beta marker on the checked date. The page reports regional or global scope and a free retention period; account-configured retention may differ. Data delivery can lag and the workspace/cloud may expose only a subset.

| Table path | Purpose | State | Free retention | Scope |
|---|---|---|---:|---|
| `system.alert.alerts` | Alert configuration history | Public Preview | 365 days | Regional |
| `system.alert.alert_evaluation_history` | Alert evaluations and delivery state | Public Preview | 365 days | Regional |
| `system.access.audit` | Account/workspace audit events | Public Preview | 365 days | Regional workspace; global account events |
| `system.billing.usage` | Billable usage records | GA/unmarked | 365 days | Global |
| `system.access.clean_room_events` | Clean-room activity | Public Preview | 365 days | Regional |
| `system.compute.clusters` | Historical compute configuration (SCD2) | GA/unmarked | 365 days | Regional |
| `system.access.column_lineage` | Unity Catalog column read/write lineage | GA/unmarked | 365 days | Regional |
| `system.data_classification.results` | Column classification results | Public Preview | 13 months | Regional |
| `system.data_quality_monitoring.table_results` | Table quality results/incidents | Public Preview | 13 months | Regional |
| `system.tags.governed_tags` | Governed tag definitions | Beta | 365 days | Global |
| `system.access.assistant_events` | Genie Code events | Public Preview | 365 days | Regional |
| `system.ai_gateway.usage` | Unity Gateway usage/latency/token metrics | Public Preview | 365 days | Regional |
| `system.ai_gateway.external_model_spend` | Estimated external-model spend | Beta | 365 days | Regional |
| `system.lakebase.*` | Lakebase observability tables | Beta | 7 days | Regional |
| `system.sharing.materialization_history` | OpenSharing materialization events | GA/unmarked | 365 days | Regional for workspace data |
| `system.compute.instance_events` | Classic compute instance state transitions | Public Preview | 365 days | Regional |
| `system.compute.instance_pools` | Historical instance-pool configuration | Public Preview | 365 days | Regional |
| `system.lakeflow.job_run_timeline` | Job run start/end slices and outcome | GA/unmarked | 365 days | Regional |
| `system.lakeflow.job_task_run_timeline` | Task run slices and compute references | GA/unmarked | 365 days | Regional |
| `system.lakeflow.job_tasks` | Job task definitions (SCD2) | GA/unmarked | 365 days | Regional |
| `system.lakeflow.jobs` | Job definitions (SCD2) | GA/unmarked | 365 days | Regional |
| `system.marketplace.listing_funnel_events` | Marketplace listing funnel activity | Public Preview | 365 days | Regional |
| `system.marketplace.listing_access_events` | Marketplace listing access requests | Public Preview | 365 days | Regional |
| `system.mlflow.experiments_latest` | Managed MLflow experiment metadata | Public Preview | 180 days | Regional |
| `system.mlflow.runs_latest` | Managed MLflow run metadata | Public Preview | 180 days | Regional |
| `system.mlflow.run_metrics_history` | Managed MLflow run metric history | Public Preview | 180 days | Regional |
| `system.serving.served_entities` | Model-serving endpoint entity metadata | Public Preview | 365 days | Regional |
| `system.serving.endpoint_usage` | Model-serving endpoint token usage | Public Preview | 90 days | Regional |
| `system.access.inbound_network` | Denied inbound access events | Public Preview | 30 days | Regional |
| `system.access.outbound_network` | Denied outbound access events | Public Preview | 365 days | Regional |
| `system.compute.node_timeline` | Per-node utilization at minute granularity | GA/unmarked | 90 days | Regional |
| `system.compute.node_types` | Available node hardware metadata | GA/unmarked | Indefinite | Regional |
| `system.lakeflow_pipeline_events_preview.pipeline_events` | Pipeline lifecycle, flow, quality, and error events | Beta | 365 days | Regional |
| `system.lakeflow.pipeline_update_timeline` | Pipeline update duration and compute | GA/unmarked | 365 days | Regional |
| `system.lakeflow.pipelines` | Pipeline definitions (SCD2) | GA/unmarked | 365 days | Regional |
| `system.storage.table_auto_upgrade_operations_history` | Automatic table-upgrade operations | Public Preview | 180 days | Regional |
| `system.storage.predictive_optimization_operations_history` | Predictive optimization operations | Public Preview | 180 days | Regional |
| `system.billing.list_prices` | Historical SKU list prices | GA/unmarked | Indefinite | Global |
| `system.query.history` | Query execution and duration history | GA/unmarked | 365 days | Regional |
| `system.replication.states` | Managed disaster-recovery replication state | GA/unmarked | 365 days | Global |
| `system.compute.warehouse_events` | Warehouse start/stop/scale events | GA/unmarked | 365 days | Regional |
| `system.compute.warehouses` | Historical SQL warehouse configuration (SCD2) | GA/unmarked | 365 days | Regional |
| `system.access.table_lineage` | Unity Catalog table/path lineage | GA/unmarked | 365 days | Regional |
| `system.access.workspaces_latest` | Account workspace metadata | Public Preview | Indefinite | Global |
| `system.lakeflow.zerobus_stream` | Zerobus stream usage events | Beta | 365 days | Regional |
| `system.lakeflow.zerobus_ingest` | Zerobus ingestion records | Beta | 365 days | Regional |

## Focused references

- [Billing: usage schema, corrections, attribution, and pricing](system-tables/billing.md)
- [Compute: cluster history and node telemetry](system-tables/compute.md)
- [Lakeflow: jobs, timelines, and pipelines](system-tables/lakeflow.md)
- [Query history](system-tables/query.md)
- [SQL warehouse configuration and events](system-tables/warehouses.md)
- [Lineage](system-tables/lineage.md)
- [Audit/access and other schemas](system-tables/other-current-schemas.md)

System tables are read-only and access is governed by Unity Catalog. The official documentation warns against moving raw system-table data outside Databricks. Prefer narrow filters and aggregation; never save raw rows to Anvil memory.
