# Anvil 2.14.0 — Analytical Intelligence Architecture Assessment

## Scope and approach

The 2.14 audit started from the checked-out source and the existing 2.13 architecture, not from a greenfield design. It traced the `make` and installed-helper paths, the `anvil-communication` skill, tabular profile/plan/result contracts, quantitative communication helpers, artifact adapter, managed package installation, runtime profiles, lifecycle transactions, fixture tests, release matrix and user documentation.

The product boundary is now explicit: analyze named evidence once into a bounded, source-pinned result; let terminal responses and communication/artifact consumers use the same evidence. Semantic inference stays task-local and uncertain. This is a small standard-library package and adapter relocation, not a semantic catalog, BI platform, new agent, or service.

## Existing implementation audit

| Existing responsibility | Classification | 2.14 treatment |
| --- | --- | --- |
| `scripts/analysis` request, plan, bounded table profile, primitive calculations, evidence, findings and Pareto materiality | KEEP / GENERALIZE | Retained the existing contracts; added semantic candidates, shared statistics, composite-key distinct counts, entity-period cohort aggregation, additive contribution and validation against executed evidence. |
| `scripts/analysis/adapter.py` importing communication contracts | MOVE | Relocated the consumer adapter to `scripts/communication/analysis_adapter.py`; analysis core has no communication/artifact import. |
| `scripts/communication/quantitative.py` change/distribution arithmetic | REUSE | Delegates shared arithmetic to `scripts/analysis/statistics.py`; keeps unit, epistemic, audience and presentation policy. |
| Lazy `anvil-communication` task workflow | KEEP / GENERALIZE | Continues to decide relevance, depth, interpretation and narrative; now documents direct analytical answers and reusable profile/result flow. |
| Existing artifact contracts, editorial planning, Markdown and SVG renderers | KEEP | Remain consumers; no new PowerPoint or binary-document renderer is claimed. |
| OpenCode profiles, lifecycle ownership manifest, transaction, rollback, memory and Databricks setup | KEEP | No runtime/profile/schema/dependency change; managed package discovery and lifecycle fixtures cover the added modules. |
| Analytical evaluation harness | ADDED | `evals/analytical/` provides synthetic blind fixtures, evaluator-only manifests, deterministic scoring, isolated optional OpenCode runs, structured review and immutable results. |
| Live model quality and rendered artifact benchmark | NOT MEASURED | No OpenCode runtime/provider was available for a live run in this implementation environment; no actual rendered presentation before/after review is performed by the harness. These remain release blockers. |

## Realigned responsibilities

```text
Named local evidence
        ↓
Analysis core: profile → candidate semantics → validated plan → calculations
        ↓
Evidence, hypotheses, claim checks, findings, provenance and execution metadata
        ├── terminal answer
        └── communication adapter → report / supported artifact
```

The analysis module does not render, write memory, discover files, make network/model calls, or persist task results. The communication adapter imports analysis output, never the reverse. The existing profile/plan/result API was retained instead of introducing a new framework.

## Implemented analytical scope

Semantic profiling reports observation counts separately from candidate entity cardinality; repeated values and temporal repetition; unique and bounded composite row-key candidates; temporal, dimension and measure candidates; candidate metric templates/questions; and missing/duplicate-key limitations. These are heuristic candidates with bounded confidence, not certified business semantics.

The deterministic layer supports distinct counts over composite keys, grouping, change/distribution summaries, trend thresholds, coverage, category-share composition comparison, repeated entity-period cohort comparison, and additive sum/count contribution. Cohorts expose retained, added, removed and unkeyed populations and aggregate repeated rows inside an entity-period before like-for-like comparison. Composition reports category shares and optional category/overall measures so mix movement is visible. Contribution exposes signed net and absolute movement shares; neither operation claims causality or performs exact mean/rate decomposition.

Result checks bind operations and evidence to the source hash and validated plan. They can reject or qualify observation/entity count mismatches, trend language without at least three periods, unsupported like-for-like or breadth statements, coverage shifts, and causal claims presented as facts. General prose receives structural and reference checks only; natural-language truth is not machine-proven.

## Deliberately limited or not implemented

- Metric discovery emits a small set of candidate templates/questions; it does not autonomously run a complete metric neighborhood or select findings by a learned materiality model.
- Cohort comparison, category-share movement, and additive contribution are implemented; exact within-population/composition decomposition for rates/means and causal attribution are not.
- No general anomaly detector, structural-break/seasonality detector, schema-drift service, arbitrary join engine, remote data provider, Databricks query workflow, semantic catalog, or general BI engine was added.
- FAST/STANDARD/DEEP remain validated per-plan question/operation budgets. The helper does not yet dynamically execute or escalate a multi-stage hypothesis graph. The skill guides the model to choose relevant operations.
- The deterministic `AnalysisResult` contract validates assembled results, but the CLI does not generate an executive narrative/findings automatically. The existing agent remains responsible for semantic interpretation and synthesis.
- No binary PPTX/DOCX/PDF or quantitative-chart renderer was added. Existing Markdown/SVG and artifact contracts remain intact.

These limits are intentional boundaries or known gaps, not claims that the full research-like workflow in the specification is complete.

## Evaluation boundary

The separate `evals/analytical/` package measures the production analysis helper without importing fixture truth into production. Offline scoring detects exact fact correctness and semantic-candidate gaps; optional model runs use an isolated workspace and blind prompt. L3 discovery, L4 reasoning/claim calibration and L5 communication fidelity remain unmeasured until model results receive structured human review. The evaluation package does not add production analytical behavior. See the [analytical evaluation guide](analytical-intelligence-evaluation.md).

## Documentation audit

The pre-change docs described the 2.13 profile/operation adapter but did not document explicit grain/entity candidates, composite keys, repeated entity-period aggregation, additive contribution, claim checks tied to execution, or source-profile reuse. README, system map, lifecycle architecture, changelog, capability matrix and release links still identified 2.13 as current. They were corrected for 2.14; the analytical guide was expanded; release/migration/assessment/report/ADR documents were added. This evaluation phase added a dedicated harness guide and current evidence status. Historical 2.13 assessment and release records remain unchanged as history.

No active public doc was found claiming a general BI engine or binary PPTX renderer. The documentation now explicitly says such capabilities are absent. The capability matrix describes the 2.14 additions separately from OpenCode runtime generation.
