# Anvil Analytics certification — 2.17.0

Run time: 2026-11-01T23:04:23Z

Result: **PASS** — 93/93 offline checks passed.

| Suite | Result | Checks | Time | Coverage |
|---|---:|---:|---:|---|
| context_store | PASS | 8/8 | 0.039s | SQLite context, privacy, WAL, migration and search |
| catalog | PASS | 14/14 | 1.838s | Shared Databricks capability, cached catalog and lazy hydration |
| catalog_hydration | PASS | 2/2 | 0.000s | Cached tree convergence, progress, resume and metadata-only discovery |
| query_materialization | PASS | 16/16 | 0.091s | Read-only routing, coverage, Parquet snapshots and resumable transfer |
| runtime_sessions | PASS | 10/10 | 1.618s | OpenCode 1/2 adapters, runtime warmup, canonical and task sessions |
| dependency_runtime | PASS | 4/4 | 0.075s | Release-pinned Analytics dependencies, drift repair and safe staging |
| service_lifecycle | PASS | 6/6 | 0.137s | systemd ownership, MainPID, unit verification and service convergence |
| warehouse_lifecycle | PASS | 4/4 | 0.005s | Stopped/start transitions, permission feedback and timeout |
| http_ui | PASS | 7/7 | 3.536s | Loopback BFF, same-origin API, static UI and contextual SSE |
| frontend_ui | PASS | 11/11 | 1.470s | Static UI contracts, accessible resizable SQL/results split and mock scenarios |
| tools_service | PASS | 8/8 | 0.535s | OpenCode tool bridges, profile, lineage and route comparison |
| lifecycle | PASS | 1/1 | 1.773s | Fresh install, 2.15→2.17 and 2.16→2.17 convergence, idempotency, dry-run, rollback and user data preservation |
| frontend_syntax | PASS | 1/1 | 0.108s | Static frontend JavaScript syntax |
| python_syntax | PASS | 1/1 | 0.112s | Compile Analytics modules |

## Scope and limits

The certification runs local fixtures, fake OpenCode 1/2 HTTP servers, fake Databricks provider responses, a loopback BFF, and isolated temporary HOME/XDG lifecycle roots. It does not contact a live OpenCode model, Databricks workspace, Windows browser, or production credential store.

- Live OpenCode prompt/tool execution and model quality were not measured.
- Live Databricks permissions, authentication, SQL warehouse behavior, and Arrow CloudFetch were not measured.
- Windows-to-WSL browser reachability is environment-specific and remains a host-side check.
- Release-pinned DuckDB/PyArrow wheels and their host ABI compatibility were not downloaded in the offline certification; install-time import checks are enforced before publishing the isolated runtime.
- Systemd ordering and MainPID semantics are fixture-checked and the generated unit is statically verified; this runner did not enable a real user service or OpenCode executable.

## Artifacts

- `report.json` — machine-readable suite and test case results.
- `scenarios.json` — scenario group status and evidence mapping.
- `pytest.xml` — JUnit-compatible test report.
