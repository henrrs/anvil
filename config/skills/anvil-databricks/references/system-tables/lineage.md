# Lineage tables

**Verified:** 2026-10-16. Official source: [System tables reference](https://docs.databricks.com/aws/en/admin/system-tables).

- `system.access.table_lineage`: Unity Catalog table/path read and write events; 365 days free retention, regional.
- `system.access.column_lineage`: Unity Catalog column read/write events with source information; events without a source are not included; 365 days free retention, regional.

Lineage coverage depends on supported operations, Unity Catalog, permissions, and source availability. Filter by a narrow event-time window and requested object/workload. Do not infer a missing dependency when lineage is incomplete. Use live schema inspection before joins; never return large object-level lineage extracts when counts/aggregates answer the question.
