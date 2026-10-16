# Databricks setup

`make databricks-setup` is the explicit opt-in to configure Anvil's Databricks integration. Normal `make reforge`, `make upgrade`, `make doctor`, and `make capabilities` do not install Databricks clients. Reforge and upgrade also do not perform Databricks auth probes.

## Setup lifecycle

When invoked, setup:

1. inspects the current CLI, SDK, VS Code extension, Connect/SQL Connector packages, profile file, and saved Anvil state;
2. validates a supported CLI and prefers a previously verified absolute path;
3. if no supported CLI is usable, attempts the official Databricks CLI release in Anvil's private user-local data tree, verifies its SHA-256 checksum, and never elevates privileges;
4. classifies a failed install and prepares/reuses an isolated SDK environment if the CLI is still unavailable;
5. validates supported Unified Authentication and asks the user to choose among multiple valid workspace profiles;
6. detects local/remote terminal topology and selects only an officially supported authentication path;
7. validates Databricks identity through the selected provider;
8. writes safe provider, auth-strategy, and capability metadata atomically and reports the overall state.

The CLI release is obtained from the official [`databricks/cli` GitHub releases](https://github.com/databricks/cli/releases) metadata and installed at `$XDG_DATA_HOME/anvil/databricks/bin/databricks` (default `~/.local/share/anvil/databricks/bin/databricks`). This path is internal to Anvil; users do not need to invoke it directly. No shell startup file is modified. The CLI remains usable through its validated absolute path when its directory is missing from `PATH`.

If CLI setup is blocked, Anvil reports the failure and attempts the SDK fallback in `$XDG_DATA_HOME/anvil/databricks/venv`. The isolated environment does not modify system or user-global Python packages. A healthy SDK can use an existing supported Unified Authentication profile or an Azure CLI session for Azure workspaces. See [provider routing](providers.md) for the fallback matrix.

`make databricks-setup` owns the complete onboarding flow. On a local interactive terminal it can run the official CLI OAuth U2M login after the user provides a workspace URL. For an Azure workspace in a supported remote/headless environment, it can run the official Azure CLI device-code flow and validate identity through the SDK. Remote AWS/GCP sessions are not sent through an assumed local browser callback; setup recommends a validated profile or the official Databricks VS Code extension. Anvil does not automate extension UI.

## Preview and repeat setup

```bash
make databricks-setup DRY_RUN=1
make databricks-setup
```

The dry-run performs bounded local discovery and prints a human-readable installation/auth strategy plan. It does not contact GitHub/PyPI/Databricks/Azure, install tools, change `PATH`, authenticate, or write Anvil state. A normal setup is safe to repeat: healthy providers and the saved profile are retained, and only missing supported providers are prepared.

Public output is concise and human-readable by default. Use `make databricks-setup OUTPUT=json` for the full machine-readable result or `make databricks-setup VERBOSE=1` for local provider diagnostics. A CLI outside `PATH` is still usable by Anvil; setup will not ask the user to copy its internal path.

## Setup outcomes

Provider outcomes use `READY`, `DEGRADED`, `NOT_CONFIGURED`, `BLOCKED`, and `BROKEN`. A blocked CLI with a healthy SDK can still yield an overall `READY`. A blocked CLI and unavailable SDK are visible as provider state; neither makes Anvil's own installation unhealthy.

If no valid authentication exists and no interactive strategy is appropriate, setup reports `NOT_CONFIGURED` and gives a supported next action. No auth profile is silently switched to another workspace. Authentication is validated before setup reports `READY`; a CLI binary alone does not complete onboarding.
