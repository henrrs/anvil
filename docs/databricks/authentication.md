# Databricks authentication

Anvil 2.2 uses the official Databricks CLI, minimum version `1.0.0`. The CLI owns authentication and OAuth U2M token storage. Anvil runs `databricks auth profiles`, non-sensitive `databricks auth describe --profile NAME`, and `databricks current-user me --profile NAME` to discover and validate a selected workspace. It never calls `auth describe --sensitive`, `auth env`, or `auth token`.

Use OAuth U2M on a human workstation:

```bash
databricks auth login
make databricks-setup
```

The CLI prompts for the workspace and profile and completes browser login. On supported operating systems, CLI 1.0.0 and later use OS-native secure storage for U2M tokens. See the [official install guide](https://docs.databricks.com/aws/en/dev-tools/cli/install), [auth command reference](https://docs.databricks.com/aws/en/dev-tools/cli/reference/auth-commands), and [OAuth U2M documentation](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m).

Anvil stores only the selected profile name, HTTPS workspace host, and verification timestamp in `${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks.json`. It is atomically written with mode `0600` inside a `0700` directory. The preference survives new OpenCode sessions. CLI profiles and secure credentials stay in their existing Databricks-owned location.

One valid workspace profile can be selected automatically. Multiple valid profiles require a user choice. If the selected profile disappears or fails validation, Anvil reports that profile and asks for repair; it never chooses another workspace automatically. A task may use an explicit `--profile NAME` without changing the saved default.

When the CLI is missing or too old, setup points to the official install/update guide and leaves the existing environment untouched. Non-interactive setup may fail with an actionable message without blocking Anvil installation or upgrade.
