# Analytics Local Data Intelligence — Engineering Report

## Outcome

The Analytics Workspace now treats a remote table as one logical local copy and shares conservative coverage decisions between AUTO query routing and explicit materialization. Updates are built as immutable generations, validated before publication, and retain one previous generation for a bounded rollback window. The workspace also has clearer local-copy, query-progress and Ask Anvil interactions, with an explicit Luna model policy.

## Implementation results

1. **Previous Local Data model.** Local materializations were represented as per-table snapshots and operation records. Different projections could appear as separate materializations, while the UI had no first-class logical table copy.

2. **Logical LocalDataset model.** A stable ID is derived from the selected workspace identity and case-normalized `catalog.schema.table`. The SQLite control store persists one row per logical dataset, including column and row intent, schema/source identity, freshness, current/previous generation references, row count and size.

3. **Legacy reconciliation.** Pre-workspace-scoped data is considered only when its manifest proves it belongs to the selected workspace. Listing reconciles legacy and scoped roots to one visible row, prefers the broader verified copy, and prefers the scoped root on equal coverage. Ambiguous or invalid copies are not promoted. Explicit removal cleans only generations whose manifests match that workspace and table.

4. **LocalCoverage representation.** Coverage intent remains `ALL` or `SELECTED` columns and `FULL` or `FILTERED` rows. The manifest retains selected columns, physical columns, predicates, schema identities, source version, freshness, generation identity, row count and size. SQLite schema version 4 adds the logical dataset registry.

5. **Coverage planner rules.** `LocalCoverageService` evaluates table identity, requested and predicate columns, row containment, schema and available source version. The shared planner returns reuse/projection/filter, refresh or rematerialize decisions. Unsupported SQL or predicates stay conservative.

6. **AUTO integration.** AUTO queries use the same coverage service while holding a shared generation lock. A query routes local only when its supported single-table shape and all required columns and rows are covered. Otherwise it routes remote with an explanation; it does not create or update a local copy.

7. **Materialization planner integration.** Explicit acquisition uses the same coverage decisions as AUTO. A broad copy can serve a narrower projection or filter; a partial copy expands through a replacement generation when it cannot serve the request.

8. **Column coverage.** `ALL` remains semantic intent rather than only a saved list of current names. A remote schema change makes an ALL copy stale. For SELECTED intent, an unrelated new column does not invalidate the copy; removed selected columns or changed selected types do.

9. **Row coverage.** Full-row copies cover narrower filters. Filtered copies cover only predicates that the conservative containment checker can prove. Predicate columns are included in the physical transfer even when they are not part of the visible projection.

10. **Freshness behavior.** Coverage and freshness are separate. When source version or schema metadata is available, changes are reported as stale data or stale schema. If the provider cannot verify freshness, the result remains `UNKNOWN`; Anvil does not claim that an unverified copy is current.

11. **Generation lifecycle.** Materialization writes to STAGING while CURRENT remains immutable. Arrow and Parquet output, checksums, schema, row count, size and manifest are validated before a locked, atomic pointer switch. Queries hold shared locks while reading; publication and cleanup use exclusive locks.

12. **24-hour retention.** The previous CURRENT becomes the single PREVIOUS generation after a successful switch. PREVIOUS expires after 24 hours. A later switch replaces the old PREVIOUS. Cleanup validates ownership and never evicts CURRENT; terminal staging state can be pruned safely.

13. **Remove local copy UX.** The table and Local Data views expose one “Remove local copy” action with a confirmation that local Anvil files are removed and the remote Databricks table is unaffected. Removal is rejected while an update is active and does not delete catalog metadata, favorites or unrelated state.

14. **Warehouse behavior.** “Keep local” is not disabled just because a warehouse is stopped. The backend owns warehouse discovery/start when a remote transfer needs it; local reuse does not start a warehouse. Acquisition remains explicit.

15. **Arrow transfer path.** Databricks result chunks are downloaded as Arrow IPC through the transfer adapter, checked against declared lengths and limits, then converted by PyArrow to compressed Parquet files. Chunk checkpoints support safe resume without repeating completed transfers.

