# Anvil Analytics Workspace 2.17.0 — Engineering Report

## Outcome

**Offline implementation status: PASS.** This release converges fresh installs and upgrades on the same managed Analytics runtime, service, OpenCode runtime and canonical session. It also makes catalog discovery resumable and complete, starts stopped warehouses only for remote queries, and adds an accessible SQL/results divider.

**Live environment status: NOT CHECKED.** Local evidence does not validate the company's package mirror, a real Databricks workspace or permissions, the user's systemd session, a live OpenCode model, or browser reachability from Windows into WSL.

## Findings and corrective changes

| Finding | User impact | Correction |
|---|---|---|
| Analytics requirements were not converged with Anvil releases and could depend on whichever Python environment happened to be active. | Fresh installs and long-lived installations could have different capabilities or fail at import time. | Added `config/analytics-requirements.lock` and `scripts/analytics_dependencies.py`. DuckDB and PyArrow are installed without transitive dependency resolution into a content-addressed, Anvil-owned Python 3.11+ environment. Exact imports and versions are validated before atomic publication; a failed replacement retains the previous environment. |
| Runtime migration could start Analytics before the target OpenCode executable was installed. | A successful config write could be followed by an unavailable or stale session and a misleading lifecycle result. | Install, reforge, upgrade and runtime migration now defer Analytics service activation until package/config/runtime ordering is complete. Lifecycle success includes the managed service health response, OpenCode health and canonical Analytics session. |
| Service state could report success without a live systemd process, and paths requiring escaping were not robust. | `MainPID=0`, unusual home paths, or a stale listener could be mistaken for READY. | Service status reports installed/enabled/active/MainPID/HTTP health separately; zero MainPID is not READY. Unit paths use systemd-specific escaping. Start/restart is idempotent and verifies health. Hosts without a user systemd manager use an Anvil-owned lock/PID process. `make analytics-dev` remains explicit foreground mode. |
| Unity Catalog table discovery requested up to 200 rows per page, omitted later pages, did not reconcile deletions, and conflated empty scopes with provider failures. | Tables beyond the first page could be missing, and users could not distinguish empty results from permission/network blockers. | Table pages are capped at 50 and all page tokens are followed. Catalogs, schemas and tables/views hydrate in bounded, resumable background phases. Scope state and progress persist, deletions reconcile atomically, provider concurrency is capped at two, and failures remain distinct from confirmed empty scopes. Table rows and column detail stay lazy. |
| Remote SQL did not consistently start a selected stopped warehouse. | A configured warehouse could be ready in the UI but reject query execution until users started it manually. | The Databricks execution path starts a selected STOPPED warehouse once, waits through STARTING/STOPPING, and returns actionable permission/timeout errors. LOCAL and AUTO-to-LOCAL do not start compute. |
| The SQL/results split was fixed-height and difficult to operate precisely. | Resizing was unavailable to pointer/keyboard users and editor dimensions could become stale. | Added an accessible, keyboard-operable separator with bounded persisted ratio, pane minimums, pointer dragging and editor reflow. UI dimensions and interaction are checked at four viewport sizes. |

The Unity Catalog page-size bound is supported by the [official List tables API reference](https://docs.databricks.com/api/uc-tables/v1/list-tables), which documents a maximum `max_results` of 50. The earlier 200-row request is the code-level cause inferred from this contract and the missing later-page behavior.

## Runtime and service contract

`make upgrade`, fresh reforge, runtime update and major migration prepare the pinned dependencies before managed config activation. Runtime migrations defer the service until the requested OpenCode executable is in place. Failed dependency preparation stops before config activation and leaves a previously supported environment available.

`make analytics` ensures one managed service is ready and prints its URL. `make analytics-dev` runs a foreground development server. `make analytics-status` reports managed service state. Inspect, doctor, capabilities and the Analytics runtime endpoint share the same local readiness view, including runtime/session and dependency status. A degraded installed default capability produces a diagnostic and points to `make upgrade` for convergence.

The isolated environment pins DuckDB 1.5.5 and PyArrow 26.0.0. PyArrow's [26.0.0 package metadata](https://pypi.org/project/pyarrow/26.0.0/) specifies Python 3.11 or newer. DuckDB's [1.5.5 package metadata](https://pypi.org/project/duckdb/1.5.5/) specifies Python 3.10 or newer and no external package dependencies; the Anvil environment uses the stricter shared Python floor. Local certification tests the exact locked versions without accessing an external package source.

## Catalog and query behavior

Catalog metadata refreshes roots, schemas and tables/views in the background; cached metadata is shown first. Progress and per-scope state survive restart, and a retry resumes unfinished/failed scopes. Discovery is metadata-only; data rows are still fetched on demand. Refresh logs include structured lifecycle events and object counts without row data or secrets.

Warehouse lifecycle is reached only after query routing chooses remote Databricks SQL. Local queries and AUTO fallback remain local. Warehouse start waits for a stable RUNNING state within a bounded deadline and surfaces authorization, timeout and provider failures distinctly.

## UI evidence

The SQL/results divider supports pointer drag, Arrow Up/Down keyboard adjustment, browser-local persistence, bounded split ratios, minimum pane sizes and Monaco reflow. Mock and production markup share the interaction contract.

Browser automation checks representative Home/table/query views, active tabs and divider behavior at **1366×768, 1920×1080, 2560×1440 and 3840×2160**. The run also checks browser scales 125% and 150% at 1366×768 and 1920×1080. This is a visual regression matrix with geometry assertions; screenshots are stored under `artifacts/analytics-production-hardening/ui/` and `artifacts/analytics-active-tab-indicator/final/`.

## Verification evidence

| Check | Result |
|---|---|
| Focused runtime, service, warehouse, catalog, store and mock UI unit suites | PASS — 59 tests |
| Fresh install, 2.15→2.17 and 2.16→2.17 lifecycle, idempotency, dry run, rollback and data preservation | PASS |
| Browser geometry and interaction matrix | PASS — four viewport sizes; browser scale checks at two sizes |
| `make test` | PASS — complete offline suite; includes 95 Analytics unit tests and lifecycle integration |
| `make eval-analytics` | PASS — 93/93 checks; [certification summary](../artifacts/analytics-certification/summary.md) |
| `scripts/version_docs.py` | PASS — release documentation consistency |
| `git diff --check` | PASS |

The separate visual automation run passed tab geometry at Home, table and query widths; active Home, transaction and query tabs; multiple tabs; query-divider drag, keyboard adjustment, persistence, bounds and pane minima; and browser scales of 125%/150% at the documented sizes. Production-hardening screenshots are under `artifacts/analytics-production-hardening/ui/query-splitter/`.

Certification uses local fixtures and isolated temporary state. It does not contact a live model, workspace, credentials or package mirror. This report records offline engineering evidence; production rollout still needs validation in the target company's network and runtime environment.

## Upgrade and first use

```bash
make upgrade DRY_RUN=1
make upgrade
make inspect
make doctor
make capabilities
make analytics-status
make analytics
```

The dry run is read-only and does not need network access. A real upgrade may need the configured Python package mirror/proxy to obtain a wheel when the managed environment is not already valid. No package is installed into system or shell Python.

## Harness size

The global `config/AGENTS.md` is **3,511 bytes** (estimated 878 tokens), within its 4,200-byte budget.

## Migration source window

The 2.17 release retains Anvil 2.6.x as a supported same-major migration source, covering eleven prior minor releases. The next step outside that documented window is 2.5.x.
