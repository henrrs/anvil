# Analytics Workspace operations

## Install, start and stop

Analytics files are installed with `make reforge` and `make upgrade`; existing supported runtimes are preserved exactly. `make upgrade DRY_RUN=1` rehearses managed file changes without starting a service or changing live state.

```bash
make inspect
make upgrade DRY_RUN=1
make upgrade
make doctor
make analytics-status
make analytics
```

Open `http://anvil.localhost:8765`. Config activation writes a private systemd user unit only in the active XDG user unit directory. When systemd user mode is available, the unit starts and restarts the Analytics server. Without it, `make analytics` starts a foreground server; Ctrl-C stops that process. `make analytics-stop` stops an active Anvil systemd unit. A foreground server is stopped with Ctrl-C in its terminal.

Use `ANALYTICS_PORT=8765 make analytics` for a one-command port override or export `ANVIL_ANALYTICS_PORT` for the shell/session. The selected port is written into the Anvil-owned service unit. `make analytics-status` returns a nonzero status while the endpoint is stopped.

## Readiness and diagnosis

`make inspect` is a local structural inventory. It reports package and frontend presence, the configured URL, private workspace/state paths, whether SQLite exists, OpenCode generation/canonical ID presence and optional DuckDB availability. `make doctor` adds Analytics state to Anvil's current diagnostic without making Analytics required for the traditional core. `make capabilities` reports Catalog, SQL Workspace, Ask Anvil, Local Analytics, Materialization and service states.

Analytics status uses `READY`, `DEGRADED`, `RECOVERABLE`, `NOT_CONFIGURED` and `FAILED` where the state can be established. A stopped service is reported as stopped; the core Anvil doctor can still be healthy. The Analytics UI remains available if the OpenCode process cannot start, and Ask Anvil displays a bounded error. Cached catalog and local data are not erased when a provider is offline.

| Symptom | Meaning | Next action |
|---|---|---|
| UI is unavailable | Service stopped, port occupied or frontend missing | Run `make analytics-status`; run `make analytics` and read its short error |
| Catalog empty | No cache yet or Databricks metadata cannot be reached | Run `make databricks-setup` if needed, check `make doctor`, then use catalog refresh |
| Preview/query asks for a warehouse | Databricks SQL uses an existing warehouse; Anvil does not start compute | Choose a running warehouse by name in the UI |
| Ask Anvil degraded | OpenCode is missing, unsupported or not responding | Check `make inspect`, close conflicting runtime processes, then retry the service/chat |
| Local SQL unavailable | DuckDB is not importable in the service Python environment | Install/use DuckDB in that environment or choose `AUTO`/`DATABRICKS` |
| Materialization unavailable | PyArrow is missing, no warehouse/profile is selected, or local disk is insufficient | Check capabilities, setup Databricks, narrow the selection or free disk |
| WSL page does not open | Windows localhost forwarding/firewall policy may be unavailable | Try the same configured port on Windows localhost; host-side changes are environment-specific and are not made by Anvil |

The default Anvil-owned Databricks profile and authentication remain the only supported identity source. Run `make databricks-setup` if it has not been set up. Analytics does not log into Databricks independently, install its CLI implicitly during feature startup, or adopt an external profile.

## Runtime update and migration

`make update-runtime` and `make migrate-runtime OPENCODE_MAJOR=N` already rebuild the managed config, so the matching OpenCode 1 or 2 plugin adapter is packaged with the target runtime. The Analytics service is synced after config activation. The stored Analytics session record is checked/recovered when the service warms or the next chat is made; incompatible or missing canonical sessions are recreated and rehydrated from SQLite.

## Data and rollback

Analytics state lives outside managed OpenCode configuration and lifecycle backups. Upgrade/reforge do not copy it into snapshots. Rollback restores Anvil-owned config and removes only the Anvil-owned Analytics service unit when the target package lacks Analytics. It preserves SQLite, runtime.json, workspace files, Parquet datasets and snapshots. SQLite can be opened by a compatible later Analytics version; rollback does not downgrade user data.

## Developer UI mock

The UI-only preview is separate from the Analytics user service and can run without an Anvil installation or runtime dependencies:

```bash
make analytics-ui-mock SCENARIO=healthy
make analytics-ui-mock SCENARIO=large-catalog
```

It binds to `127.0.0.1`, serves repository static assets, and uses fixtures in `web/analytics/dev/`. It does not create or modify Analytics state, contact Databricks, or initialize OpenCode. See the [user guide](analytics-workspace.md#developer-mock-preview) for scenarios. Production install manifests omit the mock directory.

## Offline certification

`make test` runs offline Anvil regressions and Analytics contracts/lifecycle fixtures. `make eval-analytics` emits `summary.md`, `report.json`, `scenarios.json` and JUnit-compatible `pytest.xml` under `artifacts/analytics-certification/`. No live Databricks, OpenCode model, production credentials or Windows browser are used by these checks.
