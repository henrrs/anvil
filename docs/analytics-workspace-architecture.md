# Analytics Workspace architecture

Analytics is a default-installed feature package with an explicit dependency direction. It reuses the Anvil Databricks capability and the installed OpenCode runtime; it does not create a second agent, memory system, auth owner or lifecycle.

```mermaid
flowchart TB
  User --> Browser
  Browser -->|same-origin HTTP / SSE| BFF[Loopback Analytics BFF]
  BFF --> Service[Analytics application service]
  Service --> Catalog[Cached catalog and metadata hydration]
  Service --> Router[Read-only query router]
  Service --> Sessions[Analytics session manager]
  Service --> Transfer[Materialization coordinator]
  Catalog --> DBX[Shared Anvil Databricks capability]
  Router --> DBX
  Transfer --> DBX
  Router --> PyEnv[Release-pinned Analytics Python runtime]
  PyEnv --> DuckDB[Required DuckDB]
  PyEnv --> Arrow[Required PyArrow]
  Transfer --> Arrow
  Transfer --> Parquet[Private Parquet snapshots]
  Sessions --> Runtime[OpenCode 1/2 adapter]
  Runtime --> Canonical[Canonical Analytics session]
  Canonical --> Anvil[Anvil agent, skills, memory and plugin tools]
  Service --> SQLite[(SQLite WAL context store)]
  Context[Context resolver] --> Sessions
  SQLite --> Context
```

## Boundaries

| Boundary | Owns | Must not own |
|---|---|---|
| Anvil lifecycle | Managed config package, upgrade, reforge and rollback | Analytics schema or user dataset contents |
| Shared Databricks capability | Anvil-owned profile, provider/auth selection, catalog, SQL and transfer calls | Analytics UI, state or OpenCode session context |
| Analytics application | Catalog cache, query plan, coverage, materialization, context resolution and API composition | Databricks secrets or OpenCode endpoint contracts |
| OpenCode adapter | Runtime process lifecycle, generation-specific routes and session identity | Databricks auth or large data movement |
| Browser BFF | Loopback HTTP, origin validation, static assets and bounded JSON/SSE | Raw OpenCode API, shell, credential values or arbitrary file serving |

The traditional Anvil core does not import Analytics modules. Lifecycle packaging includes the feature, its runtime policy and a release-specific dependency lock. It prepares the isolated Analytics Python environment before replacing managed config, then starts the service after the target OpenCode executable is installed and validates the runtime/canonical session before lifecycle success. Analytics dependencies are required by the default Analytics local SQL/materialization capabilities but are not imported by the traditional Anvil core. Databricks scripts do not import Analytics.

## Runtime and sessions

`AnalyticsRuntimeManager` discovers the same validated OpenCode executable and starts a dedicated `serve` process in `~/.anvil/workspaces/analytics/` when needed. OpenCode 1 and OpenCode 2 details are isolated in `OpenCode1xRuntimeAdapter` and `OpenCode2xRuntimeAdapter`. The HTTP server binds to IPv4 loopback. Its startup thread warms the runtime and canonical session after the BFF is already available; runtime failure leaves the browser service alive in a degraded state.

The session titled `anvil-global-analytics` represents active analytical context. Its ID and runtime generation live in private `runtime.json`, written atomically without secrets. A filesystem lock serializes runtime/session recovery. On a missing session, Anvil recreates it and rehydrates a short context from SQLite rather than replaying history. Deep investigations use child sessions, then persist concise findings to SQLite before returning to the canonical conversation.

The canonical OpenCode session is working context, not durable memory. Losing it does not remove catalog metadata, findings, query history, operations or snapshots. Repository OpenCode sessions are isolated because the runtime uses the dedicated global Analytics workspace directory. Startup probes retry short local health requests inside a bounded deadline; service readiness includes both the OpenCode runtime and the canonical session.

