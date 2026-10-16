# System-table knowledge and live discovery

Anvil ships a dated system-table snapshot in [`system-tables-index.md`](../../config/skills/anvil-databricks/references/system-tables-index.md) and focused billing, compute, Lakeflow, query, warehouse, lineage, and access references alongside it. The snapshot was checked against the current [official catalog](https://docs.databricks.com/aws/en/admin/system-tables) on 2026-10-16. It records documented status, purpose, free retention, and regional/global scope for every table in the catalog on that date.

The snapshot is reference material, not a guarantee for a specific account. Before a live analysis, use `SHOW SCHEMAS IN system`, `SHOW TABLES IN system.<schema>`, and `DESCRIBE TABLE` as appropriate. Live schema, grants, cloud/region, account enablement, preview enrollment, and configured retention decide what is available. Mention a relevant difference between live schema and the snapshot.

System tables are read-only and may contain sensitive operational data. Filter at the source, aggregate in Databricks, and return only bounded fields relevant to the task. Do not persist raw rows in Anvil memory. System-table grants typically require `USE CATALOG`, `USE SCHEMA`, and `SELECT`; default access can be limited. The official catalog warns that exported operational data can expose sensitive information.

Record availability varies: billing usage is typically available within 12 hours; query history within about one hour; new workspaces can take longer. Retention is table-specific unless account-level configurable retention applies. Neither a documented retention window nor a static schema snapshot guarantees data is complete for the requested period.
