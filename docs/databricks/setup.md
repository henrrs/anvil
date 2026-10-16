# Databricks setup

`make databricks-setup` is the explicit opt-in to configure Anvil's Databricks integration. Normal `make reforge`, `make upgrade`, `make doctor`, and `make capabilities` do not install Databricks clients. Reforge and upgrade also do not perform Databricks auth probes.

## Setup lifecycle

When invoked, setup:

1. inspects the current CLI, SDK, VS Code extension, Connect/SQL Connector packages, profile file, and saved Anvil state;
2. validates a supported CLI and prefers a previously verified absolute path;
3. if no supported CLI is usable, attempts the official Databricks CLI release in Anvil's private user-local data tree, verifies its SHA-256 checksum, and never elevates privileges;
4. classifies a failed install and prepares/reuses an isolated SDK environment if the CLI is still unavailable;
5. validates supported Unified Authentication and asks the user to choose among multiple valid workspace profiles;
6. writes safe provider and capability metadata atomically and reports the overall state.

The CLI release is obtained from the official [`databricks/cli` GitHub releases](https://github.com/databricks/cli/releases) metadata and installed at `$XDG_DATA_HOME/anvil/databricks/bin/databricks` (default `~/.local/share/anvil/databricks/bin/databricks`). No shell startup file is modified. The CLI remains usable through its absolute path when its directory is missing from `PATH`.

If CLI setup is blocked, Anvil reports the failure and attempts the SDK fallback in `$XDG_DATA_HOME/anvil/databricks/venv`. The isolated environment does not modify system or user-global Python packages. See [provider routing](providers.md) for the fallback matrix.

## Preview and repeat setup

```bash
make databricks-setup DRY_RUN=1
make databricks-setup
```

The dry-run performs bounded local discovery and prints the installation/auth plan. It does not contact GitHub/PyPI/Databricks, install tools, change `PATH`, or write Anvil state. A normal setup is safe to repeat: healthy providers and the saved profile are retained, and only missing supported providers are prepared.

## Setup outcomes

Provider outcomes use `READY`, `DEGRADED`, `NOT_CONFIGURED`, `BLOCKED`, and `BROKEN`. A blocked CLI with a healthy SDK can still yield an overall `READY`. A blocked CLI and unavailable SDK are visible as provider state; neither makes Anvil's own installation unhealthy.

If no valid authentication exists, setup prints the next supported action. Authenticate with the official CLI or VS Code extension and run setup again. No auth profile is silently created or replaced by Anvil.
