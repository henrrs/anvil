# Databricks setup

`make databricks-setup` is the explicit opt-in to configure Anvil's Databricks integration and interactive authentication. Normal `make reforge`, `make upgrade`, `make doctor`, and `make capabilities` do not install Databricks clients. Doctor performs bounded, read-only workspace checks only when an Anvil profile exists; capabilities remains local.

## Anvil-owned configuration

Anvil stores its Databricks CLI/SDK configuration at:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks/databrickscfg
```

The default development profile is `anvil-dev`; the other suggested labels create `anvil-staging` and `anvil-prod`. A custom neutral label becomes `anvil-<label>`. The file and its directory are mode `0600` and `0700`. Provider metadata remains in the separate `anvil/databricks.json` file and contains no credential values.

Setup asks for the workspace URL and environment. A previously recorded workspace can be offered as a suggestion and must be confirmed. Existing profiles in the normal Databricks config file are external state: Anvil does not select, copy, repair, rename, delete, or reauthenticate them. If an older Anvil release stored a selected external profile, its name is ignored; the saved workspace host is only a user-confirmed suggestion for the new Anvil profile.

The flow is:

1. collect workspace and environment information;
2. prepare a supported CLI and/or isolated SDK during this explicit setup command;
3. stage a private Anvil profile without replacing the active config;
4. detect cloud and execution topology, then choose an authentication strategy;
5. validate the staged profile and current user through the production CLI/SDK adapter;
6. list clusters and warehouses through that same adapter and validate their response shapes;
7. atomically activate the config and save non-secret readiness/provider metadata only when core readiness is proven.

If the active Anvil config is malformed, setup leaves it unchanged and reports `CONFIG_INVALID`. `make databricks-setup RESET=1` stages a clean Anvil config, validates it, keeps a private timestamped backup, and replaces only the Anvil-owned config. An existing config at Anvil's managed path without ownership metadata is ambiguous and is never overwritten, even with reset.

## Providers and authentication

The official Databricks CLI is installed, when needed, at `$XDG_DATA_HOME/anvil/databricks/bin/databricks` (default `~/.local/share/anvil/databricks/bin/databricks`) after checksum verification. If CLI installation is blocked, setup can prepare the isolated Python SDK under `$XDG_DATA_HOME/anvil/databricks/venv`. Neither installation uses privilege elevation or modifies shell startup files. This executable path is internal to Anvil and is not part of user instructions.

Authentication follows the workspace cloud and topology. An existing Azure CLI session is reused for Azure workspaces; local interactive Azure login and remote Azure CLI device-code login are available. Databricks CLI OAuth U2M is used where appropriate, including as a fallback if Azure CLI is unavailable in a suitable local terminal. Remote/headless AWS/GCP or unknown-hybrid contexts are not sent through an assumed loopback browser flow. See [authentication](authentication.md) and [provider routing](providers.md).

CLI and SDK child processes use the same Anvil config/profile. Inherited `DATABRICKS_*` variables are removed from those child environments; output reports only conflicting variable names, never values. The SQL Connector remains a specialized OAuth U2M path and does not reuse the SDK profile. It is not substituted for Azure CLI authentication.

## Preview and repeat setup

```bash
make databricks-setup DRY_RUN=1
make databricks-setup
make databricks-setup RESET=1
```

Dry-run performs bounded local discovery and reports the Anvil-owned profile it plans to create. It does not contact GitHub, PyPI, Azure, or Databricks; install tools; authenticate; change `PATH`; or write Anvil state/config. It may report the number of external profiles for diagnostics but never uses them. A healthy owned profile is revalidated on repeat setup without another login or config rewrite. A new profile is not activated as READY if identity or core resource discovery fails. Setup does not require a running cluster, SQL warehouse, or system-table access; an empty list is a successful result.

Human-readable output is the default. Use `make databricks-setup OUTPUT=json` for structured results or `make databricks-setup VERBOSE=1` for local provider diagnostics. A CLI outside `PATH` is still usable by Anvil.

## Setup outcomes

`READY` means current-user identity, workspace reachability, provider health, `clusters list`, and `warehouses list` all passed. `DEGRADED` means some core capability is usable but another is blocked, for example by a permission denial. `NOT_READY` means a required shared/provider check failed or no core capability was verified. `NOT_CONFIGURED` means no Anvil-owned workspace profile exists. A CLI binary or login state alone does not complete onboarding. Reforge and upgrade never install Databricks tools or probe workspace authentication.
