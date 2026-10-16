# Databricks capability

Anvil uses the official Databricks CLI and REST APIs through the CLI, shared shell/filesystem primitives, and the `anvil-databricks` skill. It does not require MCP, a Python SDK, or OpenCode 2. Databricks remains optional; the rest of Anvil works when the CLI or workspace is unavailable.

```text
Anvil primary agent
  → anvil-databricks skill
  → installed stdlib Python adapter
  → Databricks CLI profiles and REST API
  → bounded Python/SQL results and live system-table discovery
```

Run `make databricks-setup` to select a persistent default CLI profile. `make doctor` reports non-secret health information; `make capabilities` reports the functions available in the current environment. Neither command changes Databricks resources.

The adapter discovers classic all-purpose clusters for remote Python and SQL warehouses for SQL. It asks when more than one suitable running resource exists and never starts or reconfigures compute. SQL uses inline Statement Execution results limited to 100 rows and 1 MB. Python command contexts are polled, bounded, canceled on timeout when possible, and destroyed.

See [authentication](authentication.md), [execution](execution.md), [system tables](system-tables.md), [FinOps](finops.md), [security](security.md), and [offline tests](testing.md). The skill's current dated catalog and focused references are shipped under `config/skills/anvil-databricks/references/`.
