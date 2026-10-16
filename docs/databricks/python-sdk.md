# Databricks SDK for Python

The SDK is Anvil's primary headless fallback when the Databricks CLI cannot be used. Anvil installs the official `databricks-sdk==0.141.0` into its private virtual environment at `$XDG_DATA_HOME/anvil/databricks/venv`; it never installs the package into global Python. This exact version is pinned because the SDK publishes interface-change guidance and recommends exact pins.

The worker uses `WorkspaceClient` and supported Unified Authentication profiles. It covers identity validation, cluster and warehouse listing, Command Execution on running classic all-purpose clusters, and Statement Execution with 100-row/1 MB response bounds. SQL mutation screening, timeout cancellation, stopped-resource checks, and output normalization remain in the shared Anvil adapter.

No custom token acquisition, raw credential copying, or independent REST client is added. SDK errors are normalized to short categories; raw provider diagnostics and credential values are not printed. The SDK environment is user-owned Anvil data and is not deleted by Anvil rollback.

Official references: [SDK for Python](https://docs.databricks.com/aws/en/dev-tools/sdk-python), [Unified Authentication](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth), [Command Execution](https://databricks-sdk-py.readthedocs.io/en/latest/workspace/compute/command_execution.html), [Statement Execution](https://databricks-sdk-py.readthedocs.io/en/latest/workspace/sql/statement_execution.html), and the [SDK package release](https://pypi.org/project/databricks-sdk/0.141.0/).
