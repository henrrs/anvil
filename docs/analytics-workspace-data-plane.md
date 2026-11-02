# Analytics Workspace data plane

The control plane chooses work and records evidence; the data plane performs deterministic acquisition and query execution. Large result sets do not pass through OpenCode or an LLM.

```mermaid
flowchart LR
  Intent[User intent or explicit SQL] --> Plan[Read-only planner and coverage]
  Plan -->|AUTO: exact local coverage| DuckDB[DuckDB over Parquet]
  Plan -->|Remote query or uncovered data| Shared[Shared Databricks capability]
  Plan -->|Keep or update local copy| Acquire[Explicit acquisition plan]
  Shared -->|bounded result| UI[Analytics UI]
  Acquire --> Statement[SQL statement / Arrow transfer]
  Statement --> External[Databricks Arrow result links]
  External --> Verify[Download, verify chunks and limits]
  Verify --> Staging[Private staging Parquet snapshot]
  Staging --> Commit[Atomic CURRENT/PREVIOUS pointer publication]
  Commit --> DuckDB
  Plan --> SQLite[(SQLite query and operation history)]
  Commit --> SQLite
```

## Query routes

Every route accepts one read-only SQL statement. Anvil rejects mutation words, multiple statements, comments and unsupported characters before the provider call. The remote result is capped at 100 rows and 1,000,000 serialized bytes. Query history stores SQL, a fingerprint, actual route, latency, rows/bytes and success/error state in SQLite.

- **AUTO** uses local DuckDB only for a single-source query in Anvil's deliberately small provable subset and only if snapshot coverage matches source, projection and normalized filter. Otherwise it falls back to Databricks.
- **LOCAL** fails if DuckDB is unavailable or exact coverage cannot be proven; it never silently sends a requested local query remotely.
- **DATABRICKS** uses the existing shared provider and the explicitly selected SQL warehouse. If it is STOPPED, Anvil sends one start request and polls through STARTING/STOPPING until RUNNING or a bounded timeout; a permission denial gives the user local/other-warehouse/manual-start choices. A LOCAL route never starts compute.
- **Explain** reports the planned route, coverage and reason without executing SQL.
- **Compare** executes the same bounded query locally and remotely. It reports equality only when both complete bounded result sets and column sets are available; truncation produces `INCONCLUSIVE`.

The local parser intentionally defers joins, CTEs, unions, grouping, windowing and expressions outside the supported subset to the remote route. This limits what Anvil can prove; it does not claim all SQL can run locally.

## Catalog and preview

Catalog/schema/table metadata uses the shared Unity Catalog capability with pagination and atomic cache updates. On service startup, the browser can read cached state immediately while bounded background hydration refreshes catalogs, schemas, and tables/views. Each scope has persisted NOT_LOADED/PENDING/LOADING/READY/EMPTY/FAILED state, attempt time, reason code and object count; the tree also persists its phase and completed/total scope progress. Provider calls are bounded to two concurrent requests and retry only retryable provider failures with jitter. Service cancellation leaves the tree pending for a later restart. A user-expanded scope is fetched immediately if background work has not reached it. The Unity Catalog tables API has a maximum page size of 50, so table listings request at most 50 objects per page and follow the continuation token. Refresh replaces each complete scope atomically and removes disappeared catalog/schema/table descendants. Permission failures become browse-only state, never EMPTY. Columns hydrate only when requested. SQL warehouse listing and detail use the same existing shared capability, with a short-lived in-memory cache and response fields limited to ID, name, state, type and size. Preview is a separate user-requested remote read capped at 100 rows; it does not create a snapshot or imply local coverage.

Metadata failure keeps the prior cache and reports browse-only status. `search_catalog` searches all cached levels locally. It does not issue a remote wildcard scan or invoke an LLM.

## Make local and transfer

An acquisition request includes a fully-qualified source table, selected or all columns, all rows or an optional supported filter, source version, principal and service-managed safety bounds. The interactive UI hides technical limits and uses a ceiling of 1,000,000 rows and 1 GiB; direct API/tool requests default to 100,000 rows and 512 MiB. These are hard acquisition limits: if the result exceeds them, Anvil fails the operation and preserves the active local copy rather than publishing a truncated dataset. Keeping all columns requires explicit confirmation, and OpenCode materialization tools require an additional user approval prompt. Free disk space is checked before transfer.

