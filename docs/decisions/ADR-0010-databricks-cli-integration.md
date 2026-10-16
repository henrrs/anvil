# ADR-0010: Use the Databricks CLI as Anvil's integration boundary

## Status

Accepted for Anvil 2.2; superseded by [ADR-0012](ADR-0012-databricks-provider-independence.md) in Anvil 2.3.

## Context

Anvil must support repeatable Databricks work from OpenCode 1 and 2 sessions while keeping credentials outside Anvil memory/configuration. Adding an OpenCode 2 plugin, MCP server, SDK dependency, or direct token handling would couple the integration to a runtime or duplicate credential lifecycle.

## Decision

Use the official Databricks CLI for profile discovery/authentication and its `api get|post` commands for the supported REST API calls. Keep Anvil-specific logic in a stdlib Python adapter installed beside the shared skill. Persist only the selected profile and workspace host under Anvil's XDG config path. Require CLI 1.0.0 or newer and never overwrite an existing CLI installation.

Use Command Execution for requested Python on running classic all-purpose clusters and Statement Execution for requested SQL on running warehouses. Discover but do not start or reconfigure compute. Bound response output, redact CLI error payloads, and use live system-table introspection when practical.

## Consequences

- Both OpenCode generations use the same authentication, scripts, skills, and execution contracts.
- The Databricks CLI owns OAuth token storage and refresh; Anvil never reads sensitive auth output.
- Databricks remains optional during reforge and upgrade. Missing CLI, profile, grants, or active compute is reported as a capability limitation.
- The supported API surface requires workspace permissions and supported resource types; it does not provide cluster or warehouse mutation operations.
- Offline fixtures can validate parser and request contracts, while a real workspace smoke check remains separate from mandatory tests.