16. **Storage responsibilities.** Parquet is durable local table data. DuckDB is an in-memory query engine that reads the active Parquet files. SQLite holds metadata, coverage, operations and control state; it is not the table data store.

17. **Type compatibility.** DuckDB results are consumed through Arrow to avoid runtime timezone conversion dependencies. The API serializer preserves nulls, nested lists/maps/structs, timezone-aware and naive timestamps, dates, decimals and binary values (Base64). The pinned certification matrix passed with DuckDB 1.5.5 and PyArrow 26.0.0.

18. **Query progress UX.** Query status and progress are shown in Results, next to the result surface, with route, latency and human-readable execution phases. Cancellation and terminal states are reflected without exposing operation identifiers.

19. **Ask Anvil resizing.** The assistant pane can be resized with pointer input and keyboard controls, while retaining usable bounds across the tested desktop sizes. The composer supports a larger multiline prompt area.

20. **Markdown rendering.** Assistant replies render a safe Markdown subset and GFM tables. Raw HTML is rendered as text; links are restricted to safe protocols. Tables use a horizontally scrollable, keyboard-accessible region for narrow panels.

21. **Activity and streaming.** Ask Anvil reports operational states such as preparing context, requesting a response and receiving output. The UI shows activity without exposing chain-of-thought. Mock streaming preserves paragraph breaks and the model response completes before the visual assertion.

22. **Canonical session.** Analytics continues to reuse its dedicated canonical OpenCode session. Durable Analytics context remains in the existing context store, separate from transient session history. Deterministic catalog, local data and query operations bypass the model.

23. **AnalyticsModelPolicy.** A logical `anvil-analytics` policy selects provider `opencode`, disables silent fallback, and separates the user-facing name from the provider/model selector. The resolved policy is available in service status and UI.

24. **Luna 6 resolution.** The initial policy displays **GPT 6 Luna** and selects `opencode/gpt-6-luna`. Provider/model failures are shown to the user; Anvil does not silently switch models.

25. **Future model routing.** Callers depend on the logical policy boundary and selector object, so task-based routing or multiple profiles can be added without changing the Analytics conversation contract.

26. **Tests added/updated.** New tests cover logical dataset listing/removal, coverage response metadata, generation and coverage behavior, the Arrow→Parquet→DuckDB type matrix, and current schema migration. Lifecycle integration expectations now follow the current Analytics schema version.

27. **Responsive/accessibility validation.** The browser visual check passed at 1366×768, 1920×1080, 2560×1440 and 3840×2160, with browser scale checks at 125% and 150%. It exercises local-copy views, acquisition dialogs, query progress, Markdown tables, assistant resizing, keyboard behavior and minimum pane bounds. Evidence: [Local Data view](../artifacts/analytics-active-tab-indicator/final/local-copy-1920x1080.png), [Ask Anvil Markdown table](../artifacts/analytics-active-tab-indicator/final/ask-anvil-markdown-table-1920x1080.png), [query progress](../artifacts/analytics-active-tab-indicator/final/query-progress-1920x1080.png), [responsive screenshots](../artifacts/analytics-active-tab-indicator/final/) and [query splitter screenshots](../artifacts/analytics-production-hardening/ui/query-splitter/).

28. **Full regression.** `make test` passed. The Analytics suite ran 131 tests with one skip; lifecycle, offline OpenCode 1/2, Databricks fakes, Anvil communication/evaluation and native stats checks passed. The separate focused run passed 32 dataset, query/materialization and lifecycle tests. `git diff --check`, JavaScript syntax checks, Python compilation and the pinned Arrow/Parquet/DuckDB type test passed.

29. **Remaining limits.** The certification was offline. It did not contact a live Databricks workspace, start a real warehouse, transfer production data, or call a live OpenCode model session. Provider authorization, real workspace permissions, network behavior and remote model availability still require validation in the target environment. Freshness remains `UNKNOWN` when the provider cannot supply reliable source metadata.

## Changed boundaries

The implementation extends the existing Analytics coverage service, materialization transfer, SQLite context store, query router and canonical session. It does not add a second state store, query engine, runtime manager, cost-intelligence feature or implicit local materialization policy.
