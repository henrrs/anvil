---
name: anvil-communication
description: Use for bounded, evidence-backed analysis of explicitly authorized data and for turning source evidence/findings into reports, presentations, summaries, architecture diagrams, or for reviewing communication artifacts. Includes task-intent preservation, deterministic table profiling and analysis, semantic question selection, editorial planning, six audience lenses, Markdown materialization, semantic visual intent, and SVG validation. Keep it lazy: do not use for routine prose/code edits, trivial calculations, or simple tasks that do not need data analysis.
---

# Anvil Communication & Artifact Intelligence

Use the local core at `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/artifacts.py` when installed. In an Anvil repository checkout, use `scripts/artifacts.py`. The core is runtime-independent and uses only Python's standard library; optional PDF extraction uses `pdftotext` when available.

## Required reasoning order

```text
Intent and hard constraints
  → named input inventory
  → targeted evidence with provenance
  → findings and unknowns
  → deterministic quantitative interpretation
  → audience-specific thesis and storyline
  → artifact plan/pilot where useful
  → Markdown/SVG materialization
  → deterministic checks + semantic review
```

For a data task, analysis is independent of artifact format and precedes the existing evidence-to-artifact flow:

```text
Original request → task brief → deterministic profile → semantic model/questions
  → bounded plan → deterministic operations → typed evidence/findings
  → materiality and narrative → response or existing artifact plan
```

This path is available for a direct terminal/chat answer. Do not create an artifact as a prerequisite. Keep `TaskBrief.original_request` authoritative, and use the same validated findings if the user later asks for a report or presentation.

## Intent compilation and adaptive analysis

- Keep short code, writing, and explanation requests on the ordinary direct path. Do not profile data, create a brief, or invoke analysis helpers unless the task benefits from evidence exploration.
- For a material or underspecified analytical request, preserve the exact original request in `TaskBrief.original_request`. Separate explicit requirements from derived quality refinements. Derived requirements need a short rationale and may not broaden the requested objective. Ask only when an unresolved ambiguity could materially change the answer or action.
- Keep the brief, profiles, plans, evidence, and findings in the current task context or private temporary working files. Never store one-off analytical results in Anvil memory.
- Profile only named/authorized local sources. Use the installed `scripts/analyze.py` helper, or the checkout copy, for deterministic local table work. It does not recurse, write files, contact a model, or require Databricks:

  ```bash
  python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/analyze.py" profile ./named-data.csv
  python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/analyze.py" execute ./named-data.csv analysis-plan.json --profile profile.json
  ```

- Supported tables are UTF-8 CSV, TSV, JSON arrays of flat row objects, and JSON Lines. Inputs are capped at 32 MiB, 100,000 rows, 200 columns, and 250,000 profile cells. A profile can report exact total rows with prefix-sampled column statistics when it exceeds its profile row budget; do not represent those statistics as complete. Plan execution stops rather than silently calculate over a partial prefix. Nested or duplicate JSON fields, unsupported encodings, missing columns, changed input, and symlink paths remain explicit blockers.
- The profile includes a bounded `semantic_context`: exact observation count; entity, event, technical and candidate keys; bounded observation grain; time roles; dimensions; measures; confidence; supporting/contradicting evidence; ambiguity; quality risks; and candidate questions/metrics. These are evidence-based hypotheses, not a business semantic layer. An observation is a recorded row at the observed grain. An entity is a persistent object; an entity key identifies it; an event key identifies an occurrence; a candidate key is only observed uniqueness; and grain describes what one row represents. Do not collapse these concepts.
- A unique row/event ID is not automatically an entity. A dimension is not an entity because it repeats or has high cardinality. Numeric type alone does not establish a measure, and an ID-like name does not establish a key. Composite entity keys and composite observation grain are possible. Snapshot data can support entity candidates without temporal recurrence. Ingestion/processing timestamps are not business time unless source semantics establish that role.
- Respect `HIGH`/`MEDIUM`/`LOW`/`UNKNOWN` confidence and concise supporting/contradicting evidence. When evidence is insufficient, retain `UNKNOWN`; do not turn row count, a low-confidence key, or the first candidate into a definitive population claim. Source metadata can strengthen role inference, but a database primary key may still identify an event or record rather than a persistent analytical entity. Deterministic candidates do not establish business meaning or units.
- When a profile is sampled, counts and grain describe only the profiled prefix. Use the actual entity key fields in `distinct_count` and `cohort`, including all fields for a composite key; do not substitute observation count or event-key cardinality for entity count. If uncertainty materially affects the answer, qualify it or ask for the source meaning.
- Preserve the profile JSON in a private task-local location and pass it as `--profile` when executing the plan. The helper verifies source path, SHA-256 and row count before reusing its semantic inference. This avoids repeating semantic profiling while still re-reading the named source for deterministic calculation.
- Generate only questions grounded in the task and profile. Consider magnitude, change, trend, distribution, composition, concentration, coverage, segmentation, relationships, and exceptions where relevant; do not run every lens mechanically. If population membership can change, check population size/coverage and use `cohort` for common/added/removed entities when stable entity IDs exist. Cohort calculations aggregate repeated rows within entity and period before comparing like-for-like values; use `entity_columns` for a composite entity key. Compare aggregate change with the common cohort before attributing a shift to performance. Use `contribution` only with additive `sum` or non-null `count`; do not present a contribution decomposition for a non-additive mean. Do not claim a numeric composition/performance decomposition unless separately computed.
- Choose depth from user wording, decision importance, ambiguity, available evidence, and profile complexity. FAST allows at most 4 questions/operations, STANDARD 12, and DEEP 20. Plan execution is bounded to 100,000 rows, 100 groups per expansion, two grouping dimensions, and 100 ranked categories. FAST is a sensible default for a focused summary; use DEEP only when requested or justified. Stop when the main question is answered, additional analysis is unlikely to alter the conclusion, evidence is insufficient, or a budget is reached.
- Use supported deterministic operations (`count`, `distinct_count`, `sum`, `mean`, `median`, `percentile`, `min`, `max`, `ratio`, `share`, `delta`, `delta_percent`, `delta_percentage_points`, `rank`, `top_n`, `bottom_n`, `distribution`, `trend`, `volatility`, `coverage`, `cohort`, `concentration`, `contribution`, `correlation`). Use `distinct_count` with `columns` for a composite key. Do arithmetic, grouping, ranking, and validation through the helper, not model mental math. Ratios require a meaningful denominator; relative change is unknown for missing/non-positive baselines. Numeric distributions retain median, quartiles, tail percentiles, range, and a simple 1.5-IQR outlier count. Correlation is association, never causal evidence.
- Two temporal observations support a comparison, not a trend. Use three or more points before describing a trend, and qualify short or irregular coverage. Compare units and periods before combining metrics. Missing remains unknown, never zero.

