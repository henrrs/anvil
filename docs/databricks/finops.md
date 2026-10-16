# Databricks FinOps analysis

Anvil builds an evidence plan from workload type and requested time window, then queries only relevant sources. Versioned SQL recipes live under `config/skills/anvil-databricks/queries/`; they filter time, aggregate, and bound result sets.

For jobs, aggregate run timeline slices by `(workspace_id, job_id, run_id)` before counting runs or calculating durations. Dedicated job compute and serverless usage may support job/run billing attribution where IDs are populated. Shared all-purpose compute does not expose precise per-job infrastructure attribution; any allocation must be marked approximate and explain the method. For SQL warehouses, combine configuration history, warehouse events, query history, and billing evidence. Classic node CPU/memory does not describe warehouse internals.

`system.billing.usage` is a Databricks usage source with correction records. `system.billing.list_prices` supports a list-price estimate matched to the effective price period. Label this as Databricks usage/list cost, not a total cloud bill or invoice amount. Usage delivery lag, discounts, missing tables, short-lived compute, incomplete telemetry, and truncation all reduce confidence.

The installed `databricks_finops.py` computes an Evidence Confidence Score from 0–100 using run sample size, telemetry coverage, freshness, attribution quality, independent signal count, and compute configuration history. It applies documented penalties for missing system tables, very few runs, low telemetry, short-lived resources, stale/partial billing, and conflicting signals. Labels are LOW (<55), MEDIUM (55–79), and HIGH (80+). This is evidence quality, not the probability that a recommendation succeeds.

Use a **recommendation** only when strong, repeated, high-coverage evidence supports a conservative change and no peak/wait signal argues against it. Otherwise present a **test candidate** for a controlled benchmark. Never change production settings automatically. Report scope, window, workload, compute, utilization, cost semantics, reliability, coverage, limitations, candidates, score, and a validation step.
