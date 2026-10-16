# Databricks authentication

Anvil uses Databricks Unified Authentication through supported configuration profiles, environment variables, and provider libraries. It does not create credentials, scrape IDE storage, or implement OAuth itself.

## Profiles

Databricks configuration profiles live in the supported `.databrickscfg` location (or the path selected by `DATABRICKS_CONFIG_FILE`). The SDK accepts a selected profile through `WorkspaceClient(profile=...)`; the CLI uses `--profile`. Anvil discovers profile names and HTTPS workspace hosts, validates the selected identity through the active provider, and stores only the selected name and host in its own state.

One valid workspace profile can be selected automatically. Several valid profiles require a user choice. If the saved profile disappears or becomes invalid, Anvil asks for repair and does not silently choose another workspace. With only the SDK provider, Anvil can also use the supported default profile or environment-based Unified Authentication.

`make databricks-setup` owns the local interactive OAuth U2M flow and invokes the validated absolute Databricks CLI internally. Users do not need to locate Anvil's private CLI installation path or run an internal executable themselves. The official CLI manages its own secure credential storage and OAuth U2M lifecycle.

The auth strategy resolver uses the workspace cloud and local topology:

- A previously validated profile is reused without another login.
- On a local interactive terminal, Anvil can start the official Databricks CLI browser-based OAuth U2M flow. The flow has a bounded inactivity watchdog and the CLI's own login challenge timeout.
- For an Azure workspace, a current Azure CLI session may be reused by the Databricks SDK. In a remote/headless Azure session, Anvil can run `az login --use-device-code` and then validate the identity with `WorkspaceClient(host=..., auth_type="azure-cli")`.
- For remote AWS/GCP and unsupported headless contexts, Anvil does not assume that a browser callback on the user's workstation can reach a remote process. It guides the user to a supported Databricks Unified Authentication profile or the official VS Code extension.

Authentication is never implemented by Anvil itself. It does not copy tokens, automate browser UI, inspect IDE credential stores, or infer cross-cloud device-code support.

## State and secrets

Anvil state is `${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks.json`, atomically written with mode `0600` inside a `0700` directory. It contains a schema version, selected profile, workspace host, non-secret auth strategy/provider/cloud labels, provider health/discovery metadata, and capability resolution. It never contains tokens, passwords, client secrets, signed URLs, one-time device codes, or raw identity payloads.

The provider state is a cache. The active executable/package and authentication are revalidated when used. Existing 2.2 profile and host preferences migrate without changing Databricks authentication or profile files.

## Official references

- [Unified Authentication](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth)
- [Configuration profiles](https://docs.databricks.com/aws/en/dev-tools/auth/config-profiles)
- [OAuth U2M](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m)
- [CLI authentication commands](https://docs.databricks.com/aws/en/dev-tools/cli/reference/auth-commands)
- [Databricks SDK authentication types](https://github.com/databricks/databricks-sdk-py/blob/main/docs/auth-types-reference.md)
- [Microsoft Azure CLI device-code sign-in](https://learn.microsoft.com/cli/azure/authenticate-azure-cli-interactively)
