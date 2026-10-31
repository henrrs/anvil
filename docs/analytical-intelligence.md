# Analytical Intelligence

Anvil 2.14 realigned the 2.13 task-local table workflow as a reusable Analytical Intelligence capability. Anvil 2.15 hardens the semantic foundation before model-backed higher-order analysis. Analysis is available for a direct answer in the existing single Anvil agent; report and presentation plans can consume the same evidence and findings. An artifact is optional and is never a prerequisite for investigation.

```text
Original request
  → bounded profile and semantic candidates
  → user/task-specific questions and plan
  → deterministic execution
  → evidence, hypotheses, claims and findings
  → direct response or communication/artifact consumer
```

The analysis package owns bounded local data profiling, candidate grain/entity evidence, reusable calculations, provenance contracts and claim checks. The communication package owns audience framing, editorial selection, visual intent and rendering. The communication-side adapter imports validated analysis results; the analysis core does not import presentation or renderer code. Shared arithmetic for changes and distributions lives in `scripts/analysis/statistics.py`; communication adds its unit, epistemic and audience rules around those calculations.

## Semantic profile

Run the helper from a checkout:

```bash
python3 scripts/analyze.py profile ./named-data.csv > /tmp/anvil-profile.json
```

Only explicitly named UTF-8 CSV, TSV, flat JSON row arrays, or JSON Lines files are read. The profile records source path/hash, exact observation count, profiled row count, column types, missingness, numeric/temporal summaries, and a task-scoped `semantic_context`.

The semantic context uses an additive schema-v2 evidence model. It separates:

- observations from persistent entity candidates and their one- or multi-column entity keys;
- event keys and technical/row keys from persistent entities;
- time dimensions, descriptive dimensions, measures and candidate keys;
- composite relationship candidates from entity and observation keys;
- positive and negative evidence with `HIGH`, `MEDIUM`, `LOW` or `UNKNOWN` confidence;
- a bounded observation-grain candidate (at most six candidate columns and combinations up to width three);
- candidate metric templates, analytical questions, missing-key/duplicate-row risks, and explicit limitations.

For example, a table may report 160 observations, 8 repeated `customer_id` candidates and a candidate grain of `customer_id × period × product_id`. Those are different facts: an entity key identifies a persistent object, while grain describes what one observation represents. An event ID can identify an occurrence without representing an entity; a unique row ID can identify a record without carrying business identity; a dimension such as region is not promoted just because it repeats; and an entity can require a composite key. The profile also recognizes snapshots where temporal repetition is unavailable and can abstain when evidence is insufficient.

Inference combines names, data shape, recurrence, missingness, uniqueness, time behavior, dimensions, functional dependencies and optional schema-v1 source metadata. Metadata can declare field roles, entity/event key groups, uniqueness constraints and observation grain. A declared database primary key remains distinct from an analytical entity. Ingestion and processing timestamps are reported separately from event/business time and do not automatically extend business grain. Confidence and concise supporting/contradicting evidence remain candidates; they do not establish units, intent, causality or business meaning.

Downstream claims must use the actual key fields and honor candidate confidence. If evidence does not establish an entity, Anvil does not turn row count or an identifier-looking column into a definitive population claim. `UNKNOWN` is a valid answer.

Grain search examines at most six candidate fields and combinations up to three fields. If no complete unique row key is established, grain confidence is `UNKNOWN`; sampled profiles lower confidence and explicitly limit counts to the profiled prefix. Entity candidates never receive a business confirmation automatically. The user request, source/query semantics and applicable documentation remain authoritative.

The profile rejects symlink paths, malformed/ragged records, duplicate JSON keys, nested JSON cells, unsupported encodings, and inputs over 32 MiB. It supports at most 100,000 rows, 200 columns and 250,000 profile cells. Prefix sampling labels statistics incomplete. The profile `source_sha256` pins a plan/result to its exact input. An execution plan stops if its row budget cannot cover the whole input; it never calculates a silent prefix. Grouping supports at most two dimensions and 100 groups, categorical labels are bounded, and full output is capped at 5 MiB.

## Bounded execution

The agent preserves the exact request in `TaskBrief.original_request`, chooses only relevant questions and compiles a plan pinned to the profile SHA-256. Plans have these maximums:

| Depth | Questions | Deterministic operations | Use |
|---|---:|---:|---|
| FAST | 4 | 4 | Direct calculations with cheap semantic safeguards |
| STANDARD | 12 | 12 | Normal comparisons and focused profiling |
| DEEP | 20 | 20 | Explicit or decision-critical investigation |

The `FAST` path still needs the bounded profile to prevent row/entity mistakes. The profile JSON can be reused during execution so semantic inference is not repeated:

```bash
python3 scripts/analyze.py execute ./named-data.csv analysis-plan.json --profile /tmp/anvil-profile.json
```

The helper verifies the profile source path, SHA-256 and row count against the current input. It rereads the named file for calculations, detects source mutation, and emits per-run metadata such as depth, rows scanned, deterministic operation count, whether semantic context was reused and elapsed time. It makes no model or network call and stores no task result. Model/tool-call and prompt-token counts for the surrounding OpenCode task are not measured by this helper.

Supported operations include row and distinct counts (including up to three composite key columns), sums, means, medians, percentiles, rankings, shares, concentration, distributions, period deltas, percentage-point deltas, trends, volatility, ratios, coverage, cohorts, category composition, contributions and Pearson correlation. Ratio operations require declared units and a denominator. Relative change is undefined for missing, zero, near-zero or negative baselines. Two points support a comparison, not a trend; a trend result requires at least three observed periods. Correlation is association only and does not establish causality.

