# Anvil 2.13.0 — Intent and Analytical Intelligence Engineering Report

**Assessment date:** 2026-10-30

**Release recommendation:** **NOT READY**

## Architecture assessment

Before implementation, the repository assessment examined runtime/provider boundaries, agent and instruction loading, lazy skills, memory and engineering state, communication extraction and quantitative contracts, artifact rendering/review, Databricks adapters, lifecycle ownership, and offline/lifecycle test architecture. The findings are in [the architecture assessment](intent-analytical-architecture-assessment.md); [ADR-0021](decisions/ADR-0021-intent-compilation-and-analytical-intelligence.md) records the implementation boundary.

Anvil already had a lazy communication skill, bounded source extraction, deterministic comparisons over structured metrics, and artifact-independent evidence/finding fields inside communication plans. It did not have a general raw-table profiler, generic bounded operations, or a separate analysis-result contract. The existing quantitative helper expects prepared metrics, and the artifact contract participates in presentation planning. Neither is an appropriate place to own reusable row-level analysis.

## Implementation

Added a stateless Python standard-library package at `scripts/analysis/` and the local CLI `scripts/analyze.py`. The helper profiles explicitly named CSV, TSV, flat JSON arrays, and JSON Lines; validates intent, semantic model, plans and results; executes deterministic operations; records provenance; ranks findings by Pareto tiers; and adapts validated findings to the existing communication contracts. The `anvil-communication` skill remains the lazy model-reasoning layer. `make capabilities` reports the helper and its limits.

The helper has no network, model, database, external package, cache, new Make target, persistent analysis state, or result-file write. Limits include 32 MiB per source, 100,000 rows, 200 columns, 250,000 profile cells, 2,000 tracked distinct values per column, 100 groups per operation, two grouping dimensions, and 5 MiB total output.

### Intent compilation

`TaskBrief` keeps the exact original request and validates explicit and reasoned-derived requirements separately. Derived requirements need a rationale. Constraints, ambiguities, non-goals, evidence expectations, quality attributes, and success criteria remain structured. The contract prevents request-text substitution; whether a live model faithfully reasons from that text is not established by schema validation.

### Analytical intelligence

Profiles report source hash, types, null coverage, numeric and temporal summaries, distinct-count limits, and candidate roles as hints. The model-facing skill instructions cover semantic confidence, question selection, competing explanations, distributions, population/composition, coverage, concentration, anomalies, relationships, and stop conditions. The plan contract validates bounded questions/operations and units. The deterministic operations include counts, summaries, ratios/shares, period changes, trends, distributions, volatility, coverage, cohorts, ranks, concentration, and correlation.

Intent interpretation, semantic assignments, question generation, materiality judgments, hypotheses, and narrative remain model reasoning. No workflow was added that automatically runs every analytical lens. The CLI validates and executes an already selected plan; it does not decide business semantics or synthesize a final narrative.

### Adaptive depth

The skill chooses FAST, STANDARD, or DEEP according to task value, ambiguity, source complexity, and the remaining question. Contracts cap each at 4, 12, or 20 questions and operations. A shallow direct path remains the instruction for short code, writing, and explanation work. The fact that the skill is lazy is covered structurally, but live prompt loading and model latency for short tasks were not measured.

### Evidence and claim calibration

Evidence includes source locator and SHA-256 and may retain the deterministic method and result. A plan is pinned to the profile hash; changed input stops execution. Findings distinguish OBSERVED, DERIVED, INTERPRETED, HYPOTHESIS, and UNKNOWN, and every non-UNKNOWN finding must cite evidence. Correlation explicitly states that it does not establish causation; insufficient temporal evidence cannot be labeled a trend. Materiality stores separate named dimensions and produces explainable Pareto tiers rather than a weighted score.

### Artifact integration

The analytical result is independent of artifact format. A narrow adapter carries evidence, epistemic class, findings, and materiality order to existing communication contracts. Offline tests validate both summary/section and presentation/slide plans with the same evidence and finding. The adapter does not create slides, render binary files, select visual hierarchy, or recalculate analysis. Existing Markdown/SVG capability and limitations remain unchanged; binary PPTX/DOCX/PDF rendering is still unavailable.

### Configuration preservation

The helper is now copied and manifested as Anvil-owned managed configuration through the existing staging and lifecycle transaction. OpenCode 1.x/2.x profile behavior, exact runtime selection on Anvil-only upgrade, external configuration ownership, memory, Databricks state, rollback snapshots, and machine-local files remain on the existing lifecycle paths. The brownfield 2.6.1 fixture was updated to model a real old install without 2.13 helper files. Lifecycle tests verify install, upgrade, reforge, rollback, runtime migration, and local/user state preservation.

## Tests

The final `make test` run passed. It exercised the shell/Python checks, release-document consistency, OpenCode 1 and 2 offline profiles, Databricks fakes, memory/distillation regressions, analytical and communication suites, 25 engineering tests, adaptive evaluation replays, and the full upgrade/reforge/runtime-migration/rollback matrix. The lifecycle matrix specifically installed the new helper from a 2.6.1 brownfield profile and verified its manifest and ability to profile a named fixture.

