# Databricks FinOps evidence method

## Evidence plan

Choose sources by workload and requested time window. A job may need run timelines, task timelines, compute configuration history, node timeline, billing usage, and list prices. A pipeline may need pipeline/update timelines and billing. A SQL warehouse needs warehouse configuration/events, query history, billing usage, and list prices. Do not query every schema by default.

Filter at the source, aggregate close to Databricks, and return a small bounded result. Avoid raw telemetry, statement text, identities, or `SELECT *`. Verify time bounds, permissions, system-table availability, ingestion delay, retention, and truncation before interpreting results.

## Attribution and metrics

- Dedicated job compute or serverless usage may support job/run attribution through `usage_metadata.job_id` and `usage_metadata.job_run_id`, when populated.
- Jobs run on shared all-purpose compute do not receive per-job IDs in billing usage. Attribute only an explicitly described approximation based on shared cluster usage and runtime overlap.
- Job and task timeline rows can be sliced across long runs. Aggregate by workspace/job/run before counting runs or computing durations.
- Node timeline data is minute-granularity per instance. Separate driver and worker metrics. Report sample count and telemetry coverage; compute p50/p95/max for CPU, memory, CPU wait, worker count and duration as available.
- SQL warehouse workloads use query history, warehouse events/configuration, and billing data. Do not treat classic node CPU/memory as warehouse internals.
- `system.billing.usage` corrections use `ORIGINAL`, `RETRACTION`, and `RESTATEMENT`; aggregate quantities without discarding corrections. `system.billing.list_prices` supplies list-price estimates, not customer-discounted invoices or full cloud infrastructure cost.

## Evidence Confidence Score

The deterministic 0–100 score measures evidence quality. It is not a probability of success:

| Dimension | Points |
|---|---:|
| Sample size: 20+ / 10–19 / 5–9 / under 5 runs | 20 / 14 / 8 / 4 |
| Telemetry coverage | 20 × coverage ratio, rounded |
| Freshness: ≤24 h / ≤7 d / ≤30 d / older or unknown | 15 / 11 / 6 / 0 |
| Cost attribution: dedicated/serverless/warehouse / unknown / shared | 15 / 8 / 4 |
| Independent signal count | 4 per signal, capped at 15 |
| Compute configuration history: complete / partial / missing | 15 / 8 / 0 |

Subtract 30 for missing system-table access, 8 for fewer than three runs, 10 for telemetry below 50%, 10 for short-lived compute likely underrepresented, 10 for partial/stale billing, and 15 for conflicting signals. Clamp the result to 0–100. Labels are LOW below 55, MEDIUM from 55 through 79, and HIGH at 80 or above.

## Recommendation threshold

High averages alone never justify a change. A direct right-sizing recommendation requires at least ten runs, at least 80% telemetry coverage, complete historical configuration, non-shared attribution, CPU average below 35%, CPU p95 below 50%, memory p95 below 60%, autoscale max at least twice the observed p95 worker count, and CPU wait p95 below 10% or unavailable with a clear limitation. High CPU/memory peaks or CPU wait block aggressive downsizing. Less complete underutilization is a **test candidate** for a controlled benchmark, not an instruction to edit production compute.

Report scope, window, workload, compute, utilization, Databricks usage/list cost, reliability/runtime signals, coverage/limitations, candidates, score, and a suggested validation step. Keep every conclusion traceable to aggregate evidence.
