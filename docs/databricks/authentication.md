# Databricks authentication

Anvil uses Databricks Unified Authentication through supported configuration profiles, environment variables, and provider libraries. It does not create credentials, scrape IDE storage, or implement OAuth itself.

## Profiles

Databricks configuration profiles live in the supported `.databrickscfg` location (or the path selected by `DATABRICKS_CONFIG_FILE`). The SDK accepts a selected profile through `WorkspaceClient(profile=...)`; the CLI uses `--profile`. Anvil discovers profile names and HTTPS workspace hosts, validates the selected identity through the active provider, and stores only the selected name and host in its own state.

One valid workspace profile can be selected automatically. Several valid profiles require a user choice. If the saved profile disappears or becomes invalid, Anvil asks for repair and does not silently choose another workspace. With only the SDK provider, Anvil can also use the supported default profile or environment-based Unified Authentication.

The official CLI manages its own secure credential storage (“secure storage”) and OAuth U2M token lifecycle. To authenticate through the official CLI, use:

```bash
databricks auth login
make databricks-setup
```

When the CLI is unavailable, sign in through the official Databricks VS Code extension or prepare another supported Unified Authentication profile, then rerun `make databricks-setup`. VS Code is a guided authentication path; Anvil does not automate its UI.

## State and secrets

Anvil state is `${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks.json`, atomically written with mode `0600` inside a `0700` directory. It contains a schema version, selected profile, workspace host, provider health/discovery metadata, and capability resolution. It never contains tokens, passwords, client secrets, signed URLs, or raw identity payloads.

The provider state is a cache. The active executable/package and authentication are revalidated when used. Existing 2.2 profile and host preferences migrate without changing Databricks authentication or profile files.

## Official references

- [Unified Authentication](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth)
- [Configuration profiles](https://docs.databricks.com/aws/en/dev-tools/auth/config-profiles)
- [OAuth U2M](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m)
- [CLI authentication commands](https://docs.databricks.com/aws/en/dev-tools/cli/reference/auth-commands)
