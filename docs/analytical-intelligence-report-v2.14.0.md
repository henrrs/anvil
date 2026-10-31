# Anvil 2.14.0 — Analytical Intelligence Engineering Report

## Architecture assessment

Before this change, 2.13 already had a useful stateless `scripts/analysis` package for named-table profiles, deterministic operations, evidence/findings and materiality. The existing lazy communication skill selected questions/depth and interpreted results. However, the adapter was placed in the analysis package and imported communication contracts, quantitative comparison arithmetic was duplicated, and observation/entity/grain semantics and executed-claim checks were too weak for repeated-entity data. Current repository mapping and KEEP/MOVE/GENERALIZE/REUSE decisions are recorded in the [architecture assessment](analytical-intelligence-realignment-v2.14.0.md).

## Realignment

The artifact adapter now lives at `scripts/communication/analysis_adapter.py`. The analysis core owns bounded profiling, semantic candidates, shared calculations and result validation. Communication owns audience framing, editorial decisions and rendering. Terminal answers and artifacts can use the same profile and evidence; an artifact is optional.

## Analytical Intelligence

Added reusable candidate semantic context, candidate grain and composite observation keys, entity/cardinality evidence, candidate metrics/questions, profile reuse, composite distinct count, category-share composition comparison, entity-period cohorts, additive contribution, shared distribution/change arithmetic, claim/hypothesis checks and execution metadata. Existing distributions, deltas, trends, volatility, coverage, correlation, materiality and evidence contracts remain in the deterministic core.

## Semantic correctness

Row count is an observation count. Entity candidates are separate, uncertain and based on repeated categorical keys/cardinality/temporal evidence; a unique row identifier is not automatically treated as an entity. Composite uniqueness search is bounded to six candidate fields and keys of at most three fields. Partial profiles are labeled incomplete. Semantic guesses never prove business meaning or units.

## Investigation

Cohorts aggregate repeated observations by entity and period before comparison and report retained/added/removed/unkeyed populations and like-for-like movement. Composition reports changing category shares alongside optional within-category and overall measures; it does not perform exact mix/rate decomposition. Contribution is limited to additive sum or non-null count, and reports signed net and absolute contribution shares. Candidate metric templates and questions support a relevant investigation. Autonomous multi-stage escalation, general anomaly detection and causal inference are not implemented.

## Validation

The result validator checks provenance, profile/plan/execution correspondence, evidence references, row versus distinct-key counts, three-point trend evidence, like-for-like cohort evidence, broad-based thresholds, coverage changes and causal classification. It can structurally validate general natural-language claims but cannot prove their semantic truth. Existing findings retain confidence, caveats, alternatives and explainable Pareto materiality dimensions.

## Artifact integration

The consumer adapter maps evidence/findings to the existing communication contracts. The same deterministic change/distribution calculations now power communication formatting and analytical operations. Existing Markdown and architecture SVG generation remains in place. No binary PPTX/DOCX/PDF renderer or chart renderer exists. No real presentation benchmark was present to compare visual quality.

## Lifecycle safety

No OpenCode runtime, config profile, plugin, dependency, user-data, Anvil memory, Databricks state, or persistent analysis schema changed. The helper remains in the existing managed package tree and existing file-manifest install/upgrade/reforge/rollback flow. The lifecycle fixture asserts semantic profile behavior in an installed helper. Existing lifecycle tests cover external config ownership and rollback preservation; the full isolated suite is required below to reconfirm them on this candidate.

## Tests

- `python3 tests/analysis.py`: passed after adding repeated/composite grain, entity-period population, category composition and claim checks, additive contribution, stable-mean distribution shift, scope-aligned coverage, and claim-calibration regressions.
- `python3 tests/communication.py`: passed with a shared-statistics boundary assertion.
- `python3 -m py_compile scripts/analysis/*.py scripts/communication/*.py scripts/analyze.py tests/analysis.py`: passed before final documentation changes; final verification reruns it.
- `python3 evals/analytical/test_harness.py --scope all`: passed fixture reproducibility, hidden-truth isolation, evaluator negative cases, repeated runs, human-review overlays, parity, no-runtime handling, private permissions and benchmark workload checks.
- `make test`: passed. The complete offline suite validated lifecycle, configuration preservation, OpenCode 1/2 profiles, installed analytical helpers, Databricks fixtures, memory, engineering continuity, communication/artifacts, release docs, upgrade/reforge, migration, rollback and process-quiescence behavior.

## Evaluation harness

This phase added `evals/analytical/` as a separate observer of production analysis. It contains two deterministic synthetic fixtures, eight exercised trap snapshots, evaluator-only facts and interpretations, a blind prompt, exact L1 and separate L2 scoring, isolated optional OpenCode model runs, repeated-run aggregation, structured human review, parity checks, cost attribution, private-case support and an immutable baseline. Production analysis and communication do not import fixture truth or scoring code.

The complete offline `make test` suite passed. The immutable baseline is `evals/analytical/baselines/anvil-2.14.0-deterministic-v1.json`, run `20261031T153737Z-503d82c7`, SHA-256 `e647ed84203c6f20d93ae03c9b07a8420b68cb1183e65091487b23ccc8b3f753`. It captures the 2.14 source fingerprint at freeze and compares it with committed 2.13 revision `59d5b0af52c3649ac515bbdbbea2b1f1c2b1b8c3` using the same generated 10,000-row workload and operation counts.

### Baseline scores

