# Databricks authentication

Anvil creates an isolated Databricks configuration and delegates authentication to the official Databricks or cloud tools. It does not create credentials and does not copy tokens, scrape IDE storage, or implement OAuth itself. Configure it with `make databricks-setup`.

## Anvil profiles

Anvil profiles live in `${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks/databrickscfg`; a development setup creates `anvil-dev`. Both the CLI and Python SDK select that config file and profile for Anvil operations. The SDK accepts a config file and profile through Unified Authentication; the Databricks CLI honors `DATABRICKS_CONFIG_FILE` and `DATABRICKS_CONFIG_PROFILE`.

External profiles such as `DEFAULT` or `dev` remain untouched and are not an Anvil authentication source. Old Anvil state that points to an external profile is retained only as legacy metadata; it is not silently reused. Setup asks the user to confirm a saved workspace host before using it to create the new Anvil profile.

## Strategy selection

The resolver evaluates workspace cloud, execution topology, available providers, Azure CLI availability/session status, and interactivity after workspace information is collected and an Anvil profile is staged.

- **Azure workspace with an authenticated Azure CLI:** reuse that session. Anvil does not open another browser. The owned profile uses `auth_type=azure-cli` for supported Unified Authentication clients; the SDK path is the guaranteed Azure CLI provider.
- **Azure workspace in remote/headless/hybrid topology without a session:** use `az login --use-device-code` when Azure CLI is available. This avoids relying on a browser callback to a remote loopback listener.
- **Azure workspace on a local interactive terminal without a session:** use normal `az login` when Azure CLI is available.
- **Azure CLI unavailable on a suitable local terminal:** use Databricks CLI OAuth U2M if the supported CLI is available.
- **AWS/GCP or unknown cloud:** use Databricks CLI OAuth U2M on a local interactive terminal. In remote/headless contexts, Anvil does not assume loopback browser callbacks work; it reports a supported assisted/manual next step.
- **Already configured Anvil profile:** validate it first. A healthy identity is reused without another login or config write.

The Databricks SQL Connector is a specialized provider with its own OAuth U2M flow; it does not consume the shared Anvil SDK profile, so Anvil does not use it as an Azure CLI-auth fallback. The CLI and SDK remain the primary profile-aware providers.

## Environment isolation

Anvil child processes receive the Anvil config path and, when selected, the `anvil-*` profile. All inherited `DATABRICKS_*` variables are removed from Databricks CLI, SDK, SQL Connector, and Azure login child environments where appropriate. Anvil never mutates the user's parent shell. Doctor and setup may list conflicting variable names such as `DATABRICKS_TOKEN`, but never print their values.

## Credential storage and state

The Anvil config file is written atomically with mode `0600` inside a mode `0700` directory. Anvil rejects plaintext token/password/client-secret fields and does not enable Databricks CLI plaintext auth storage. Databricks CLI 1.0 and later use native OS secure credential storage for OAuth U2M tokens by default; Azure CLI owns its own credential cache. Anvil state at `${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks.json` stores only the workspace host, environment, profile name/path/ownership, authentication strategy, provider metadata, and capability resolution. It never stores tokens, passwords, client secrets, signed URLs, device codes, or raw identity payloads.

`make databricks-setup RESET=1` affects only the Anvil-owned config. It backs up the previous file and activates a replacement only after identity validation. Existing general-purpose Databricks profiles and cloud authentication are not deleted or converted.

## Official references

- [Databricks CLI configuration profiles](https://docs.databricks.com/aws/en/dev-tools/cli/profiles)
- [Databricks Unified Authentication environment variables](https://docs.databricks.com/aws/en/dev-tools/auth/env-vars)
- [Databricks CLI authentication commands](https://docs.databricks.com/aws/en/dev-tools/cli/reference/auth-commands)
- [Databricks CLI authentication and secure token storage](https://docs.databricks.com/aws/en/dev-tools/cli/authentication)
- [Databricks SDK authentication types](https://github.com/databricks/databricks-sdk-py/blob/main/docs/auth-types-reference.md)
- [Databricks SDK authentication](https://github.com/databricks/databricks-sdk-py/blob/main/docs/authentication.md)
- [Microsoft Azure CLI interactive and device-code sign-in](https://learn.microsoft.com/cli/azure/authenticate-azure-cli-interactively)
