# Analytics Local Correctness and Recovery

## Query routing and coverage

`LOCAL` and `AUTO` first compile a conservative single-table query into `QueryRequirements`. The requirements describe the referenced columns, row predicate, aggregates, grouping, distinctness, ordering and row limit. The coverage decision is made against the selected workspace's current local snapshot before asking Databricks for warehouse state.

`LOCAL` never falls back to a remote query. `AUTO` selects DuckDB when the current snapshot proves the requested data is complete; otherwise it may select Databricks. A missing warehouse therefore does not prevent a covered local query. Joins, CTEs and unsupported expressions remain remote-required. Aggregate queries such as `COUNT(*)`, `COUNT(column)`, `SUM`, `AVG`, `MIN`, `MAX`, `GROUP BY`, `DISTINCT`, `ORDER BY` and `LIMIT` are evaluated as the original SQL against a verified DuckDB snapshot.

Local readiness checks three views of the data: persisted coverage metadata, the physical Parquet schema read through PyArrow, and the schema DuckDB exposes. A mismatch marks the dataset invalid; an unavailable independent schema reader requires reconciliation. Invalid metadata is not reported as a successful `Local` state.

## Materialization lifecycle

An operation records its worker instance, process, start time and heartbeat. The service refreshes the heartbeat while work is active and enforces one process-held lock per workspace/table. On startup, persisted nonterminal work from a prior service process is marked `FAILED` with a structured reason. Recovery removes only the exact operation's staging directory and leaves the published `CURRENT` snapshot intact.

Cross-process resume is intentionally unsupported. **Retry** creates a new operation ID and a fresh plan; it never resumes old chunk or worker state. Cancellation signals the active worker, asks the provider to cancel when possible, then cleans staging after the worker exits. Removing a local copy takes the same table lock as materialization, so it cannot race an active writer. Removal affects Anvil's local generations and local coverage record; catalog metadata, favorites, query history and remote tables remain separate.

## Analytics service and Databricks trust

The generated systemd unit and fallback process receive only the explicit CA path allowlist: `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE` and `SSL_CERT_DIR`, and only when the paths are readable. The fallback service does not inherit the caller's complete environment. Proxy credentials, cloud tokens and unrelated environment variables are not copied into the unit or process.

Databricks status reports configuration, authentication, TLS trust, workspace reachability and warehouse discovery separately. Health uses the last provider result and does not probe the network from a status read. Local SQL, local snapshots and catalog views are not gated by Databricks status.

## Ask Anvil model resolution

The logical policy is `anvil-analytics`, with Luna 6 preferred through GitHub Copilot and no fallback. Before a prompt, the adapter reads OpenCode's `/provider` catalog using a 16 MiB response ceiling (other runtime requests retain their 2 MiB limit). It requires the preferred provider to be connected and resolves a matching Luna 6 model entry using the IDs and names returned by the runtime. It sends the exact returned `providerID` and `modelID` in the prompt request.

Provider discovery failures return `PROVIDER_DISCOVERY_FAILED`; a disconnected provider returns `PROVIDER_UNAVAILABLE`; a connected provider without the requested model returns `MODEL_UNAVAILABLE`. None of these cases dispatches an unvalidated pair or silently selects another model. The canonical Analytics session remains reused for normal questions; deep investigations use a child session.

The UI displays the logical model policy and updates the compact badge with the validated provider/model during a request. The `/api/runtime` status includes the last successfully resolved model without probing the provider catalog.

## Service actions and UI feedback

Removing a local dataset is a `DELETE /api/datasets/<dataset-id>` action. Cancellation and retry are no-body `POST` actions. Other API requests that require JSON continue to validate their body normally. Local-copy form validation is shown in the dialog; selecting all columns does not add a generic confirmation step. A retry action appears for failed or cancelled operations and creates a fresh operation.

The Home operations list reports phase, start time, last activity and failure reason. Table tabs remain navigable while a materialization runs; only the conflicting local-copy action is disabled.

## Validation boundaries

Automated query tests use a fake local engine when DuckDB/PyArrow are absent. Those tests validate routing, requirement extraction, SQL rewriting and fail-closed schema behavior; they do not certify execution against native Parquet files. A real Ask Anvil run also requires a connected GitHub Copilot provider that exposes Luna 6 in the active OpenCode `/provider` catalog.
