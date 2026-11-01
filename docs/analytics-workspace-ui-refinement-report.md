# Analytics Workspace UI Refinement Report

## Scope

This incremental refinement preserves the Analytics service, canonical OpenCode session, shared Databricks capability, Context Store, DuckDB, materialization flow and lifecycle package boundary. It does not add cost, savings, billing or FinOps features.

## Implemented

- A useful Analytics Home for recent tables and queries, favorites, local snapshots, active operations and completed investigations.
- Closable table/query workspaces; table Overview, Columns, Preview, Lineage and Local data tabs; bounded catalog paging; favorites/recent lists; responsive resizable and collapsible side panels; keyboard focus and visible status states.
- SQL Warehouse discovery through `ComputePort` and the shared Databricks resolver, with a 60-second in-memory cache, safe metadata projection, refresh, predictable selection, stale/error handling and browser-local selected-ID persistence. Stopped compute is never started by discovery.
- `HttpAnalyticsApi` for production and a separate fixture-backed `MockAnalyticsApi` for development. The mock is served by a static loopback server, makes no backend/model calls, and supports healthy, offline, degraded, materializing and large-catalog scenarios plus warehouse edge cases.
- Recent operations and completed investigation summaries on Home through existing SQLite tables; removed external footer navigation.

## Production and mock isolation

The production page loads only `HttpAnalyticsApi`. Its server allowlist contains the four production assets, while managed lifecycle packaging excludes `web/analytics/dev/`. The mock command serves static repository assets at `127.0.0.1` and has no route to Databricks, OpenCode or the Analytics BFF.

## Verification

Baseline before editing: `make test` passed before changes. Final verification:

- `make test` — PASS; all Anvil offline checks passed, including 68 Analytics contract tests, lifecycle install/upgrade/reforge/rollback, and the large external managed-config plan regression.
- `make eval-analytics` — PASS, 60/60 Analytics certification checks.
- `git diff --check` — PASS.
- Mock preview — started without the Anvil service or Databricks and visually reviewed in Firefox. The Home, table overview/preview, SQL workspace and warehouse selector rendered from fixtures.
- Screenshots at 1920×1080: [healthy Home](../artifacts/analytics-ui-refinement/healthy.png), [degraded Home](../artifacts/analytics-ui-refinement/degraded.png).

No live Databricks workspace, OpenCode model response, or real SQL Warehouse query was used for this offline implementation check. Mock query/chat/materialization responses are fixtures and are not evidence of live provider behavior.

## Files and artifacts

- User guide: [`analytics-workspace.md`](analytics-workspace.md)
- Operations guide: [`analytics-workspace-operations.md`](analytics-workspace-operations.md)
- Architecture: [`analytics-workspace-architecture.md`](analytics-workspace-architecture.md)
- Data plane: [`analytics-workspace-data-plane.md`](analytics-workspace-data-plane.md)
- Visual captures: [`healthy.png`](../artifacts/analytics-ui-refinement/healthy.png) and [`degraded.png`](../artifacts/analytics-ui-refinement/degraded.png).
