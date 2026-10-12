---
name: anvil-databricks
description: Investigate Databricks-specific runtime behavior, Unity Catalog, compute, jobs and workflows, governance, performance, or platform constraints. Use when a solution depends on Databricks rather than generic Spark behavior.
---

# Databricks evidence workflow

Separate workspace control-plane configuration from Spark execution behavior. For a job, record task type, identity, access mode, runtime, libraries, compute policy, and retry settings; for an interactive cluster, distinguish user-level settings from policy-enforced fields. For Unity Catalog failures, check the effective principal and grants along the catalog/schema/object chain, plus the storage credential or external location involved. Avoid a workspace-wide policy change when a table grant or task-level adjustment is sufficient. State which cloud and workspace feature you assume.

Establish the workspace context, cloud, access mode, Unity Catalog status, cluster or serverless compute, job/workflow settings, and exact Databricks Runtime before drawing platform-specific conclusions. Inspect the actual job configuration, permissions, table metadata, logs, query plan, and runtime evidence that relate to the issue.

For Unity Catalog, trace catalog/schema/table ownership, grants, storage credentials and external locations, identity propagation, and the operation's execution identity. For compute and workflows, examine runtime version, policies, libraries, task dependencies, retries, schedules, and cluster reuse. For performance, distinguish a Databricks platform feature from generic Spark tuning and verify actual execution behavior.

Do not encode fast-changing runtime or governance behavior as timeless fact. Confirm capabilities, defaults, deprecations, and supported syntax in current official Databricks documentation for the target cloud and runtime. Do not invent workspace policy or company practice. Propose the narrowest change that respects governance and report prerequisites, evidence, and any remaining platform uncertainty.