Keep local and Update local copy are available without a previously selected running warehouse. Anvil first plans against the current local copy. It reuses a broader copy for a narrower projection or a contained filter. If a transfer is required, it selects a running warehouse when available; otherwise it starts an available stopped warehouse because the user explicitly requested local acquisition. This does not start a warehouse merely to browse the catalog or inspect local data. The UI reports warehouse startup, query execution, Arrow download, Parquet writing, validation and activation as distinct observable phases.

The shared Databricks capability submits one read-only statement and returns bounded Arrow result metadata/links. Analytics downloads those links directly to its private data plane using a no-redirect client; result bytes are not sent through the model. Each chunk has checksums and is checkpointed for resume. Repeated chunks, corrupt payloads, excessive rows/bytes, incomplete manifests or disk failure stop publication.

Chunks are converted to Parquet under a private hidden staging generation. Anvil validates files and manifest, then atomically publishes one logical dataset pointer only after all chunks succeed. The current generation remains active on failure. A successful update retains one previous generation for 24 hours; readers hold a shared generation lock, and cleanup/deletion waits for those readers to finish. Expired previous generations and terminal staging folders are pruned on dataset listing or successful publication. Duplicate plans are idempotent; force-refresh creates a distinct operation. Interrupted transfers can resume by operation ID; unknown Databricks submission state requires a new explicit operation rather than risking duplicate acquisition.

## Coverage and consistency

Coverage refers to one logical workspace/table copy, its recorded source version, schema identity, selected/all-column intent, full/filtered-row intent and completion state. Partial or malformed copies are never reported as complete. AUTO and explicit acquisition use the same conservative coverage planner: full-column data can serve a projection, full-row data can serve a contained simple filter, and numeric/date ranges are reused only when implication can be proven. Predicate columns must also be present in the local copy. Unsupported predicates, missing columns, incompatible selected-column types, all-column schema drift, other workspace identities and partial row coverage fall back to Databricks or require a new acquisition. A selected-column copy may remain usable after unrelated source columns are added only when the selected column types are still proven; freshness is then unknown. Table metadata version can be unavailable, in which case freshness is reported as unknown; users can refresh metadata and explicitly update their local copy when data needs to be current.

SQLite stores one local_datasets row per workspace/table, including acquisition intent, source/schema identities, freshness, current/previous pointers and size. Individual generation identifiers and transfer operation identifiers stay internal to the UI. Home and the table's Local data tab expose one logical copy and a confirmed Remove action that deletes verified local files for the selected workspace while preserving unrelated or unrecognized files. The confirmation explicitly says that the remote Databricks table is not changed. Existing table-only copies are reused only when their manifest proves the workspace identity; duplicate legacy copies are reconciled by selecting the broadest healthy copy.

Refresh metadata updates catalog state only. Refresh local repeats or resumes a materialization. Neither operation silently downloads all data. A local copy is an explicit acquisition at its recorded point; it is not a live mirror of Databricks.

## Lineage and profiling

`profile_table` derives null/distinct/min/max summaries from a bounded preview of at most 100 rows and does not return the raw sample in its profile response. `get_lineage` issues a bounded read against `system.access.table_lineage`; availability depends on workspace permissions and system-table data. Databricks describes this table as observed lineage events with limited coverage and retention, so absence of a row is not proof that no dependency exists. See [Databricks lineage system tables](https://docs.databricks.com/aws/en/admin/system-tables/lineage).

## Storage separation

| Data | Location | Format |
|---|---|---|
| Runtime identity and canonical session ID | `~/.anvil/analytics/runtime.json` | Atomic JSON, no secrets |
| Catalog, findings, queries, sessions and operations | `~/.anvil/analytics/context.db` | SQLite WAL |
| Transfer staging and committed snapshots | `~/.anvil/analytics/datasets/` and `snapshots/` | Arrow during transfer, Parquet after commit |
| Dedicated OpenCode directory | `~/.anvil/workspaces/analytics/` | OpenCode-owned workspace files |

All Analytics user data is outside managed OpenCode config and Anvil backups/rollback. Files and directories are private to the current OS user. DuckDB and PyArrow are required feature dependencies in a content-addressed, release-pinned Python environment prepared and import-validated by Anvil before service activation. The exact lock is installed with the managed package; neither package is installed into the system Python.
