# Intent Compilation and Analytical Intelligence

Anvil 2.13 adds a task-local analytical path to the existing single agent and lazy `anvil-communication` skill. It helps preserve the user's request, inspect named data deterministically, select a bounded set of useful questions, distinguish evidence from interpretation, and prepare findings before building a narrative or artifact.

```text
Original request → TaskBrief → deterministic profile → semantic model/questions
  → bounded plan → deterministic operations → evidence/findings
  → materiality and narrative → response or existing artifact plan
```

Short coding, editing, explanation, and trivial calculation tasks stay on the direct path. The profile helper does not interpret business meaning; the existing agent and skill do that lazily when useful.

## Local helper

The helper is runtime independent, uses Python's standard library, writes results to stdout, and never invokes a model or contacts a service. In a repository checkout:

```bash
python3 scripts/analyze.py profile ./named-data.csv
python3 scripts/analyze.py validate-brief task-brief.json
python3 scripts/analyze.py validate-plan analysis-plan.json
python3 scripts/analyze.py execute ./named-data.csv analysis-plan.json
python3 scripts/analyze.py validate-result analytical-result.json
python3 scripts/analyze.py artifact-components analytical-result.json
```

After `make upgrade`, the installed helper is at `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/analyze.py`. `make capabilities FORMAT=json` reports its availability and limits.

Only explicitly named files are read. Supported inputs are UTF-8 CSV, TSV, JSON arrays of flat row objects, and JSON Lines. The helper rejects symlink paths, malformed/ragged rows, duplicate JSON keys, nested JSON cells, unsupported encodings, and files over 32 MiB. Profiling reports exact row count and hashes the source snapshot. Column statistics cover the full file up to 100,000 rows, subject to a 250,000-cell working limit; a larger profile labels its prefix statistics as incomplete. A single input snapshot stays bounded by its byte, column, row, and cell limits. Plan execution never silently analyzes a prefix: its explicit `max_rows` budget must cover the entire table, up to 100,000 rows. Output is capped at 5 MiB, each grouping has at most two dimensions and 100 groups, and categorical labels exposed in results are bounded.

The profile reports schema, physical type, row/column counts, nulls, bounded distinct counts, numeric/temporal ranges, candidate dimensions/measures/identifiers, and low-confidence lexical hints such as possible rates. Empty CSV cells and explicit JSON `null` count as missing; ambiguous text such as `NA`, `n/a`, or `null` remains a category. Those hints are not semantic conclusions. Nested/complex tables and larger datasets require a suitable pre-flattened or pre-aggregated extract.

## Bounded plans

The model builds a plan from the exact profile and pins its `source_sha256`; if the source changes before execution, the helper stops and requires a new profile. Plans have adaptive FAST/STANDARD/DEEP budgets:

| Depth | Maximum questions | Maximum deterministic operations | Typical use |
|---|---:|---:|---|
| FAST | 4 | 4 | Focused summary or comparison |
| STANDARD | 12 | 12 | Decision-relevant exploration |
| DEEP | 20 | 20 | Explicit or well-justified diagnostic investigation |

The agent selects questions and depth from user intent, ambiguity, decision importance, source coverage, and profile complexity. Deterministic code does not guess business KPIs or semantic roles. Plans can use generic counts, distinct counts, sums, means, medians, percentiles, ranking, distributions, ratios/shares, period deltas, trends, volatility, coverage, cohorts, concentration, and correlation. Ratio plans declare numerator, denominator, and result units; values are never implicitly converted.

Example plan:

```json
{
  "schema_version": 1,
  "source_sha256": "<sha256 copied from profile.source.sha256>",
  "depth": "STANDARD",
  "primary_question": "Did the measure change between the selected periods?",
  "questions": ["What changed?", "Did the population also change?"],
  "operations": [
    {
      "id": "period-change",
      "operation": "delta_percent",
      "column": "measure",
      "unit": "items",
      "period_column": "period",
      "baseline": "2026-01-01",
      "current": "2026-03-01",
      "aggregate": "sum"
    },
    {
      "id": "like-for-like",
      "operation": "cohort",
      "column": "measure",
      "unit": "items",
      "period_column": "period",
      "baseline": "2026-01-01",
      "current": "2026-03-01",
      "entity_column": "entity",
      "aggregate": "sum"
    }
  ],
  "stop_conditions": ["Stop after the comparison and cohort are evaluated."],
  "budgets": {"max_rows": 50000, "max_groups": 100}
}
```

The profile provides the exact representation for temporal values, such as `2026-03-01` for a CSV month `2026-03`. Two time points can establish a change comparison; trend wording requires at least three observed periods. Numeric distribution summaries retain median, quartiles, tail percentiles, range, and a simple 1.5-IQR outlier count. `cohort` separates common, added, and removed entities and compares the same entities across periods; it does not claim a numeric performance/composition decomposition unless one was explicitly calculated.

Correlation operations return a bounded Pearson association when there are at least three valid varying pairs. Correlation is association only; it does not establish causation.

## Evidence, findings, and narrative

Profiles and operations are deterministic. Semantic roles/confidence, question selection, materiality judgments, hypotheses, and narrative remain model reasoning. Finding types stay distinct:

- `OBSERVED`: directly present in source evidence.
- `DERIVED`: calculated deterministically from named evidence.
- `INTERPRETED`: reasoned conclusion supported by evidence.
- `HYPOTHESIS`: plausible explanation not established by the observed data.
- `UNKNOWN`: evidence is insufficient or a meaning cannot be established.

Every non-unknown finding must cite evidence. Evidence records the source locator/hash and can retain the bounded operation result and method. A finding carries separate materiality dimensions for magnitude, breadth, persistence, decision relevance, confidence, exception severity, and novelty. The validator orders non-dominated findings into Pareto tiers; it does not hide priorities in a weighted total. The narrative names material caveats and unresolved questions before artifact layout is considered.

`artifact-components` adapts validated evidence and findings into Anvil's existing communication contracts. It does not render an artifact, create visual priorities, or redo the analysis. The same structured finding can support a chat answer, Markdown report, or future artifact. Existing Markdown/SVG rendering remains unchanged; binary PPTX/DOCX/PDF and quantitative chart rendering remain unavailable.

No brief, raw data, plan, evidence, or finding is persisted in Anvil memory or engineering task state. There is no analysis cache, network service, external library, database, Databricks requirement, new agent, or additional Make target. Databricks remains an optional separately authorized evidence provider under its existing read-only rules.

## Evaluation and limits

The previous repository had no deterministic raw-table profiling/execution API; its quantitative helper accepted already structured metrics. Offline candidate fixtures now check exact calculations, percentage versus percentage-point behavior, composition and like-for-like movement, trend evidence thresholds, distribution versus mean, coverage denominators, correlation wording, evidence links, Pareto ranking, report and presentation plan adaptation, an unrelated helpdesk dataset, source drift, and a synthetic three-period operations benchmark containing changing population, a deteriorating segment, one outlier, and a stable metric. They also measure 10,000-row bounded execution. They measure deterministic correctness and local runtime only.

The helper itself makes zero model calls. An agent task typically invokes the helper once for profiling and once for execution when those stages are needed. Actual model calls, token use, semantic misses, claim fidelity, and live task latency depend on the configured model/runtime and were not available in offline tests. See the [2.13 candidate engineering report](versions/v2.13.0.md) for the release recommendation.