## Findings, materiality, and narrative

- Separate OBSERVED, DERIVED, INTERPRETED, HYPOTHESIS, and UNKNOWN findings. Every non-unknown finding must cite evidence IDs. Evidence retains the input locator/hash and, for deterministic operations, its operation, method, and bounded result data. A hypothesis remains a hypothesis even when plausible.
- For important claims, include `claims` in the analysis result and run `validate-result`. The validator checks observation count against `count`, entity count against `distinct_count` and the stated key fields, trend claims against at least three observed points, like-for-like claims against a cohort operation, and broad-based claims against an explicit retained-entity threshold. It rejects deterministic claims that confuse rows with entities and causal claims not classified as hypotheses. General prose is only structurally/evidence-reference checked, not proven true by the helper.
- Assess competing explanations for material movement, including composition, coverage, ownership, measurement/data quality, and time-window differences when the source can distinguish them. Do not investigate unsupported possibilities indefinitely.
- Give findings a rationale and separate HIGH/MEDIUM/LOW/UNKNOWN materiality dimensions for magnitude, breadth, persistence, decision relevance, confidence, exception severity, and novelty. The helper forms transparent Pareto tiers; it does not calculate a weighted universal score. Select primary narrative findings by their decision value and evidence quality, and explain meaningful exclusions.
- Build the conclusion and narrative before choosing a report or slide structure. State what changed, why it matters, what explains it, what remains unresolved, and a possible action only when supported. Unknown is a valid result. Artifact generators consume validated findings; they do not discover the analysis or change its numerical meaning.

Renderer code does not select business meaning. Quantitative code does not select layouts. Never start by choosing slides or charts.

## Scope and privacy

- Analyze only paths and remote sources the user named or explicitly authorized. A directory is not permission to crawl unrelated roots. Run `discover PATH...` first; recursive traversal requires the user to name the directory as the scope and the `--recursive` flag.
- `discover` returns metadata and hashes, not source bodies. Extract only relevant sources and ranges with `extract`. Extractions are bounded; notes state when a source is partial, has unsupported embedded media, or was truncated.
- Supported text analysis includes Markdown/text, CSV/TSV, JSON, JSONC as text, common source/config files, and OOXML DOCX/PPTX/XLSX text. PDF text extraction is optional. Do not claim charts, images, speaker notes, formulas, scanned pages, or embedded objects were analyzed unless an adapter actually extracted them.
- Do not persist raw sources, query results, evidence, or one-off findings in Anvil memory. Do not log them. Write only the artifact the user requested, to the named or agreed output path. Do not overwrite an existing output without explicit approval; `--force` means the user has explicitly approved replacement.
- Databricks analysis uses existing Anvil capabilities only when the user requests remote evidence. Keep queries read-only and bounded; do not change compute or workload configuration. If access or telemetry is unavailable, report the unknown and continue only when the remaining evidence supports a useful result.

