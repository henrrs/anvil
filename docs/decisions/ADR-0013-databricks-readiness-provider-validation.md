# ADR-0013: Treat Databricks readiness as validated runtime evidence

## Status

Accepted for Anvil 2.6.0.

## Context

Anvil setup and later workspace operations could disagree. In the repository baseline, setup called `current-user` but then computed readiness from installed provider inventory; it did not validate `clusters list` or `warehouses list` before promotion. The baseline status path did make those calls, but after catching a provider error it recomputed overall readiness from provider inventory and successful identity, so a timeout could still coexist with `READY`. Runtime also repeated remote profile and identity discovery before a requested operation and gave metadata requests a generic 20-second CLI budget. Provider installation, authentication, workspace reachability, provider transport, and capability permissions are separate properties.

The baseline inventory-only readiness calculation was reproduced with the pre-existing pure resolver and returns `READY` for an installed CLI plus `auth_valid=true`, without making a resource request. The matching controlled executable scenario then establishes an Azure CLI session, succeeds at identity validation, and hangs on the actual CLI cluster-list call. The corrected setup path uses that same executable through the production wrapper, receives the bounded timeout, and refuses promotion. A second fixture confirms that successful setup state reloads in a clean process and performs status plus cluster discovery through the persisted Anvil profile.

## Decision

- Use one readiness evaluator for setup, status, and runtime outcome persistence. Validate the core probes through the same production provider adapter used by later Anvil sessions.
- Advance through CONFIGURED, AUTHENTICATED, WORKSPACE_VALIDATED, PROVIDER_VALIDATED, CAPABILITIES_DISCOVERED, and READY only when each stage has explicit evidence.
- Define core readiness as a validated current-user response plus successful `clusters list` and `warehouses list` operations through the same CLI/SDK adapters used at runtime. Empty collections are successful. Running compute and SQL/system-table access are optional capabilities.
- Stage a first-use config and promote it only after readiness validation; retain a prior active config when a later revalidation fails.
- Persist schema-3 validation timestamps, selected provider, probe, capability counts, and safe error metadata. Reject persisted READY state that lacks core evidence. Continue lazy migration for earlier state schemas.
- Revalidate status/doctor when explicitly invoked and mark cached local capability evidence stale after 15 minutes. Runtime failures update evidence and recompute state through the same evaluator.
- Permit fallback only for explicit provider-specific failures. Stop for shared auth/network failures, permission denials, invalid arguments, and unknown execution failures. Do not replay SQL or remote Python after dispatch.
- Use bounded, operation-specific timeouts and a shared process runner that drains stdout/stderr, limits aggregate output, and terminates process groups on timeout.
- Keep the agent-facing resource command grammar consistent and test the command examples in the Databricks skill against the parser.

## Consequences

- `READY` now means a fresh session can use the persisted Anvil profile for core read-only workspace discovery.
- `make doctor` performs read-only Databricks requests when a profile is configured; without a profile it performs no workspace call. `make capabilities` remains local and distinguishes support, current availability, and verification.
- A permission denial can leave overall readiness DEGRADED while other core capabilities remain verified.
- Existing Anvil-owned config and credentials are not rewritten. State schema 3 changes the readiness data contract without changing the command surface, so the release is MINOR rather than PATCH.
- All mandatory regressions use local executable fixtures; a live workspace smoke test remains optional and non-destructive.
