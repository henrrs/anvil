# ADR-0012: Resolve Databricks providers per capability

## Status

Accepted for Anvil 2.3; configuration ownership amended for Anvil 2.5.

## Context

Anvil 2.2 routed Databricks authentication, resource discovery and execution through the Databricks CLI. Restricted workstations may prohibit its installation, and different shell sessions may have different `PATH` values. CLI absence should not make all Anvil Databricks capabilities unavailable when a supported official SDK can use the same Unified Authentication configuration. Earlier setup could adopt an arbitrary external profile, mixing unrelated workspace and authentication state into Anvil.

One global provider is insufficient: SQL Connector is specialized for SQL, Databricks Connect is a Spark development client, and VS Code is an assisted workflow rather than a headless API.

## Decision

- Model only the Databricks capabilities Anvil needs and resolve a provider separately for each capability.
- Keep the official CLI as the preferred general-purpose provider.
- Use the official Python SDK in an Anvil-owned virtual environment as the primary headless fallback for identity, compute, warehouses, Command Execution and Statement Execution.
- Recognize SQL Connector and Connect as specialized optional providers; do not install them automatically.
- Treat the official Databricks VS Code extension as assisted only. Detect it through public extension listing; do not automate the UI or inspect extension internals.
- Own a separate Databricks config at `${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks/databrickscfg` and name managed profiles `anvil-*`. External profiles are diagnostic-only and are never adopted, changed, or reauthenticated by Anvil.
- Run the CLI and SDK against the same Anvil config/profile and remove inherited `DATABRICKS_*` overrides from Anvil child processes. Never build custom OAuth or copy credentials into Anvil state.
- Resolve authentication only after collecting the workspace and detecting cloud/topology. Prefer an existing Azure CLI session for Azure workspaces, use device code for supported remote sessions, and retain Databricks CLI U2M where appropriate.
- Stage and validate a candidate config before atomic activation. `RESET=1` replaces only owned config and retains a private backup; ambiguous unowned data is never overwritten.
- Attempt CLI installation only during an explicit `make databricks-setup`, using an official release, checksum verification, user-local ownership and no privilege elevation.
- Store a versioned, atomic, secret-free provider cache. Revalidate a provider when used and report PATH visibility separately from absolute-path usability.
- Do not let corporate policy blockages trigger alternate credential extraction, hidden binaries, IDE scraping or privilege bypass.

## Consequences

- A healthy CLI remains the default; a blocked CLI can still leave the core Databricks capabilities ready through SDK fallback.
- Standard reforge and upgrade stay independent of Databricks installation, network access and authentication.
- VS Code assisted workflows are visible but never reported as headless execution.
- Provider routing and install behavior can be tested offline using local doubles without a workspace or real credentials.
- Users upgrading from external-profile reuse may need one clean sign-in. The old profile and its credential store remain unchanged; Anvil does not migrate credential values.
- The SDK's version is pinned and must be reviewed against official API changes before upgrade. SQL Connector requires supported warehouse metadata; Connect is separately configured for Spark compatibility.