## Evidence and findings

Keep evidence separate from findings. Every evidence item needs a stable ID, concise claim, epistemic type, confidence, and source provenance (`type`, `locator`, and SHA-256 when the local source was hashed). Keep a useful line, slide, worksheet, table, query, period, or section locator. Do not copy a large source body into the plan.

Use these epistemic distinctions (legacy aliases remain accepted):

`OBSERVED` (`FACT`, `MEASUREMENT`, `OBSERVATION`), `CALCULATED` (`DERIVED_VALUE`), `ESTIMATED` (`ESTIMATE`), `SCENARIO`, `INFERRED` (`INFERENCE`), `ASSUMPTION`, `PROJECTION`, `PROPOSAL`, and `UNKNOWN`.

Confidence is `HIGH`, `MEDIUM`, `LOW`, or `UNKNOWN`. Do not promote model prior, correlation, an estimate, or a projection into a measured fact. Conflicts and unknowns remain explicit. Findings reference evidence IDs; proposals/unknowns may be unbacked, but must be labeled as such.

## Quantitative analysis

Represent measurements in a separate JSON file in a private temporary directory, then run `artifacts.py quantify metrics.json`. Example:

```json
{
  "metrics": [{
    "id": "QI-cost",
    "name": "Monthly compute cost",
    "kind": "amount",
    "unit": "BRL",
    "semantics": "lower_is_better",
    "baseline": {"value": "1200000", "unit": "BRL", "period": "previous 30 days", "evidence_ids": ["E-cost-before"]},
    "current": {"value": "870000", "unit": "BRL", "period": "last 30 days", "evidence_ids": ["E-cost-now"]},
    "annualize": {"period_days": 30, "assumption": "The observed monthly reduction persists for twelve months."}
  }]
}
```

Use decimal strings where source precision matters. Baseline semantics and source IDs must be explicit. `kind: rate` with a percent unit produces a separate percentage-point delta and relative change. Zero, near-zero, and negative baselines have no default relative change. Missing remains unknown, never zero. Normalization requires a measured denominator. Distribution summaries retain outliers and state any explicit exclusions. Projection output remains `PROJECTION` and requires its persistence assumption. If units or baselines are ambiguous, do not guess; ask only if the ambiguity changes the conclusion.

The comparison question matters: absolute impact and relative improvement may rank the same workloads differently. Interpret direction only when metric semantics support it. Choose visual form from the question (trend, ranking, distribution, composition, target/actual, delta, etc.), not merely from the presence of numbers.

## Audience, purpose, and constraints

Keep audience (`executive`, `financial`, `technical_leadership`, `engineering`, `technical`, or `mixed`) separate from tone. Current explicit user constraints override policy, relevant memory, and defaults. Hard constraints must validate; soft preferences guide selection. Detect conflicts instead of silently dropping a requirement. Use `constraints PLAN.json --prompt 'original request'` to validate the contract and catch unambiguous exact slide-count/measured-only constraints.

Executive communication leads with decision, material impact, risk, and action. Financial communication keeps observed actuals distinct from projections and capture scenarios. Technical leadership foregrounds architecture, scale, reliability, constraints, and trade-offs. Engineering communication retains mechanism, method, runtime evidence, diagnostics, raw measurements, and interfaces. Technical communication preserves baseline, distributions, uncertainty, and alternatives; mixed communication uses progressive disclosure. Preserve raw precision in the data contract and select audience-appropriate presentation precision. State why quantitative evidence, storyline points, or exclusions matter. Titles should assert the message; a slide should carry one primary point.

For substantial work, produce a concise plan/pilot (audience, purpose, constraints, thesis, storyline, selected evidence, unknowns, and artifact structure) before lengthy rendering when the request leaves a material choice open. Do not add a user gate to simple requests or when the user explicitly asked for the final artifact.

## Artifact contract and materialization

Create a schema-version-1 JSON plan with:

- `request`: `artifact` (`report`, `presentation`, or `summary`), audience, purpose, tone, language, optional minutes, and constraints;
- `thesis`, ordered `storyline`, selected/excluded evidence rationale;
- `evidence`: ID, claim, epistemic, confidence, and source provenance;
- `findings`: ID, claim, epistemic, confidence, supporting `evidence_ids`, implications/limitations, audience relevance, and insight IDs;
- `quantitative_insights`: output of deterministic `quantify`, unchanged;
- optional `editorial`: decision context, materiality note, and appendix finding/insight/evidence IDs;
- for reports/summaries, human-readable `sections`; for presentations, exactly the planned `slides`, each with role/title/body and finding/evidence/insight IDs;
- optional section/slide `visual_intent`: semantic relationship/form, primary message/evidence, supporting evidence, prominence, semantic color roles, and storyboard. Keep coordinates and raw colors in renderer-owned layers;
- optional artifact metadata with stable ID, plan version, theme, renderer, and creation time. Never embed raw query results or secrets.

