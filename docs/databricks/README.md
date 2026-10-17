# Databricks capability

Anvil integrates with Databricks capabilities, not one Databricks client. The capability layer routes each operation to the best available provider while preserving Anvil's execution bounds and mutation guardrails. It works with OpenCode 1 and OpenCode 2 and does not require MCP.

```text
Anvil primary agent
  → anvil-databricks skill
  → capability resolver
  → CLI / Python SDK / SQL Connector / Connect / assisted VS Code
  → Anvil-owned Unified Authentication profile
```

Run `make databricks-setup` only when you want to configure Databricks. That command attempts a safe user-local installation of the official Databricks CLI and prepares an isolated SDK fallback if needed. Preview local discovery and planned actions with `make databricks-setup DRY_RUN=1`; dry-run does not install, write state, or make network requests. Reforge and upgrade never install Databricks tooling or probe workspace auth.

Anvil creates its own `anvil-*` profile in an isolated config file and does not adopt or modify external `.databrickscfg` profiles. CLI and SDK operations share that profile; inherited `DATABRICKS_*` overrides are stripped from child processes. Provider state stores only ownership/profile, workspace, strategy, absolute executable path, versions, health metadata, and capability resolution. The official Databricks VS Code extension is an assisted integration; Anvil uses the public `code --list-extensions` command and does not automate IDE UI or inspect extension files.

The CLI remains the preferred provider when healthy. The isolated Databricks SDK for Python provides headless identity, compute, warehouse, Command Execution and Statement Execution capabilities when the CLI is unavailable. SQL Connector and Databricks Connect remain specialized paths and are not installed by default.

Anvil 2.6 uses one readiness contract for setup, status, and doctor. READY requires a successful current-user request plus cluster and warehouse list results through the production provider adapter; empty lists are valid, and setup does not require running compute or SQL access. `make doctor` refreshes configured workspace readiness with read-only calls. `make capabilities` remains local and distinguishes Supported, Available, and Verified. See [readiness](readiness.md) for the state machine, timeout policy, and fallback rules.

The adapter discovers classic all-purpose clusters for requested remote Python and SQL warehouses for SQL. It asks when multiple suitable running resources exist, never starts or reconfigures compute, bounds returned SQL results to 100 rows and 1 MB, and checks live system-table schemas before relying on the dated reference snapshot. FinOps recipes return filtered aggregates and distinguish Databricks usage/list-cost estimates from a complete cloud bill.

See [setup](setup.md), [readiness](readiness.md), [providers and routing](providers.md), [authentication](authentication.md), [VS Code](vscode.md), [Python SDK](python-sdk.md), [SQL](sql.md), [Databricks Connect](connect.md), [execution](execution.md), [system tables](system-tables.md), [FinOps](finops.md), [security](security.md), and [offline tests](testing.md).
