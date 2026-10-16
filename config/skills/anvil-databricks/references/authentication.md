# Authentication and workspace profiles

The supported interface is the official Databricks CLI. Anvil 2.2 requires CLI `1.0.0` or newer; this is the first documented release where U2M OAuth tokens use OS-native secure storage by default. The CLI profile remains the authentication source of truth.

## Setup and cross-session selection

`make databricks-setup` invokes `databricks auth profiles`, `databricks auth describe --profile NAME` (without `--sensitive`), and `databricks current-user me --profile NAME`. The first uses the CLI's own profile validation. Anvil stores only `selected_profile`, `workspace_host`, and `last_verified_at` in `${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks.json`, mode `0600` in a mode `0700` directory.

- One valid workspace profile can be selected automatically during setup.
- Several valid profiles require an interactive choice. The profile name and HTTPS workspace host are shown; Anvil does not silently choose the first.
- A selected profile that becomes invalid stays selected and is reported for repair. Authenticate that same profile with `databricks auth login --profile NAME`, then rerun setup. Anvil does not fall back to another workspace.
- Task commands may accept an explicit `--profile NAME`; it is validated for that invocation and does not change the stored default.

For a human workstation, prefer OAuth U2M through `databricks auth login`. The CLI stores OAuth tokens in the platform's native secure store on supported operating systems. Existing managed CLI installations are preserved; Anvil does not install over them, create PATs, log out, or read token-bearing output.

If the CLI is absent, install it using the [official Databricks CLI guide](https://docs.databricks.com/aws/en/dev-tools/cli/install), then run `make databricks-setup`. Anvil continues to work without Databricks access.

## Official behavior checked

Checked 2026-10-16 against the [CLI auth reference](https://docs.databricks.com/aws/en/dev-tools/cli/reference/auth-commands), [OAuth U2M guide](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m), and [unified authentication guide](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth). `auth profiles` prints names, hosts, and validity without access tokens. `auth describe` can expose secrets only with `--sensitive`; Anvil never uses that option.
