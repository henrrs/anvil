# Databricks Connect

Databricks Connect is a specialized provider for local Spark development, DataFrame execution, and debugging against supported remote compute. It is not the same as Anvil's existing remote Python execution through classic all-purpose compute and the Command Execution API.

Anvil detects Connect only when its supported Python environment contains the official package. It does not install Connect by default: Connect versions must match the local Spark/runtime and workspace compatibility requirements. Use the official setup guidance for the target workspace and runtime.

Connect is reported for `spark.develop`; it is not used as a fallback for SQL warehouse execution, Bundles, or Anvil's remote Python contract. The VS Code Databricks extension may assist with Connect setup and interactive workflows.

References: [Databricks Connect for Python](https://docs.databricks.com/aws/en/dev-tools/databricks-connect/python/), [Connect configuration](https://docs.databricks.com/aws/en/dev-tools/databricks-connect/python/connect-to-workspace), and [VS Code extension](https://docs.databricks.com/aws/en/dev-tools/vscode-ext/).