`tests/analysis.py` also checks malformed/duplicate/nested JSON, byte/cell/symlink limits, exact request provenance, low-confidence semantics, source drift, composition, like-for-like population, segment trends, outlier distribution, rate versus percentage-point changes, coverage, correlation language, materiality, unrelated helpdesk transfer, and both existing artifact representations.

## Evaluation

| Dimension | 2.12 baseline | 2.13 offline candidate | What remains unmeasured |
|---|---|---|---|
| Intent fidelity | No structured raw-data task brief contract | Exact source request and explicit/derived separation pass contract fixtures | Live-model scope fidelity and ambiguity handling |
| Analytical coverage | No general deterministic raw-table profile/execution API | Predeclared synthetic operations cases passed for volume, population, segments, cohort, trend, distribution/outlier, coverage, stable metric, and anomaly | General discovery recall on real user tasks |
| Numerical correctness | Existing calculations operate on prepared structured metrics | Deterministic fixture calculations and unit semantics passed | Independent business-data validation |
| Missed material findings | Not measured for raw-table analysis | **0 missed among the assertions predeclared in the synthetic benchmark** | General missed-finding rate |
| Unsupported claims | No raw-table reasoning workflow to compare | Deterministic calculations make no semantic claims; correlation and temporal limits are qualified | Live-model unsupported-claim rate and claim fidelity |
| Materiality | Existing editorial selection, no analysis Pareto contract | Separate dimensions and Pareto ordering pass offline fixtures | Live narrative prioritization quality |
| Artifact usefulness | Existing artifact flow remains the baseline | Same analytical finding validates in summary and presentation plans | Rendered artifact quality or user assessment |
| Latency | No comparable raw-table API | 10,000 rows, profile plus execution: FAST (4 ops) **151.3 ms**, STANDARD (12) **189.6 ms**, DEEP (20) **235.7 ms** in the final suite run; two source scans per run | Live task latency and simple-task overhead |
| Model/tool calls | No comparable raw-table workflow | The deterministic helper made **0 model calls, 0 external tool calls, and 0 prompt-token use**; each measured end-to-end test read the source twice | Agent model calls, shell/tool invocations, context and token use |

The latency results are one local synthetic run on this machine, not a general service-level guarantee. The deterministic analysis helper is cheaper at shallower depth, but no live model comparison establishes the quality per token or confirms that STANDARD/DEEP are selected only when worthwhile. The old version has no directly comparable raw-table endpoint, so no numerical baseline improvement is claimed.

## Compatibility

OpenCode 1.x and 2.x remain supported. No model/provider/runtime is pinned. No runtime update, external service, Databricks setup, migration of memory, or change to existing artifact renderers is required. The same-major source compatibility window covers seven prior Anvil minor releases, retaining the supported 2.6.x upgrade path.

## Known limitations

- Live model quality, task success, question recall, claim calibration, model/tool-call count, context use, and token use were not evaluated.
- There is no deployed/task-level question generator or narrative API in the deterministic CLI; the existing agent and lazy skill perform those semantic stages.
- Only bounded local flat tables are profiled. Nested data, arbitrary larger sources, live databases, statistical inference, and automated causal attribution are out of scope.
- Analysis results are task-local and are recomputed after interruption; no cache/resume store was introduced. A source hash prevents stale-plan reuse.
- Pareto tiers are an ordering aid, not a validated executive decision policy; the model still selects what belongs in a narrative.
- Summary and presentation contracts were validated offline, but the new adapter was not evaluated in a complete rendered user artifact.

## Deferred improvements

First collect a reproducible, privacy-safe live-model evaluation set covering intent fidelity, missed/unsupported claims, analytical breadth, narrative selection, short-task overhead, tool calls, latency, and tokens across all supported runtime/model combinations. Only if that evidence demonstrates need should Anvil add caching, additional table formats, a result-resume mechanism, or deeper artifact integration.

## Anti-overengineering review

The new abstractions each own a distinct boundary: `contracts` validates model-facing structures; `profiling` parses bounded local rows; `primitives` computes deterministic operations; `findings` validates evidence and materiality; `adapter` maps to current artifact contracts. The existing quantitative helper could not own raw-row ingestion without mixing that responsibility with artifact-oriented metric comparisons, and the artifact renderer could not own analysis without coupling results to output format. Deliberately omitted: second agent/skill, generic workflow engine, database/dataframe framework, network service, durable analysis state, distributed/local cache, and new Make command. The existing skill and lifecycle manifest remain the extension points.

## Release recommendation

**NOT READY.** Offline correctness, bounded behavior, artifact-contract separation, runtime compatibility, and lifecycle preservation passed. The specification requires live-model quality and responsiveness evidence before calling this evolution ready; that evidence is absent. Keep 2.13.0 as a candidate until a controlled evaluation can report measured quality, latency, tool calls, and tokens without implying improvement from deterministic fixtures alone.
