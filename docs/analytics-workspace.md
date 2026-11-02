# Anvil Analytics Workspace

Anvil Analytics is a personal, global workspace for exploring Unity Catalog metadata, querying Databricks, and progressively making selected data available locally. This global Analytics Workspace is installed by default by `make reforge` and `make upgrade`; it does not depend on the current Git repository.

## Start here

```bash
make upgrade DRY_RUN=1
make upgrade
make analytics-status
make analytics
```

Lifecycle convergence prepares the release-pinned Analytics Python environment, synchronizes the managed service, starts the OpenCode runtime and canonical Analytics session, then begins a background catalog refresh. `make analytics` is an idempotent service check/start command; it reuses the managed service and prints the URL. A systemd user manager owns the service when available; systems without one use a managed single-process fallback with a private PID/lock file. Use `make analytics-dev` for an explicit foreground development process. Set `ANALYTICS_PORT=9000` on a Make invocation or export `ANVIL_ANALYTICS_PORT=9000` to use another port.

Use `make doctor` for Anvil, runtime, Databricks and Analytics status; `make capabilities` shows local availability. `make inspect` reports installed package files and private state paths without reading their contents. The Analytics service binds to `127.0.0.1` only and serves both the UI and same-origin API.

## Explore data

1. Configure the existing Anvil-owned Databricks profile with `make databricks-setup` if needed. Analytics reuses that profile and provider resolution; it does not create a second login or credential store.
2. Open the catalog. Cached catalog metadata appears immediately, then catalogs, schemas, tables and views refresh in the background. Metadata pages are bounded and cached; progress and permission failures remain visible as separate states. Search queries the local metadata cache. Column details hydrate when requested; catalog discovery never reads table rows.
3. Select a table to inspect cached metadata. Use **Preview rows** to run a user-requested sample query through a selected SQL warehouse. The SQL workspace discovers warehouses through Anvil's shared Databricks capability; choose a warehouse from the selector and refresh it when access changes. Warehouse IDs are not entered manually. If a query resolves to remote Databricks SQL and the selected warehouse is stopped, Anvil starts it once and waits for `RUNNING`; local routes never start compute.
4. Run one read-only SQL statement. `AUTO` selects local DuckDB only when Anvil proves that the current snapshot covers the source, columns and filter. Otherwise it uses the selected Databricks SQL warehouse. `LOCAL` fails clearly when coverage is incomplete; `DATABRICKS` explicitly uses the remote provider.
5. Use **Keep local** or **Update local copy** to choose selected or all columns and all rows or filtered rows. The interface does not ask you to set technical row or byte limits; Anvil applies its managed safety bounds and reports when a request exceeds them. Existing covered data is reused. A transfer does not require a previously selected running warehouse: on this explicit action, Anvil selects an available warehouse and starts it when needed. Keeping all columns requires explicit confirmation. Anvil checks available disk space, shows acquisition phases, fetches bounded Arrow chunks directly to the local data plane, validates them, writes Parquet, and switches the current copy only after success.
6. Ask Anvil about the current table, selected columns, SQL and small preview context. Responses use safe Markdown and the explicit OpenCode Models selection `opencode/gpt-6-luna`; a provider/model failure is shown without a silent fallback. Deep investigation creates a child OpenCode session and distills a compact result into the durable Analytics context store.

Home shows one local entry per workspace/table with its row and column coverage, size and update time. The table action reads **Keep local** when no copy exists, **Update local copy** when the copy needs attention, and **Local ✓** when it is current. A new request reuses broader column coverage for a projection and full-row coverage for a provably contained filter. Updates stage a replacement before activation; the prior copy stays available for 24 hours. Use **Remove local copy** in Home or the table's Local data tab to delete Anvil's verified local files. The confirmation states that the Databricks table is not changed.

The UI includes a recent-work Home, closable table and query workspaces, Catalog search with All/Favorites/Local filters, table details, SQL, Ask Anvil, local coverage and materialization progress. Query execution progress appears in Results, and Ask Anvil shows the selected GPT 6 Luna policy beside the conversation. Markdown tables use a horizontally scrollable, keyboard-accessible region and untrusted model output is rendered as text rather than HTML. Catalog and Ask Anvil panels can be resized or collapsed. The SQL editor/results divider supports pointer dragging and Arrow Up/Down, preserves a bounded ratio in browser-local storage, and maintains usable minimum heights. Layout and the selected warehouse ID are stored only in browser-local preferences. It has no third-party browser assets. Request and response limits are described in the [data-plane guide](analytics-workspace-data-plane.md).

