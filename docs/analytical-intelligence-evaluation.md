# Analytical Intelligence Evaluation

The evaluation harness measures whether Anvil's analytical behavior is numerically correct, semantically sound, useful, evidence-calibrated, faithful across presentation surfaces, and worth its execution cost. It is a separate observer of production analysis. Production modules do not import fixtures, ground truth, prompts, scoring rules, or evaluators.

The harness follows the 2.14 dependency boundary:

```text
Named dataset → scripts/analysis → evidence-backed AnalysisResult
                                      ├── direct response
                                      └── communication/artifact consumers

Versioned fixture + hidden truth → evaluator → structured evidence and gaps
```

It evaluates the reusable analysis layer first. Artifact rendering is downstream; this harness does not claim a visual or binary PPTX/DOCX/PDF regression test.

## Evaluation levels

| Level | What it measures | Current method |
|---|---|---|
| L1 — Numerical correctness | Counts, distinct keys, cohort membership, deltas, ratios, distribution values, coverage, and contribution | Deterministic comparison to machine-readable facts and tolerances |
| L2 — Semantic correctness | Observation grain, entities, periods, and semantic candidates | Deterministic comparison to fixture semantics and explicit error categories |
| L3 — Analytical discovery | Material findings found without a leading prompt | Blind model runs plus structured human review; lexical coverage is only a provisional diagnostic |
| L4 — Analytical reasoning | Investigation depth, evidence use, support, and claim calibration | Observable model output, deterministic claim checks, and structured human review |
| L5 — Communication fidelity | Preservation of key facts across direct, report, and presentation surfaces | Deterministic checks for declared fact/value/unit parity plus human review |

The levels remain separate. L1/L2 success cannot offset a missed insight, unsupported claim, or distorted communication. L3–L5 are `NOT_REVIEWED`/`NOT_AVAILABLE` when no valid model result or human review exists. The harness never substitutes a judge model for arithmetic that can be computed exactly and does not require hidden chain-of-thought.

## Versioned fixtures and hidden truth

`evals/analytical/fixtures.py` deterministically builds versioned, generic synthetic data with fixed seeds. The checked-in CSV snapshots are the public model inputs. Machine-readable manifests in `ground_truth/` are evaluator-only and contain the expected semantics, operation plan, exact facts/tolerances, material findings, acceptable interpretations, forbidden claims, and known ambiguities. The fixed `blind-analysis-v1.0` prompt asks for the most important evidence-supported findings; it does not name the planted phenomena.

| Fixture | Semantics | Planted evaluation cases |
|---|---|---|
| `operations-v1` | 320 rows; `entity_id × period × product`; 24 unique entities | 20→20 observed populations with 16 retained, 4 entrants and 4 exits; reported mean movement differs from the retained cohort; broad retained improvement; concentrated additive output; stable response mean with worse p95; changing coverage; a real but non-causal correlation |
| `services-v1` | 290 events; `event_id` rows, 18 services, 54 service-zone pairs | Events vs services; composite service-zone identity; different labels and domain from the primary fixture |

Eight checked-in trap snapshots cover 80 rows vs entities, 1,000 events vs users, a composite entity key, a changing cohort, stable average with changed tails, correlation without causality, and two observations that cannot establish a sustained trend. The original `stable-average-tails.csv` snapshot is retained; `stable-average-tails-v2.csv` fixes its mean at 5 in both periods while worsening the upper tail. Tests execute production operations against all traps, not just count their rows. Fixture generation tests byte equality and refuses to replace a changed versioned fixture silently. A material fixture or truth change requires a new versioned fixture and documented rationale.

## Semantic foundation certification

`semantic-foundation-v1` is an additional public input snapshot with 24 independent cases (A–X). Its expected answers are stored separately in `ground_truth/semantic-foundation-v1.json`; the public fixture generator contains no expected roles, entity keys, grain, or answers. Production analysis imports none of this evaluation code. The existing 2.14 deterministic baseline is not rewritten; candidate results use a new protocol ID, `semantic-certification-v1`.

The cases attack repeated entities, event IDs, composite observation/entity keys, technical row IDs, snapshots, event streams, aggregate tables, pure time series, multiple entities, dimensions, numeric identifiers and string measures, missing keys, duplicate rows, non-unique ID-like fields, multiple time fields, stable/changing functional dependencies, high-cardinality dimensions, low-cardinality entities, ambiguous schemas, authoritative metadata and misleading names. The report keeps the metrics separate:

