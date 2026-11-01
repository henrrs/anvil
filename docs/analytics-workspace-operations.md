# Analytics Workspace operations

## Install, start and stop

Analytics files and runtime dependencies are converged by fresh `make reforge`, `make upgrade`, and explicit runtime migration. Existing supported OpenCode runtimes remain on their selected major unless a runtime migration is requested. `make upgrade DRY_RUN=1` reports managed-file changes, dependency preparation, service actions, OpenCode/canonical-session bootstrap, and metadata refresh without changing files, the Python environment, systemd, runtime state or catalog state.

```bash
make inspect
make upgrade DRY_RUN=1
make upgrade
make doctor
make analytics-status
make analytics
```

Lifecycle activation writes a private systemd user unit only in the active XDG user unit directory, reloads the manager, enables/starts the unit, and waits for service, OpenCode runtime and canonical session readiness. `make analytics` performs an idempotent reuse/start check and prints `Anvil Analytics READY` plus the URL. If no systemd user manager is available, Anvil uses a managed background process with one port owner; `make analytics-dev` is the explicit foreground mode. `make analytics-stop` stops only the Anvil-owned service.

Use `ANALYTICS_PORT=8765 make analytics` for a one-command port override or export `ANVIL_ANALYTICS_PORT` for the shell/session. The selected port is written into the Anvil-owned service unit. `make analytics-status` returns a nonzero status while the endpoint is stopped.

## Readiness and diagnosis

`make inspect`, `make doctor`, `make capabilities`, and `/api/runtime` use the same structured Analytics readiness snapshot. Inspect reports package/runtime artifacts, service unit installation/enabled/active/MainPID/health, OpenCode and canonical session state, DuckDB/PyArrow imports, and cached catalog counts/hydration. Doctor warns and exits with its warning code when an installed default Analytics capability is degraded, with `make upgrade` as the supported runtime-dependency recovery. Analytics remains outside traditional core dependencies. Capabilities distinguishes catalog browsing from remote SQL, Ask Anvil, local SQL and materialization availability.

Service readiness requires installed code, an enabled/active unit (or managed fallback process), a live MainPID and a responding health endpoint. Analytics API readiness additionally requires the OpenCode runtime and canonical session; dependency and catalog state are reported separately. If OpenCode cannot start, the UI can still show a bounded degraded state. Cached catalog and local data are not erased when a provider is offline.

| Symptom | Meaning | Next action |
|---|---|---|
| UI is unavailable | Service stopped, port occupied or frontend missing | Run `make analytics-status`; run `make analytics` and read its short error |
| Catalog is loading | Metadata has not been hydrated or a background refresh is running | Check the persisted tree progress; expand catalogs/schemas for prioritized refresh |
| Catalog browse-only or failed | Permission/provider failure; not an empty catalog | Review the structured reason, check `make databricks-setup`, then retry metadata refresh |
| Preview/query asks for a warehouse | Remote Databricks SQL needs an explicitly selected warehouse | Choose a warehouse by name; remote queries start a stopped selection and wait, subject to workspace permission |
| Ask Anvil degraded | OpenCode is missing, unsupported or not responding | Check `make inspect`, close conflicting runtime processes, then retry the service/chat |
| Local SQL or materialization unavailable | Managed dependency runtime is missing/unhealthy, provider access is unavailable, or disk is insufficient | Run `make upgrade` to restore release-pinned DuckDB/PyArrow; review provider and disk readiness. Do not use system `pip` as a recovery path |
| WSL page does not open | Windows localhost forwarding/firewall policy may be unavailable | Try the same configured port on Windows localhost; host-side changes are environment-specific and are not made by Anvil |

The default Anvil-owned Databricks profile and authentication remain the only supported identity source. Run `make databricks-setup` if it has not been set up. Analytics does not log into Databricks independently, install its CLI implicitly during feature startup, or adopt an external profile. Warehouse start calls are made only after the query router selects remote Databricks execution; LOCAL and AUTO-to-LOCAL routes never start compute.

## Runtime update and migration

`make update-runtime` revalidates the existing Analytics dependency environment and service after the same-major OpenCode update. `make migrate-runtime OPENCODE_MAJOR=N` prepares the target profile/dependencies, installs the requested runtime, then activates the Analytics service against that runtime. The matching OpenCode 1 or 2 plugin adapter is packaged with the target runtime. Service readiness waits for the canonical `anvil-global-analytics` session; missing/stale sessions are reused, recovered or recreated and rehydrated from SQLite under a process lock.

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

`make test` runs offline Anvil regressions and Analytics contracts/lifecycle fixtures. `make eval-analytics` emits `summary.md`, `report.json`, `scenarios.json` and JUnit-compatible `pytest.xml` under `artifacts/analytics-certification/`. The separate Firefox geometry run emits screenshots under `artifacts/analytics-production-hardening/ui/query-splitter/`. Offline checks use fake providers and do not install/download wheels or contact live Databricks, an OpenCode model, production credentials or a Windows browser.