`cohort` aggregates repeated observations within each entity-period before comparing a retained population. It reports common, added, removed, unkeyed and comparable entities separately. Use `entity_columns` for a composite entity key. It reports observed increases/decreases; a favorable direction must be explicitly supplied from metric semantics before Anvil uses the terms improved/worsened.

`contribution` is limited to additive `sum` or non-null `count` calculations by up to two dimensions. It reports signed share of net movement and share of absolute movement, including cases where positive and negative groups offset. It does not decompose means or claim that a contributor caused the change.

`composition` compares row shares for up to two explicit categories between two periods and reports total population-share movement plus optional per-category and overall metric aggregates. This surfaces category-mix change alongside within-category values. It is descriptive evidence; it does not calculate an exact within/composition decomposition for a mean or rate and does not establish causality. Missing categories remain an explicit null group; a missing comparison period produces unknown shares.

Numeric distributions report mean, median, quartiles, tail percentiles, range, dispersion and a simple 1.5-IQR outlier summary. Compare distributions independently of averages; an unchanged mean does not establish that nothing changed. Coverage operations require an explicit eligible denominator. If a period comparison includes coverage evidence and ratios differ, claim validation qualifies the comparison and lowers its reported confidence. If coverage was not measured, the result must retain that uncertainty.

## Claims, hypotheses and findings

The model may draft hypotheses and claims; deterministic code validates their contracts and the claim types it can verify. Claims separate classification (`OBSERVED`, `DERIVED`, `SUPPORTED`, `INFERRED`, `HYPOTHESIS`, `UNKNOWN`) from confidence and validation status.

`validate-result` checks evidence references and can compare:

- an observation count to one ungrouped row-count operation;
- an entity count to a distinct-count operation over the exact declared key fields;
- trend language to the executed three-or-more-point trend operation;
- like-for-like claims to a cohort result;
- broad-based claims to a direction and an explicit retained-entity share threshold;
- period comparisons to available coverage ratios, qualifying and lowering confidence when coverage changes;
- causal claims, which must remain hypotheses because this workflow has no causal design operation.

General natural-language claims receive structural/evidence-reference validation only. The validator cannot prove a model-written paragraph's semantic truth or detect every form of overgeneralization. A non-causal classification does not make a claim true. Evidence retains the named source locator/hash, operation method and bounded data; findings link to evidence and carry confidence, caveats, alternatives and separate materiality dimensions. Ranking uses explainable Pareto tiers rather than a weighted opaque score. `UNKNOWN` is valid when a semantic or comparison question is unresolved.

The deterministic `AnalysisResult` exposes context, metric/operation evidence, claims, hypotheses, findings, warnings, limitations, source provenance and execution metadata. The agent supplies task intent and narrative; renderers may adapt the validated findings but do not redo core calculations.

## Communication and current limits

The same validated evidence/findings can support a terminal answer or an existing report/presentation plan. Communication changes audience framing and form, not the underlying arithmetic. Markdown reports/slide outlines and architecture SVG rendering remain available. Binary PPTX/DOCX/PDF rendering and quantitative chart rendering are not implemented; the existing analysis helper does not produce those files.

Core analysis remains standard-library-only, runtime independent, local, stateless and optional. It does not crawl directories, persist raw inputs, write to Anvil memory/task state, contact a model/service, require Databricks, add a dependency or require an OpenCode runtime upgrade. `make capabilities` reports the bounded local analysis surface. Existing lifecycle ownership and local-configuration preservation boundaries are unchanged.

## Evaluation and release status

`tests/analysis.py` covers repeated entities, composite grain, changing populations and repeated entity-period rows, broad versus concentrated contributions, category-composition shifts beside stable segment metrics, stable-mean distribution movement, changing coverage, two-point versus multi-period trends, wrong row/entity claims, breadth thresholds, provenance, units, artifact adaptation, unrelated helpdesk data, and bounded 10,000-row execution. `tests/communication.py` verifies shared deterministic calculations. Lifecycle fixtures verify that the installed helper exposes semantic candidates through the managed-file manifest. The evaluation harness adds two unrelated synthetic fixtures, semantic traps, hidden-truth isolation, known-bad output checks, model-run policy checks, repeated-run aggregation, structured review, communication parity, and immutable artifact contracts.

Run `make eval-analytical` for deterministic L1/L2 scores and the fixed 10,000-row benchmark. Run `make eval-analytical-semantic` for the separate 24-case adversarial semantic certification, metamorphic checks, evaluator mutation tests, sensitivity/ablation measurements, and FAST/STANDARD/DEEP comparison to the immutable 2.14 baseline. Use `make eval-analytical-model MODEL=provider/model RUNS=3` or `make eval-analytical-full` to opt into blind real-runtime evaluation. Metrics and private-run handling are documented in the [analytical evaluation guide](analytical-intelligence-evaluation.md). Passing semantic certification means the substrate is ready for L3–L5 model evaluation; it does not claim that model quality or artifact fidelity has passed review.

The semantic foundation is **READY_FOR_MODEL_EVALUATION** after its deterministic certification gates passed. The overall candidate remains **NOT READY** for release: no OpenCode runtime/provider was available for a live model run in this implementation environment, so discovery, claim calibration, model latency/token cost, and communication fidelity remain unmeasured. See the [v2.14 architecture assessment](analytical-intelligence-realignment-v2.14.0.md), [engineering report](analytical-intelligence-report-v2.14.0.md), and [2.15 release notes](versions/v2.15.0.md).
