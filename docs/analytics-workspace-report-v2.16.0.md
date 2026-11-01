# Anvil 2.16.0 Analytics Workspace — Engineering Report

## Result

The Analytics Workspace implementation and offline acceptance gates pass. It is installed by default through the existing Anvil lifecycle, while the Anvil core and shared Databricks capability remain independent of Analytics business logic. No live OpenCode process, model, Databricks workspace, or Windows browser route was tested.

## Delivered

- A local-only, same-origin Analytics UI and loopback BFF with request bounds, security headers, and contextual Ask Anvil streaming.
- Runtime-specific OpenCode 1 and OpenCode 2 adapters that use the same bounded local Analytics tool bridge and canonical/task session manager.
- SQLite WAL context and catalog cache; lazy metadata hydration; bounded preview, profile, lineage, query history, and route comparison.
- Read-only remote SQL plus conservative local DuckDB routing when source, columns, and filters have proven Parquet coverage.
- Explicitly planned, bounded Arrow-to-Parquet materialization with checksums, resumable checkpoints, atomic publication, and approval for the tool action.
- Fresh-install, upgrade, idempotency, dry-run, rollback, service ownership, and Analytics data-preservation lifecycle coverage.
- `make analytics`, `make analytics-status`, `make analytics-stop`, and `make eval-analytics`; inspect, doctor, and capabilities report Analytics state.
- User, architecture, data-plane and operations guides, the 2.15-to-2.16 migration guide, capability matrix, ADR-0023 and release notes.

The same-major Anvil migration window is ten prior minor releases so an installed 2.6.x profile remains upgradeable. Analytics does not update OpenCode or require a runtime-major migration.

## Verification evidence

| Gate | Result |
|---|---|
| `make test` | PASS — full offline suite, including OpenCode 1/2, Databricks, analysis, communication, engineering, lifecycle and rollback scenarios |
| Analytics unit and service contracts | PASS — 56 tests |
| `make eval-analytics` | PASS — 59/59 checks; JUnit, JSON, scenario and summary artifacts generated |
| `python3 tests/analytics_lifecycle.py` | PASS — fresh install, upgrade, repeatability, dry-run, rollback and user-data preservation |
| `python3 scripts/version_docs.py` | PASS — release, migration and capability documentation are aligned |
| Python compilation and `node --check web/analytics/app.js` | PASS |
| `git diff --check` | PASS |

Certification evidence is stored under [`artifacts/analytics-certification/`](../artifacts/analytics-certification/), including [`summary.md`](../artifacts/analytics-certification/summary.md), `report.json`, `scenarios.json` and JUnit-compatible `pytest.xml`.

## Boundaries and remaining validation

- No live Databricks authentication, permissions, warehouse, SQL execution, or Arrow transfer was tested. Databricks setup remains explicit and Analytics reuses the existing Anvil-owned profile/provider.
- No model request or live OpenCode plugin execution was tested. The V1 and V2 plugin adapters have offline source/contract coverage only; live tool loading and model quality remain unmeasured.
- Windows-to-WSL browser reachability is environment-specific and remains `NOT_CHECKED` by local certification.
- DuckDB and PyArrow are optional dependencies. Their absence degrades local SQL or materialization without blocking catalog browsing and supported remote operations.
- Lineage depends on workspace grants and the coverage of Databricks' [table lineage system table](https://docs.databricks.com/aws/en/admin/system-tables/lineage).

## Start and inspect

For an installed Anvil instance, review `make upgrade DRY_RUN=1`, run `make upgrade`, then use `make analytics-status` and `make analytics`. Open `http://anvil.localhost:8765`. If Databricks is not configured, run `make databricks-setup` explicitly. See the [user guide](analytics-workspace.md) and [operations guide](analytics-workspace-operations.md).