Analytics prompt requests select the explicit OpenCode Models provider/model reference `opencode/gpt-6-luna`. The selected model is exposed in runtime status. Provider/model errors reach the UI; Analytics does not silently route the request to another model.

## State and optional engines

| Plane | Store | Responsibility |
|---|---|---|
| Control/context | SQLite with WAL | Catalog metadata, knowledge, query history, runtime/task sessions, operations, local-dataset identity and materialization provenance |
| Query/runtime | Release-pinned Python virtual environment under Anvil XDG data | Run the Analytics service and its exact required DuckDB/PyArrow versions |
| Query engine | Required DuckDB in-memory connection | Execute the intentionally restricted local SQL subset against Parquet |
| Transfer codec | Required PyArrow | Validate bounded Arrow chunks and read/write Parquet snapshots |
| Local data | Workspace-scoped Parquet generations, checksummed manifests and an atomic dataset-state pointer | Persist one logical copy per workspace/table independently of the OpenCode context |

SQLite migrations are versioned and transactional. Runtime identity is a separate atomic JSON file so it can be inspected without querying OpenCode's private database. Dataset paths and state are permission-restricted and reject symlinked roots/files. A dataset-state pointer records CURRENT, one PREVIOUS generation with a 24-hour expiry, and hidden STAGING operations. Shared reader locks keep a generation alive during DuckDB execution; publication, pruning and explicit removal use an exclusive lock. SQLite's local-dataset registry is repairable from the verified filesystem pointer.

DuckDB returns query data through Arrow before converting values for the API. This keeps the local query path aligned with the required PyArrow runtime and supports dates, timezone-aware and naive timestamps, decimals, binary values, nulls, arrays, maps, structs and nested combinations consistently with the transfer codec. Nested values remain structured in API results, decimal and temporal values use stable text forms, and binary values use Base64. The UI shows the logical Analytics model policy as GPT 6 Luna; provider/model identity and the no-fallback setting are available in the accessible label details and service status.

## Shared Databricks capability

Catalog, SQL warehouse discovery, warehouse start, preview, SQL and Arrow transfer operations route through `scripts/analytics/databricks.py` to the existing `scripts/databricks.py` capability. Its `ComputePort` and metadata adapter retain the existing CLI/SDK strategy and Anvil-owned auth boundary. Warehouse discovery returns sanitized display metadata and caches it briefly. Remote SQL can start a selected stopped warehouse after a user query; explicit Make local can choose an available stopped warehouse when transfer is needed. STARTING is polled without duplicate starts, and LOCAL/AUTO-to-LOCAL never starts compute. The UI never reads tokens or warehouse HTTP paths. Metadata calls do not invoke a model. Preview, SQL and materialization occur only after user intent; an agent request reaches the same capability through the bounded local tool bridge.

## Catalog metadata lifecycle

The service loads cached metadata before remote refresh. It then paginates catalogs, schemas and tables/views in bounded phases, stores each complete scope atomically, records scope state and tree progress, and removes disappeared objects and descendants on reconciliation. Unity Catalog table listing uses a page size of 50; the [List tables API](https://docs.databricks.com/api/uc-tables/v1/list-tables) caps `max_results` at 50. Provider calls have a shared concurrency ceiling of two, retryable errors use bounded exponential backoff with jitter, and service shutdown leaves tree progress pending so the next start can resume. Expanded scopes are loaded on demand if background hydration has not reached them. Table rows/previews and column detail remain lazy.

The browser talks through `HttpAnalyticsApi` to the same-origin loopback BFF. `MockAnalyticsApi` and its realistic fixtures live only in the development directory and are served by a separate static-only loopback server. The production asset allowlist and lifecycle package manifest exclude that directory.

## WSL and URL

The default URL is `http://anvil.localhost:8765`; the server accepts this host plus localhost aliases, but only on the local listener. A port override is supported. WSL browser reachability is reported as `NOT_CHECKED` by local doctor because the Windows host is outside the Linux process boundary. See the [operations guide](analytics-workspace-operations.md).
