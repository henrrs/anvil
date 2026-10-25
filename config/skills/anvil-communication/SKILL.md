---
name: anvil-communication
description: Use for turning explicitly authorized documents, repositories, data, and prior findings into evidence-backed reports, executive or technical presentations, summaries, architecture diagrams, and for reviewing existing communication artifacts. Includes deterministic quantitative analysis, audience/constraint planning, Markdown materialization, and SVG architecture validation. Do not use for routine prose edits or ordinary code changes that do not require evidence synthesis or artifact review.
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

Renderer code does not select business meaning. Quantitative code does not select layouts. Never start by choosing slides or charts.

## Scope and privacy

- Analyze only paths and remote sources the user named or explicitly authorized. A directory is not permission to crawl unrelated roots. Run `discover PATH...` first; recursive traversal requires the user to name the directory as the scope and the `--recursive` flag.
- `discover` returns metadata and hashes, not source bodies. Extract only relevant sources and ranges with `extract`. Extractions are bounded; notes state when a source is partial, has unsupported embedded media, or was truncated.
- Supported text analysis includes Markdown/text, CSV/TSV, JSON, JSONC as text, common source/config files, and OOXML DOCX/PPTX/XLSX text. PDF text extraction is optional. Do not claim charts, images, speaker notes, formulas, scanned pages, or embedded objects were analyzed unless an adapter actually extracted them.
- Do not persist raw sources, query results, evidence, or one-off findings in Anvil memory. Do not log them. Write only the artifact the user requested, to the named or agreed output path. Do not overwrite an existing output without explicit approval; `--force` means the user has explicitly approved replacement.
- Databricks analysis uses existing Anvil capabilities only when the user requests remote evidence. Keep queries read-only and bounded; do not change compute or workload configuration. If access or telemetry is unavailable, report the unknown and continue only when the remaining evidence supports a useful result.

## Evidence and findings

Keep evidence separate from findings. Every evidence item needs a stable ID, concise claim, epistemic type, confidence, and source provenance (`type`, `locator`, and SHA-256 when the local source was hashed). Keep a useful line, slide, worksheet, table, query, period, or section locator. Do not copy a large source body into the plan.

Use only these epistemic labels:

`FACT`, `MEASUREMENT`, `OBSERVATION`, `DERIVED_VALUE`, `INFERENCE`, `ESTIMATE`, `ASSUMPTION`, `PROJECTION`, `PROPOSAL`, `UNKNOWN`.

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

Keep audience (`executive`, `technical`, or `mixed`) separate from tone. Current explicit user constraints override policy, relevant memory, and defaults. Hard constraints must validate; soft preferences guide selection. Detect conflicts instead of silently dropping a requirement. Use `constraints PLAN.json --prompt 'original request'` to validate the contract and catch unambiguous exact slide-count/measured-only constraints.

Executive communication leads with decision, material impact, risk, and action; technical communication preserves method, baseline, distributions, alternatives, and operational detail; mixed communication uses progressive disclosure. Preserve raw precision in the data contract and select audience-appropriate presentation precision. State why quantitative evidence, storyline points, or exclusions matter. Titles should assert the message; a slide should carry one primary point.

For substantial work, produce a concise plan/pilot (audience, purpose, constraints, thesis, storyline, selected evidence, unknowns, and artifact structure) before lengthy rendering when the request leaves a material choice open. Do not add a user gate to simple requests or when the user explicitly asked for the final artifact.

## Artifact contract and materialization

Create a schema-version-1 JSON plan with:

- `request`: `artifact` (`report`, `presentation`, or `summary`), audience, purpose, tone, language, optional minutes, and constraints;
- `thesis`, ordered `storyline`, selected/excluded evidence rationale;
- `evidence`: ID, claim, epistemic, confidence, and source provenance;
- `findings`: ID, claim, epistemic, confidence, supporting `evidence_ids`, implications/limitations, audience relevance, and insight IDs;
- `quantitative_insights`: output of deterministic `quantify`, unchanged;
- for reports/summaries, human-readable `sections`; for presentations, exactly the planned `slides`, each with role/title/body and finding/evidence/insight IDs;
- optional artifact metadata with stable ID, plan version, theme, renderer, and creation time. Never embed raw query results or secrets.

Run `constraints PLAN.json` and resolve any hard error. Render `.md` with `materialize PLAN.json --output PATH.md`; presentation output is a constrained Markdown slide outline, not a binary PowerPoint. Run `review PATH.md --plan PLAN.json`, then read the materialized artifact and perform semantic review for unsupported claims, argument flow, audience fit, quantitative integrity, and clear qualifications. Correct issues and rerun the relevant checks. The renderer's structural PASS is not proof of semantic truth.

For architecture, create a renderer-independent semantic diagram JSON with one question, one viewpoint, abstraction level, typed nodes/relationships, epistemic status, evidence IDs, and a separate layout block. Labels and provenance remain in the model. State `current` versus `proposed` explicitly. Use semantic color roles, not arbitrary hex values; labels/state are always redundant to color. Run `diagram MODEL.json --output VIEW.svg`, then `review-diagram VIEW.svg --model MODEL.json`. A crossing relationship through an unrelated node is a hard layout failure. Split views instead of mixing context, component, deployment, security, and runtime flow into one diagram.

Binary DOCX/PPTX/PDF rendering is not currently available. Do not claim to have produced one; offer validated Markdown and SVG or clearly report `RENDERER_UNAVAILABLE`. D2/Graphviz are optional future renderer capabilities, never semantic sources of truth.

## Semantic review and iteration

Use `/review` or `review` for existing Markdown/SVG plus the optional source plan. Deterministic review checks structure, hard counts, references, percentage-point wording, projection qualifications, placeholder/generic titles, and SVG validity/layout. It cannot prove semantic correctness. Also inspect claims, source relevance/conflicts, baseline choice, method, causality, distribution, normalization, visual distortion, accessibility, title-only narrative, and requested audience. Return specific findings and recommended edits; don't rewrite unless the user requested edits.

For iteration, reuse validated evidence and quantitative insights when source hashes and question remain valid. Feedback about a number changes evidence/quantitative analysis; the message changes thesis/storyline; audience changes communication policy; density changes materialization/layout. Re-run only downstream stages affected by the feedback.
