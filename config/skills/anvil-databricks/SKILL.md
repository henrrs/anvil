---
name: anvil-databricks
description: Use for Databricks CLI authentication, workspace discovery, remote Python or SQL execution, system tables, jobs, pipelines, governance, platform behavior, performance, or FinOps. Do not use for generic Spark or Delta questions that do not depend on Databricks.
---

# Databricks capability

Use Anvil's Databricks CLI adapter at `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/databricks.py`. The source checkout path is `scripts/databricks.py`. Read only the reference needed for the task; the system-table snapshot is a dated guide and live workspace metadata is authoritative.

## Before a remote task

1. Run `python3 "$XDG_CONFIG_HOME/opencode/scripts/databricks.py" status --format text` (use `$HOME/.config` when `XDG_CONFIG_HOME` is unset). Repair a selected profile with `make databricks-setup`; never silently choose another profile.
2. Read `references/authentication.md` for profiles, `references/compute.md` for Python, or `references/sql-warehouses.md` for SQL.
3. Discover resources. One running suitable resource may be used; if several are running, ask which one. If none are running, show choices and obtain approval before starting anything. Do not remember a compute choice unless asked.
4. Use live `SHOW SCHEMAS IN system`, `SHOW TABLES IN system.<schema>`, or `DESCRIBE TABLE system.<schema>.<table>` before relying on a system table when practical.

## Execution and safety

- Run remote Python only when the user clearly asks for remote execution. Review its effects; ask before running destructive or externally visible code. The helper creates, polls, bounds, cancels on timeout, and destroys a command context.
- Run SQL on a selected SQL warehouse. The helper uses Statement Execution with inline results capped at 100 rows and 1 MB, polls terminal state, and rejects statements that appear to mutate data or configuration unless the user has approved them and `--allow-mutation` is passed.
- Never start, stop, resize, edit, or delete compute, warehouses, jobs, pipelines, permissions, or system schemas without direct approval. Do not create compute automatically.
- Do not read token output, use `databricks auth describe --sensitive`, or store credentials. Anvil preferences contain only profile, host, and verification time. Keep result rows and system-table details out of durable memory.

## FinOps

Read `references/finops-methodology.md` and only the matching table/query references under `references/` and `queries/`. Aggregate and bound data in Databricks before returning it to the model. Distinguish dedicated/serverless job cost from approximate shared all-purpose allocation, and Databricks list-cost evidence from a full cloud bill. Do not apply classic node metrics to a SQL warehouse.

Use `python3 "$XDG_CONFIG_HOME/opencode/scripts/databricks_finops.py"` with bounded aggregate evidence on stdin to compute the deterministic Evidence Confidence Score. The score measures evidence quality, not the probability that an optimization will succeed. If access or evidence is missing, state the limitation instead of inferring a result.
