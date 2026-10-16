# Databricks security boundaries

- The CLI, SDK, SQL Connector and supported Unified Authentication own credentials, OAuth refresh and profile files. Anvil stores only non-secret provider metadata. Provider state rejects token, password, secret, credential and authorization fields.
- No privilege elevation is used. Anvil installs the CLI only to its own user-local data directory and installs the SDK only into its isolated virtual environment.
- Anvil never prints token output or requests sensitive auth modes. Provider errors are normalized and raw CLI stderr is not forwarded because it may include user data.
- Anvil does not create PATs, log out of Databricks, edit auth profiles, inspect VS Code private files, copy IDE binaries, or modify shell startup files.
- SQL and Python results are bounded; SQL uses inline results when using Statement Execution rather than signed external result URLs. Results are not persisted.
- System-table queries filter and aggregate before data reaches the model. Raw table dumps do not go to durable Anvil memory.
- Read-only discovery is the default. The adapter offers no cluster, warehouse, job, pipeline, permission, or system-schema mutation endpoints. DDL/DML SQL requires explicit user approval and an explicit flag; potentially destructive Python code must be reviewed and approved before execution.
- Stopped compute is never started silently. Doctor, capability checks, dry-run and normal Anvil setup do not create Databricks cost or change workspace resources.

These are agent and adapter guardrails, not a substitute for Databricks grants, compute policies, SQL permissions, workspace controls, corporate policy, or the user's review of code and queries.