- entity precision, recall, high-confidence precision, false-candidate rate and composite entity-key accuracy;
- grain classification (`EXACT`, `SEMANTICALLY_EQUIVALENT`, `PARTIAL`, `OVER_SPECIFIED`, `UNDER_SPECIFIED`, `WRONG`, `UNKNOWN`) and composite-grain accuracy;
- field-role, event-key, technical-time-role and functional-dependency accuracy, duplicate-risk detection and metadata use;
- confidence observations by HIGH/MEDIUM/LOW/UNKNOWN level, an explicitly mapped Brier score, and abstention accuracy;
- nine metamorphic checks for row shuffle, column order, neutral renaming, technical ID, irrelevant dimension, duplicate data, subsampling, removing time, and adding ingestion time;
- lexical/metadata ablations, sample-size/cardinality/temporal-density sensitivity points, and deliberate bad-output mutations that must lower evaluator scores;
- FAST/STANDARD/DEEP helper timing beside the preserved 2.14 medians.

Run the offline certification and its bounded benchmark:

```bash
make eval-analytical-semantic
make eval-analytical-semantic EVAL_REPS=5
```

The command writes a unique private JSON and Markdown report under `${XDG_STATE_HOME:-~/.local/state}/anvil/evaluations/`. It refuses to overwrite a prior run. Candidate timing is compared with the frozen 2.14 measurements, but the report does not claim that timing variation from a short local run is a product latency guarantee. A passing `READY_FOR_MODEL_EVALUATION` status means the deterministic semantic substrate met its gates; it is not an L3–L5 model-quality or release approval.

Initial deterministic gates are L1=100%, known L2=100%, zero high-confidence entity false positives, 100% known composite-grain accuracy, all metamorphic invariants, correct ambiguity abstention, role/event separation, and all evaluator mutations caught. Broader precision/recall, role, confidence and sensitivity results remain visible rather than being collapsed into one score. If a case is intentionally ambiguous, `UNKNOWN` is scored as correct abstention where hidden truth requires it.

## Deterministic and model-backed modes

Run the offline deterministic suite:

```bash
make eval-analytical
```

This computes the production profile and operations against each fixture, scores L1 exactly, scores L2 separately, checks explicit parity/claim traps, measures FAST/STANDARD/DEEP helper cost, and attempts a 2.13 comparison from an isolated `git archive HEAD`. If HEAD is not a committed 2.13 release or the isolated run cannot be reproduced, the report says `BASELINE_UNAVAILABLE`; no historical number is invented.

Run the installed Anvil agent through the actual OpenCode CLI path with an explicit model and repeated independent runs:

```bash
make eval-analytical-model MODEL=provider/model RUNS=3
make eval-analytical-full MODEL=provider/model RUNS=3
```

Each run has a fresh temporary workspace containing the named dataset copy and restrictive project policy. It resolves the supported Anvil-managed OpenCode executable from runtime state even when it is absent from `PATH` (`OPENCODE_BIN` or `--opencode-bin` can explicitly override discovery). It uses the installed `anvil` agent and installed analysis helper; the agent may edit only its plan file and run only the fixed profile/execute helper commands against that dataset. The ground-truth manifest, repository checkout, prior run history, and score rules are excluded. The runner bounds time and output, stops the child process group on timeout, and records model/runtime, duration, tool/token usage when OpenCode reports it, fixture and helper hashes, prompt version, and generated policy hash. It supports OpenCode 1 and 2 policy schemas. Missing runtime, helper, or provider access marks model runs `BLOCKED` while preserving deterministic results; it does not turn offline success into live-model success.

The standard-library test suite does not make network calls or depend on a configured provider. `make test` includes deterministic harness contracts. Live model execution is opt-in and may send the named dataset and prompt to the selected provider.

## Metrics and failure classification

The result contains L1–L5 independently, exact numerical and semantic scores, semantic error rate, and a typed failure list. Numerical fact scoring uses explicit expected values and tolerances. Model discovery recall/precision, unsupported-claim rate, claim calibration, materiality, investigation sufficiency, and communication fidelity require a structured reviewer; lexical phrase matching is not presented as authoritative semantic scoring.

Failure classes are `NUMERICAL`, `GRAIN`, `ENTITY_RESOLUTION`, `SEMANTIC`, `POPULATION`, `COHORT`, `COMPOSITION`, `DISTRIBUTION`, `DISCOVERY`, `INVESTIGATION`, `CONTRIBUTION`, `MATERIALITY`, `CLAIM_SUPPORT`, `CLAIM_CALIBRATION`, `COMMUNICATION`, `PERFORMANCE`, and `INFRASTRUCTURE`. The gap report ranks observed failures by severity and frequency and proposes candidate follow-up capabilities with impact and complexity. Recommendations are evidence for human engineering decisions; the evaluator never changes production code or implements its own roadmap.

