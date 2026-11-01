# Anvil Analytics certification — 2.16.0

Run time: 2026-11-01T01:11:39Z

Result: **PASS** — 60/60 offline checks passed.

| Suite | Result | Checks | Time | Coverage |
|---|---:|---:|---:|---|
| context_store | PASS | 6/6 | 0.024s | SQLite context, privacy, WAL, migration and search |
| catalog | PASS | 11/11 | 0.060s | Shared Databricks capability, cached catalog and lazy hydration |
| query_materialization | PASS | 16/16 | 0.096s | Read-only routing, coverage, Parquet snapshots and resumable transfer |
| runtime_sessions | PASS | 9/9 | 1.598s | OpenCode 1/2 adapters, runtime warmup, canonical and task sessions |
| http_ui | PASS | 7/7 | 3.536s | Loopback BFF, same-origin API, static UI and contextual SSE |
| tools_service | PASS | 8/8 | 0.531s | OpenCode tool bridges, profile, lineage and route comparison |
| lifecycle | PASS | 1/1 | 1.291s | Fresh install, 2.15→2.16 upgrade, idempotency, dry-run, rollback and user data preservation |
| frontend_syntax | PASS | 1/1 | 0.117s | Static frontend JavaScript syntax |
| python_syntax | PASS | 1/1 | 0.098s | Compile Analytics modules |

## Scope and limits

The certification runs local fixtures, fake OpenCode 1/2 HTTP servers, fake Databricks provider responses, a loopback BFF, and isolated temporary HOME/XDG lifecycle roots. It does not contact a live OpenCode model, Databricks workspace, Windows browser, or production credential store.

- Live OpenCode prompt/tool execution and model quality were not measured.
- Live Databricks permissions, authentication, SQL warehouse behavior, and Arrow CloudFetch were not measured.
- Windows-to-WSL browser reachability is environment-specific and remains a host-side check.
- DuckDB and PyArrow availability depends on the user's Python environment; missing optional packages are reported as degraded.

## Artifacts

- `report.json` — machine-readable suite and test case results.
- `scenarios.json` — scenario group status and evidence mapping.
- `pytest.xml` — JUnit-compatible test report.
