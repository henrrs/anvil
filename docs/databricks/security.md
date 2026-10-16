# Databricks security boundaries

- The Databricks CLI owns credentials, OAuth refresh, profile files, and OS-native token storage. Anvil stores only non-secret profile preferences.
- Never print token output or call sensitive auth modes. CLI stderr is not forwarded verbatim by the adapter because errors may contain user data.
- Anvil does not create PATs, log out of Databricks, or modify the user's CLI profiles during upgrade or rollback.
- Python and SQL results are bounded; SQL uses inline results rather than signed external result URLs. The helper never persists results.
- System-table queries filter and aggregate before data reaches the model. Raw table dumps do not go to durable Anvil memory.
- Read-only discovery is the default. The adapter has no cluster, warehouse, job, pipeline, permission, or system-schema mutation endpoints. DDL/DML SQL requires explicit user approval and an explicit flag; potentially destructive Python code must be reviewed and approved before execution.
- Stopped compute is never started silently. Doctor and capability checks do not create cost or change workspace resources.

These are agent and adapter guardrails, not a substitute for Databricks grants, compute policies, SQL permissions, workspace controls, or the user's review of code and queries.