The quality/cost report presents L1/L2 beside the 10,000-row FAST helper latency and any observed model duration, calls, and tokens. It does not collapse these into one score. The north star is material findings per unit of execution cost, not “more analysis” or more tool calls. CPU and wall time are measured for deterministic helper stages. FAST profiling and execution are timed separately, with semantic inference attributed specifically within FAST. The classification is `NECESSARY_CORRECTNESS_COST`, `UNNECESSARY_EAGER_WORK`, `MIXED`, or `UNKNOWN`; at least three repetitions for both 2.13 and 2.14 are required for a classification, otherwise it is `UNKNOWN`. Attribution is observational, not an ablation proving every measured operation necessary.

## Human review and communication parity

A model result can produce a `review-template.json`. Annotate candidate finding matches, missed material findings, claim support/calibration, semantic errors, materiality, investigation sufficiency, and communication issues. Apply it as a new artifact:

```bash
make eval-analytical-review REPORT=/path/to/report.json REVIEW=/path/to/completed-review.json
```

Review outputs are additive; source run artifacts are not rewritten. The automated parity check catches contradictory fact IDs, values, and units among declared direct/report/presentation surfaces. It does not invoke actual presentation renderers or prove visual fidelity. Human review remains required for narrative meaning and real artifacts.

## Immutable baseline and historical comparison

After the deterministic methodology and fixture versions have been reviewed, freeze the complete 2.14 baseline once:

```bash
make eval-analytical-baseline
```

This records exact fixture and ground-truth hashes, candidate revision and source fingerprints, the fixed prompt/evaluator versions, deterministic scores, performance samples, and the 2.13 comparison (or explicit unavailability). The checked-in baseline is created with exclusive file creation and cannot be silently overwritten. A changed fixture, ground truth, scoring method, or prompt needs a new versioned baseline rather than mutation of history. Generated per-run reports remain local and outside the repository.

## Private real-case evaluation

The CLI also accepts one explicitly named local dataset and a matching local JSON manifest. The manifest uses the same `fixture.id`, `fixture.version`, semantics, `expected_facts`, `material_findings`, `acceptable_interpretations`, `forbidden_claims`, `known_ambiguities`, `evaluation_plan`, and `fact_bindings` contract as a synthetic fixture. Its evaluation plan must be pinned to the exact dataset SHA-256. Example:

```bash
make eval-analytical DATASET=/private/case.csv GROUND_TRUTH=/private/case-review.json FIXTURE=case-v1
make eval-analytical-model DATASET=/private/case.csv GROUND_TRUTH=/private/case-review.json FIXTURE=case-v1 MODEL=provider/model RUNS=3
```

Keep private data and its manifest outside Git. Run artifacts have owner-only directory/file permissions and store derived model output and findings, so protect the chosen state directory and provider account as you would the input data. The model mode sends the dataset copy to the explicitly selected model provider. Do not use a private case with a provider that is not approved for that data.

## Artifacts and reproducibility

By default each invocation writes a unique directory under `${XDG_STATE_HOME:-~/.local/state}/anvil/evaluations/`. It contains `summary.md`, `report.json`, `runs.json`, `failures.json`, `performance.json`, `gaps.json`, and review templates as applicable. Files use mode `0600`; run directories use `0700`; existing results are never overwritten. No raw dataset is copied into the result directory.

The structured result records UTC run time, Anvil version and Git revision, source fingerprints, fixture version/seed/data hash, ground-truth hash, evaluation/prompt versions, model/runtime where used, controlled execution-policy fingerprint, elapsed time, and available call/token counts. Secret values and provider credentials are not captured.

## How results should guide development

First establish reproducible failures and their frequency. Separate a wrong `AnalysisResult` from a downstream communication mismatch. Confirm model findings and claim labels with human review, especially when phrasing varies or the fixture has ambiguity. Then select the smallest follow-up capability that addresses a recurring, high-impact gap. Do not add hypothesis escalation, broad anomaly detection, exact composition decomposition, or domain heuristics simply because they sound useful; implement them only when repeated measured failures support that investment.

Synthetic fixtures provide controlled checks, not proof of ecological validity. The private-case path is intended to support a future human-reviewed golden set without committing organization-specific data.
