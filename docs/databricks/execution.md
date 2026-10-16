# Databricks execution

## Python on classic all-purpose compute

Anvil discovers accessible classic all-purpose compute through the selected provider (CLI preferred, SDK fallback) and excludes job/pipeline compute. A single suitable running cluster can be used. Multiple running choices require a user selection. Stopped choices require user approval before start. The adapter does not include a cluster start/resize/edit operation.

Python uses the official [Command Execution API](https://docs.databricks.com/api/command-execution/v2/command-execution): validate the cluster, create a Python context, wait until it is ready, submit code, poll command state, return bounded results, and destroy the context. The CLI transport and SDK service client implement the same adapter contract. Timeout requests command cancellation and still attempts cleanup. Only a completed command state is success.

The user request must clearly call for remote execution. Review code for deletes, writes, external effects, or other destructive behavior and ask before running it. Anvil does not make generated code safe merely by sending it through the CLI.

## SQL on warehouses

SQL uses SQL warehouse discovery and the [Statement Execution API](https://docs.databricks.com/api/statement-execution/v1/statement-execution), through CLI or SDK. The optional SQL Connector is used only when the resolver selects it and supported connection metadata is available. One suitable running warehouse can be selected; multiple choices require a user selection; stopped warehouses require approval before start. Anvil never starts, stops, resizes, or edits warehouses.

Statements use `INLINE`/`JSON_ARRAY`, a 100-row cap, and a 1 MB response cap. The adapter polls `PENDING`/`RUNNING`, returns data only for `SUCCEEDED`, and treats `FAILED`, `CANCELED`, timeout, permissions, and invalid responses as errors. It does not use external links or log signed URLs. User values should use statement parameters. Common DDL/DML is blocked unless the user directly approves the change and the caller passes `--allow-mutation`.

For system metadata, use bounded `SHOW SCHEMAS IN system`, `SHOW TABLES IN system.<schema>`, and `DESCRIBE TABLE system.<schema>.<table>` with an explicitly selected warehouse.