Run `constraints PLAN.json` and resolve any hard error. Render `.md` with `materialize PLAN.json --output PATH.md`; presentation output is a constrained Markdown slide outline, not a binary PowerPoint. Run `review PATH.md --plan PLAN.json`, then read the materialized artifact and perform semantic review for unsupported claims, argument flow, audience fit, quantitative integrity, and clear qualifications. Correct issues and rerun the relevant checks. The renderer's structural PASS is not proof of semantic truth.

Run `python3 scripts/artifacts.py critique PLAN.json` for an optional deterministic editorial pass. Treat signals as review prompts, not automatic rejection. Check materiality, the supported so-what implication, counter-evidence, alternatives, assertion titles, editorial reduction, primary-message hierarchy, and audience fit. Do not expose private reasoning; return only useful artifact changes or concise findings.

Cards are one possible form for independent peer items, not the default. Match representation to the evidence relationship, vary prominence according to the storyline, and use color only for a meaningful semantic distinction. Animate only when time carries information; storyboard at least two distinct states. If the renderer cannot animate, preserve the sequence and report its static fallback.

For architecture, create a renderer-independent semantic diagram JSON with one question, one viewpoint, abstraction level, typed nodes/relationships, epistemic status, evidence IDs, and a separate layout block. Labels and provenance remain in the model. State `current` versus `proposed` explicitly. Use semantic color roles, not arbitrary hex values; labels/state are always redundant to color. Run `diagram MODEL.json --output VIEW.svg`, then `review-diagram VIEW.svg --model MODEL.json`. A crossing relationship through an unrelated node is a hard layout failure. Split views instead of mixing context, component, deployment, security, and runtime flow into one diagram.

Binary DOCX/PPTX/PDF rendering is not currently available. Do not claim to have produced one; offer validated Markdown and SVG or clearly report `RENDERER_UNAVAILABLE`. D2/Graphviz are optional future renderer capabilities, never semantic sources of truth.

## Semantic review and iteration

Use `/review` or `review` for existing Markdown/SVG plus the optional source plan. Deterministic review checks structure, hard counts, references, percentage-point wording, projection qualifications, placeholder/generic titles, and SVG validity/measurable geometry; `critique PLAN.json` also reports bounded editorial signals. Neither proves semantic correctness. Also inspect claims, counter-evidence and alternatives, source relevance/conflicts, baseline choice, method, causality, distribution, normalization, visual distortion, accessibility, title-only narrative, and requested audience. Return specific findings and recommended edits; don't rewrite unless the user requested edits.

For iteration, reuse validated evidence and quantitative insights when source hashes and question remain valid. Feedback about a number changes evidence/quantitative analysis; the message changes thesis/storyline; audience changes communication policy; density changes materialization/layout. Re-run only downstream stages affected by the feedback.

## Editorial and composition judgment

Interpret a value only in trustworthy context: compare it with an observed baseline, target, threshold, denominator, range, sample size, or other relevant reference. If the comparison is unavailable, keep the result unknown or describe only the observed change. Do not invent a benchmark or call a result good, bad, critical, healthy, or abnormal without support. Separate the finding (what evidence shows), insight (what the relationship suggests), and implication (what it changes). Give changes emphasis in proportion to materiality and confidence.

Edit for the argument. Merge or remove redundant claims and slides; move useful but secondary evidence to an appendix. Slide count and the presence of numeric data do not justify another slide or chart. Let one material finding dominate when the evidence is asymmetric. Keep space open when it improves focus. Prefer direct annotation beside the relevant evidence over a separate generic highlights box. Choose a visual only when its geometry helps the audience perceive a relationship faster than a concise statement or table.

Reason about the actual relationship before selecting a visual form: sequence, dependency, feedback, concentration, divergence, accumulation, transformation, trade-off, or another relationship supported by the evidence. A chart should answer a clear question and make the relevant difference perceptually useful; consider a hero number, delta, annotated timeline, ranked list, table, prose, or no visual. Vary composition to fit the argument instead of repeating equal cards, pills, banners, and density by default. Whitespace is part of hierarchy.

Use one lightweight editorial pass for substantial artifacts: state the central argument, identify the least useful repeated element, check whether each visual adds understanding, verify that context supports the emphasis, and ask whether any animation step changes what the viewer understands. For motion, storyboard the progression first; every step should reveal evidence, a dependency, a decision, a feedback path, or a changed state. Prefer a strong static explanation when time adds no meaning. Keep this review proportional and return concise corrections rather than a checklist dump.
