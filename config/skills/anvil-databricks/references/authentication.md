# Authentication and workspace profiles

Anvil 2.3 uses supported Databricks Unified Authentication through the official CLI and Python SDK. CLI `1.0.0` or newer remains preferred when available. The CLI profile is reused by the SDK; authentication remains under Databricks-owned configuration and credential storage.

## Setup and cross-session selection

`make databricks-setup` is explicit setup intent. It attempts to install the official CLI into Anvil's user-local data path with SHA-256 validation. If the CLI is blocked, it prepares the official SDK in an Anvil-owned isolated virtual environment. The selected profile is validated with the active provider. Anvil state is atomic, mode `0600` inside a mode `0700` directory, and contains only profile, host, provider, and capability metadata.

- One valid workspace profile can be selected automatically during setup.
- Several valid profiles require an interactive choice. The profile name and HTTPS workspace host are shown; Anvil does not silently choose the first.
- A selected profile that becomes invalid stays selected and is reported for repair. Authenticate that same profile with `databricks auth login --profile NAME`, then rerun setup. Anvil does not fall back to another workspace.
- Task commands may accept an explicit `--profile NAME`; it is validated for that invocation and does not change the stored default.

For a human workstation, use OAuth U2M through `databricks auth login` or the supported sign-in path in the official VS Code extension. The SDK can reuse resulting Unified Authentication state. VS Code is assisted only; Anvil does not automate the UI or inspect extension internals. Anvil never creates PATs, logs out, or reads token-bearing output.

If setup is blocked by enterprise policy, review the reported provider state and use an already supported auth profile or official VS Code sign-in. Anvil does not request elevation or bypass policy. `make databricks-setup DRY_RUN=1` previews local discovery without network access or state changes.

## Official behavior checked

Checked 2026-10-16 against the [CLI auth reference](https://docs.databricks.com/aws/en/dev-tools/cli/reference/auth-commands), [OAuth U2M guide](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m), and [unified authentication guide](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth). `auth profiles` prints names, hosts, and validity without access tokens. `auth describe` can expose secrets only with `--sensitive`; Anvil never uses that option.