See the [Local Data Intelligence engineering report](analytics-workspace-local-data-intelligence-report.md) for generation safety, coverage rules, model policy, validation evidence and remaining limits.

## Developer mock preview

For frontend work on a machine without Anvil, OpenCode or Databricks, start the static mock preview from the repository:

```bash
make analytics-ui-mock
make analytics-ui-mock SCENARIO=degraded
```

Open the printed `http://127.0.0.1:8766/dev/` URL. Visual scenarios include `home-populated`, `table-remote`, `table-local`, `query-results`, `ask-anvil`, `large-catalog`, `active-operation`, and `degraded`. Provider edge cases remain available as `offline`, `materializing`, `single-warehouse`, `no-warehouses`, and `warehouse-disappeared`. The preview serves local static files only and uses a development-only `MockAnalyticsApi`; it does not start the Analytics BFF, OpenCode, Databricks, or model requests. `SCENARIO` defaults to `healthy`, and `ANALYTICS_PORT` can override the preview port. Stop the server with Ctrl-C.

With Firefox and geckodriver installed, run `python3 scripts/analytics_ui_visual_check.py` to check the four principal views and query splitter at 1366×768, 1920×1080, 2560×1440, and 3840×2160. Splitter checks cover pane bounds/minimum sizes, pointer and keyboard resizing, and ratio persistence after reload. The script also checks Catalog favorites and local filters, icon rendering, panel collapse, tab overflow, the health details panel, and effective 125%/150% display scaling. Review the query splitter PNGs in `artifacts/analytics-production-hardening/ui/query-splitter/`; tab-indicator screenshots remain under `artifacts/analytics-active-tab-indicator/final/`. This local visual check is separate from `make test` because the offline test suite does not require a browser.

The mock source is kept under `web/analytics/dev/`. Lifecycle packaging and the production static server exclude that directory; the installed UI always uses `HttpAnalyticsApi` and the local same-origin Analytics BFF.

## Data and degradation

Private state is under `~/.anvil/analytics/`; the global workspace is `~/.anvil/workspaces/analytics/`. SQLite WAL stores metadata, query history, knowledge, operations and session identity. Local datasets are stored separately as Parquet snapshots. These locations are outside the managed OpenCode config and Anvil lifecycle snapshots. An Anvil rollback can remove the installed feature package and service unit while preserving the user's Analytics state and data.

OpenCode and Databricks are optional for different parts of the feature. Without OpenCode, cached catalog browsing, remote SQL and local SQL can still work; Ask Anvil reports degraded. Without a Databricks profile or workspace access, cached browsing and covered local SQL remain available. DuckDB and PyArrow are required Analytics dependencies, installed by Anvil into a release-pinned isolated Python runtime. If a required wheel cannot be downloaded or validated, lifecycle activation fails before replacing the supported config; use the configured package mirror/proxy and retry `make upgrade`. Do not install them manually into a system Python.

In WSL, use the Windows browser at `http://anvil.localhost:8765`. The app does not require a WSL IP or hosts-file entry. `make doctor` reports host-side browser reachability as `NOT_CHECKED`, because only the Windows host can validate its browser route. Microsoft documents Windows-to-WSL access through localhost forwarding; [WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking) describes the host forwarding behavior.

## Anvil tools

Ask Anvil can call bounded tools for cached catalog search, describe/preview, read-only query and route explanation, local coverage, materialization, metadata/local refresh, profiling, lineage, local query history and bounded remote/local comparison. OpenCode 1 and 2 use separate plugin adapters. The materialization tool requires OpenCode user approval; a full-table copy also requires explicit confirmation in the request. Tools call the local BFF and shared Anvil Databricks capability.

## Certification

```bash
make eval-analytics
```

This runs offline fixtures and writes `summary.md`, `report.json`, `scenarios.json` and JUnit-compatible `pytest.xml` under `artifacts/analytics-certification/`. `make test` runs the Analytics contracts and lifecycle regressions as part of the full offline suite. Neither command downloads packages, contacts a live Databricks workspace or model provider; the certification summary states the live checks it cannot establish.

See [architecture](analytics-workspace-architecture.md), [operations](analytics-workspace-operations.md), and [data plane](analytics-workspace-data-plane.md).
