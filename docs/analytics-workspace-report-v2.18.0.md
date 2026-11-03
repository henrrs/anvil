# Anvil 2.18.0 Analytics Engineering Report

## Scope

This release aligns local query routing with proven data coverage, verifies local physical schema independently, recovers abandoned materializations safely, preserves TLS trust in the managed Databricks service, repairs local-copy actions and form feedback, and resolves Ask Anvil through the active OpenCode provider catalog.

## Implemented behavior

- `QueryRequirements` describes the data a query needs. LOCAL/AUTO coverage is checked before remote provider discovery; full local coverage runs without Databricks.
- Local data readiness compares the manifest/coverage schema, PyArrow Parquet schema and DuckDB schema. Inconsistent copies fail closed.
- Materialization status records worker ownership and heartbeats. Startup converts stale work to structured failures, removes only operation staging, and preserves CURRENT. Retry uses a new operation ID; cross-process resume is not performed.
- A per-table lock coordinates writers and local-copy removal. DELETE and bodyless action routes are supported. UI validation, progress and retry details are shown inline or in the Home operations list.
- The managed service receives only readable CA path variables from a fixed allowlist. Databricks configuration, authentication, TLS, workspace and warehouse discovery are distinct status fields.
- Ask Anvil resolves Luna 6 from a connected GitHub Copilot provider response. Exact IDs are runtime-derived; discovery, provider and model failures are distinct; no fallback is dispatched.

## Verification

`make test` completed successfully: all offline Anvil checks passed, including 152 Python tests (one skipped), Analytics materialization/query/API/UI coverage, the full lifecycle integration matrix, and both OpenCode runtime generations. To keep the bounded engineering gate below its 600-second per-check ceiling, the same test harness also exposes `make test-core` and `make test-lifecycle`; both phases passed independently. The lifecycle matrix passed the large external config plan and upgrade case that previously failed from an oversized argument list.

The tests use local fakes for provider, filesystem, Parquet and service scenarios. They validate routing/failure semantics and operation recovery without contacting a live workspace or model provider.

## Environment limits

Offline tests cannot establish access to the real Databricks workspace or a live GitHub Copilot account. The development CLI on this machine lists OpenAI as authenticated and reports GitHub Copilot as an unknown provider. The checkout's system Python does not include DuckDB or PyArrow; native execution claims require the prepared Analytics environment. No live model or workspace request is inferred from fixtures.
