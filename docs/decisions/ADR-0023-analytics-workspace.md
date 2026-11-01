# ADR 0023: Add a global Analytics Workspace as an optional Anvil capability

**Status:** Accepted

## Context

Anvil needs an interactive analytical workspace that reuses its OpenCode agent, Databricks authentication/capability, memory and lifecycle. A browser experience must not create a second agent, auth store, data store or runtime-specific business-logic path. The feature must be present after fresh install and normal upgrade while the established Anvil core remains usable if the feature package is absent.

## Decision

- Package Analytics by default as a separate `scripts/analytics/` application module plus a static `web/analytics/` UI.
- Expose a loopback same-origin BFF. The browser never calls OpenCode or Databricks directly.
- Reuse Anvil's shared Databricks provider/auth/SQL/transfer capability. Metadata and previews are deterministic; no LLM is involved.
- Use OpenCode as the only AI runtime, with separate V1 and V2 plugin adapters and an isolated global Analytics workspace.
- Persist a canonical working session ID separately from durable analytical knowledge. Use SQLite WAL for control/context, optional DuckDB for local SQL, and Parquet for local datasets.
- Acquire data only after explicit intent. Keep Arrow transfer in the deterministic data plane; never route large results through OpenCode.
- Keep Analytics data outside managed-config snapshots. Install/upgrade/rollback own only package files and the Anvil service unit.

## Consequences

Catalog and remote SQL work without optional local dependencies. Ask Anvil degrades if OpenCode is unavailable; local SQL degrades if DuckDB is absent; materialization degrades if PyArrow is absent. A session can be recreated from durable SQLite context. Rollback can remove the package/service without deleting analytical state or user datasets.

The OpenCode 1 and 2 plugin APIs have distinct source adapters. Their tool inputs call the same local BFF helper and shared Analytics service. The full live provider/model behavior remains dependent on the user's installed runtime, Databricks permissions and network.

Analytics does not add a model route or call a second model client. OpenCode remains the only model execution path.

## Alternatives not selected

- A second Analytics agent or LLM client would duplicate Anvil's model policy, memory and session semantics.
- Sending query results through OpenCode would couple model context to transfer volume and risk exposing large datasets.
- DuckDB as the primary state store would mix transactional control state with analytical execution.
- Requiring a separate install or manual runtime upgrade would leave existing users without the feature after `make upgrade`.
- Binding the BFF to a network interface or exposing raw OpenCode APIs would expand the local security boundary without a product need.
