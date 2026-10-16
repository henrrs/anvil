# Databricks providers and capability routing

Anvil resolves the provider for each capability, rather than picking one global client. Provider metadata is refreshed at runtime; saved state improves discovery and observability but is not treated as current truth.

| Capability | CLI | Python SDK | SQL Connector | Connect | VS Code |
|---|---|---|---|---|---|
| Unified Auth/profile identity | Preferred | Supported | U2M connection auth | Supported | Assisted sign-in |
| Cluster/warehouse discovery | Yes | Yes | No | Limited | Assisted |
| Remote Python on classic all-purpose compute | Preferred | Command Execution | No | Different Spark model | Assisted only |
| SQL Statement Execution | Preferred | Preferred fallback | Specialized SQL fallback | No | Assisted only |
| Jobs, pipelines, workspace APIs | Yes | Yes | No | No | Assisted navigation |
| Spark development/debugging | Limited | Limited | No | Primary specialized path | Assisted |
| Declarative Automation Bundles | Primary | Not primary | No | No | Assisted workflow |

The default selection order is:

- General workspace APIs, compute, jobs and pipelines: CLI, then SDK.
- Remote Python on a running classic all-purpose cluster: CLI, then SDK Command Execution, then an assisted VS Code option.
- SQL and system-table access: CLI, then SDK Statement Execution, then SQL Connector when its supported connection details are available.
- Spark development: Databricks Connect, then assisted VS Code.
- Bundles: CLI, then an assisted VS Code workflow, otherwise unavailable.

The CLI is preferred when healthy. The resolver never routes SQL through Databricks Connect, and it never labels an assisted IDE operation as headless-ready. An unavailable provider is not simulated. No automatic Connect or SQL Connector package installation occurs.

Provider API coverage is based on the [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install), [Python SDK](https://docs.databricks.com/aws/en/dev-tools/sdk-python), [SQL Connector](https://docs.databricks.com/aws/en/dev-tools/python-sql-connector), [Databricks Connect](https://docs.databricks.com/aws/en/dev-tools/databricks-connect/python/), and [VS Code extension](https://marketplace.visualstudio.com/items?itemName=databricks.databricks) documentation checked on 2026-10-16.