| Fixture | L1 numerical | L2 semantic | L3 discovery | L4 reasoning | L5 fidelity |
|---|---:|---:|---|---|---|
| operations-v1 | 100.0% (24/24) | 33.3% (1/3) | NOT MEASURED | NOT MEASURED | NOT MEASURED |
| services-v1 | 100.0% (5/5) | 66.7% (2/3) | NOT MEASURED | NOT MEASURED | NOT MEASURED |

L1 is deterministic and complete for the facts bound by these manifests. L2 fails because the primary fixture's true composite grain is absent from the semantic grain candidates, and the candidate entity list includes `product`; the services fixture adds false entity candidates `event_kind` and `zone`. No live OpenCode runtime/provider is installed here, so L3 discovery recall/precision, L4 reasoning/claim calibration and L5 communication fidelity have no model evidence. The deterministic lexical signal is explicitly provisional and is not reported as semantic recall. After freezing, model-runner executable discovery was hardened for Anvil-managed OpenCode installations outside `PATH`, and FAST classification now requires at least three timing repetitions. A corrected `stable-average-tails-v2` snapshot was also added after discovering the original trap did not hold its mean stable; the prior snapshot remains intact. These evaluator-only changes do not alter the frozen main-fixture L1/L2 scoring or five-repetition benchmark; the baseline contains no model result.

### Cost and FAST-path investigation

| Depth | 2.13 median | 2.14 median | Change |
|---|---:|---:|---:|
| FAST, 4 operations | 147.667 ms | 186.552 ms | +26.3% |
| STANDARD, 12 operations | 186.239 ms | 223.209 ms | +19.9% |
| DEEP, 20 operations | 225.660 ms | 262.437 ms | +16.3% |

The FAST-path classification is **MIXED**. Semantic inference took 36.580 ms, 33.73% of the FAST profile stage. Total FAST latency increased 38.885 ms; profiling increased 37.639 ms and execution increased 1.945 ms. Semantic inference accounts for 94.1% of the total delta, but stage attribution does not establish causality or prove all inference work is necessary. No safeguards were disabled. This is a local helper benchmark, not end-to-end model latency or token cost.

Quality and cost stay separate: numerical arithmetic is exact for the selected facts, semantic candidate quality is incomplete, and model/tool/token cost is unavailable. No combined north-star score is calculated while L3–L5 are unmeasured.

### Observed gaps and next investment

- **ENTITY_RESOLUTION — HIGH, 2 fixtures:** Anvil promoted dimensions as entity candidates in both domains. Candidate work: improve evidence ranking from temporal repetition, composite grain and dimension role, then rerun blind fixtures and human review.
- **GRAIN — HIGH, 1 fixture:** the primary observation grain `entity_id × period × product` was missed while a unique identifier was proposed. Candidate work: improve composite-key evidence ranking and distinguish unique row ID from observation grain.
- **DISCOVERY / INVESTIGATION — NOT MEASURED:** no model runs means no evidence for hypothesis-driven investigation, distribution discovery, composition explanation, or prioritization. Do not implement those features from this offline score alone.

These are recommendations for a subsequent human-approved engineering phase, not automatic roadmap execution. First run repeated blind evaluations on a configured OpenCode/model path and have reviewers adjudicate finding recall, precision, materiality, evidence, claim calibration and output parity. Then compare recurring misses before selecting a capability. The private-case path allows human-reviewed cases without placing sensitive data in the repository.

## Documentation audit

- **Stale docs found:** README current-release summary/links, changelog current release, architecture source-window example, system-map release label/module inventory, capability matrix and release discipline.
- **Missing docs found:** no 2.14 semantic/grain/claim/contribution implementation guide, release/migration notes, architecture assessment, engineering report, or boundary decision.
- **Implemented but undocumented before this change:** candidate semantic context, observation/entity distinction, composite grain, repeated entity-period aggregation, additive contributions, profile reuse and coverage-qualified claim checks.
- **Added and documented in 2.14:** category-share composition comparison and validation of claims about measured composition movement.
- **Documented but missing or incomplete:** a dynamic hypothesis investigation graph, exact composition decomposition, anomaly/structural-break analysis, automatic executive synthesis, model-level quality/latency/cost evidence, and binary PPTX output were not implemented. Docs now state those limits; they are not represented as delivered 2.14 features.
- **Documents updated:** README, CHANGELOG, `docs/architecture.md`, `docs/system-map.md`, `docs/analytical-intelligence.md`, version matrix, version-doc gate, release guidance, and the supported source-window statement.
- **Documents added:** this report, architecture assessment, 2.14 release notes, 2.13-to-2.14 migration guide and ADR-0022.
- **Documents deprecated:** none. Prior-version reports remain historical.

## Known limitations

No live model/provider was available; L3–L5, model latency/tokens and real rendered output remain unmeasured. Semantic candidates are heuristics. General prose truth, broad semantic overclaim, causal explanation, metric units and business definitions still need model/user/source review. Composition decomposition, autonomous staged escalation and general anomaly/change detection are gaps. The synthetic benchmark is one controlled helper workload, not evidence of acceptable real-task performance. No actual deck or report before/after evaluation was available.

## Release recommendation

**NOT READY**

The offline deterministic and lifecycle gates can establish implementation behavior, but the full specification's analytical quality, claim fidelity, responsiveness/cost, composition/anomaly coverage and artifact regression evaluation are not satisfied. Do not interpret a passing `make test` as evidence for those product-level claims.
