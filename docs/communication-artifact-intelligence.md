# Communication & Artifact Intelligence

Anvil's communication capability turns explicitly authorized sources into a defensible explanation and then materializes that explanation into a supported artifact. Natural language remains the primary interface; the helper performs deterministic work and does not replace the model's source reasoning.

The target flow is **Evidence → Finding → Analysis → Insight → Decision Relevance → Audience → Storyline → Editorial Judgment → Visual Intent → Materialization → Critic/QA**.

## Responsibility flow

```text
User intent and constraints
        ↓
Named input inventory → bounded, targeted extraction
        ↓
Evidence records → findings and unknowns
        ↓
Quantitative interpretation → audience-specific thesis and storyline
        ↓
Validated artifact plan → Markdown / SVG renderer
        ↓
Deterministic checks + semantic review
```

`config/skills/anvil-communication/SKILL.md` teaches the single Anvil agent this workflow. The generic `/review` command operates on explicitly named artifacts. `scripts/communication` contains the standard-library deterministic core, and `scripts/artifacts.py` is its CLI. There are no communication-specific Make targets, agents, background jobs, memory writes, or required Python packages.

The initial architecture audit is recorded in [communication-artifact-assessment.md](communication-artifact-assessment.md). The design decision is [ADR-0015](decisions/ADR-0015-communication-artifact-intelligence.md).

## Contracts and provenance

Plans use schema version 1. An artifact plan contains a request, thesis, storyline, evidence, findings, quantitative insights, selection rationale, and either report sections or presentation slides. Each evidence record has a stable ID, claim, epistemic type, confidence, and source descriptor (`type`, `locator`, and optional SHA-256). Findings reference evidence IDs. Quantitative observations reference their source measurements. The validator rejects unknown references, duplicate IDs, unsupported contract fields, and measured observations without evidence.

Epistemic status and confidence remain separate. In addition to legacy values, plans may use `OBSERVED`, `CALCULATED`, and `INFERRED`; `SCENARIO` distinguishes hypothetical/capture cases from observed outcomes. Confidence is `HIGH`, `MEDIUM`, `LOW`, or `UNKNOWN`. The deterministic validator checks structure and provenance links; it cannot prove that an extracted claim is true or relevant. Its output keeps `semantic_claim_review` at `PENDING_MODEL` until semantic review occurs.

The local helper inventories hashes and metadata without returning source bodies. Extraction is performed on one explicitly named source, supports bounded line ranges for line-addressable text, and records its locator and full-source SHA-256. Directory traversal is one level by default; recursive traversal is opt-in and bounded. Symlinks are not followed. Raw documents, query results, findings, and measurements are not written to Anvil memory or a source registry.

The helper does not write to Anvil memory or the source registry.

## Supported inputs and limitations

| Input | Supported extraction | Not interpreted |
| --- | --- | --- |
| Markdown, text, source, and common configuration | UTF-8 text and selected line ranges | Other encodings without conversion |
| CSV / TSV | Bounded header and row preview | Unbounded full-table analysis |
| JSON | Parsed and formatted text | External references |
| JSONC | Text extraction | JSONC semantic parsing |
| DOCX | Paragraph text from OOXML | Images, embedded objects, tracked-change semantics |
| PPTX | Slide text from OOXML | Charts, speaker notes, images, media, embedded objects |
| XLSX | Bounded cell values, shared strings, inline strings | Formula recalculation, chart semantics, date-style interpretation |
| PDF | Text layer through optional `pdftotext` | OCR/scanned pages, figures, tables that are not text |

Default safety bounds are 200 discovered files, 16 MiB per source, 512 KiB extracted text, 2,000 OOXML archive members, and 32 MiB expanded OOXML content. Oversized or unsupported inputs produce a typed blocker or an explicit ignored-source note rather than an implied complete analysis.

## Quantitative semantics

All calculations use `Decimal`; raw values remain decimal strings in contracts. Presentation rounding is a separate display step and uses half-up rounding. An absolute delta is `current - baseline`. A relative delta is `delta / baseline × 100` only when the baseline is positive and above its declared near-zero threshold. Zero, near-zero, and negative baselines retain the absolute delta and leave relative change undefined.

For rate metrics declared in percent units, the absolute difference is also returned as a percentage-point change. Relative percent change is a separate value. Direction (increase/decrease) is kept separate from interpretation (favorable/unfavorable/neutral/unknown), which depends on declared metric semantics.

Normalization requires an explicitly measured positive denominator for each compared period. Its unit must be declared as `numerator_unit/denominator_unit`; the helper performs no implicit unit conversion. Distribution summaries preserve missing counts, use linear interpolation for percentiles, report population variance and standard deviation, and flag 1.5-IQR outliers without removing them. Exclusion requires a zero-based row index and a recorded reason.

Annualization requires a positive observed period and a non-empty persistence assumption. The result remains epistemically `PROJECTION`, includes its basis window and assumption, and warns for windows shorter than 30 days. Ranking by absolute magnitude requires a common unit. Relative-improvement ranking includes only favorable comparisons with a meaningful positive baseline; unfavorable or undefined changes remain unranked.

The core also provides question-driven quantitative visual selection policy, but it does not render quantitative charts in this release. No causal conclusion is inferred from correlation, and no significance test is claimed.

## Audience and constraints

Audience is `executive`, `financial`, `technical_leadership`, `engineering`, `technical`, or `mixed` and remains distinct from tone. Executive policy foregrounds decision impact, risk, confidence, and action. Financial policy keeps observed baseline/spend separate from projections and capture scenarios. Technical leadership emphasizes architecture, scale, reliability, and trade-offs. Engineering retains mechanism, methods, diagnostics, and raw measurements. Technical policy preserves baseline, distribution, and uncertainty. Mixed policy leads with impact and progressively reveals supporting method. Audience policy changes emphasis, selected detail, and display precision, never source values or calculated values.

Constraints carry a kind, value, strength (`hard` or `soft`), origin (`explicit`, `policy`, `inferred`, `memory`, or `default`), and optional rationale. Explicit hard constraints have the highest precedence. Conflicting explicit hard constraints block materialization and require resolution. `exact_slides`, slide-role counts, architecture conditions, no-estimates/measured-only policies, and speaking-time density are checked deterministically. Natural-language fallback parsing detects only a small set of unambiguous English and Portuguese constraints; the model should provide the complete structured constraint contract.

A plan's communication budget uses audience, requested minutes, and slide/section capacity. Findings may include materiality, counter-evidence, alternatives, implications, and limitations. An optional `editorial` object carries decision context and appendix selections. Once editorial selection is active, unused findings and insights stay in a supporting appendix instead of silently disappearing; all source provenance remains visible. Materiality and counter-evidence are rendered with the finding.

Sections/slides may carry `visual_intent`: semantic relationship and form, primary message/evidence, prominence, semantic color roles, and a static or animated storyboard. It contains no absolute coordinates or raw colors. Animated storyboards require an information purpose and at least two meaningful states. Markdown retains the story and names its static renderer fallback. Editorial critic signals include generic assertions, card-heavy/repeated forms, undifferentiated prominence, semantic-form mismatch, color competition, duplicate motion changes, precision theater, exhaustive evidence inventories, and generic corporate phrases. They call for review; they do not make taste a hard constraint.

## Materialization and review

Markdown reports and constrained Markdown slide outlines are supported. A presentation outline retains the exact plan slide count and roles; it is not a PowerPoint file. Output writes are atomic, use mode `0600`, reject symlink destinations, and do not replace an existing file unless `--force` is supplied.

Architecture diagrams use a renderer-independent JSON model with a single question, viewpoint, abstraction level, typed nodes and edges, epistemic status, provenance, and a separate geometry block. The SVG renderer labels state and epistemic status as text as well as using a semantic color palette. Validation rejects invalid geometry, overlapping nodes, boundaries that do not fully contain members, and relationships crossing unrelated nodes. SVG output carries accessible title and description text. Edge crossings and potential label crowding are surfaced as layout warnings where detected; layout PASS does not mean aesthetic quality is guaranteed.

The deterministic Markdown reviewer checks structure, exact slide counts, evidence links, mislabeled percentage-point values, projection qualifications, generic slide titles, placeholders, and density. `python3 scripts/artifacts.py critique PLAN.json` returns advisory plan-level signals with `PENDING_MODEL_REVIEW`. The SVG reviewer rejects active/remote content and measurable off-viewBox geometry; diagram planning rejects routes outside its canvas. With a diagram model it also checks node/edge identity, containment, crossings, and measurable layout. Without a model it returns `PASS_WITH_WARNINGS` and reports geometry-only QA, not semantic layout verification. Text glyph overflow remains dependent on fonts and rendering. Neither reviewer proves factual truth, argument validity, source relevance, causality, or audience fit; the skill requires a separate semantic read.

Available outputs are Markdown report, Markdown slide outline, and architecture SVG. Binary PPTX/DOCX/PDF, quantitative-chart renderers, D2/Graphviz, OCR, dynamic animation, and non-Markdown document review are unavailable and reported as such. Optional PDF text extraction is capability-gated on `pdftotext`.

## Local CLI

After installation, the helper is located at `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/artifacts.py`. In a checkout, use `scripts/artifacts.py`.

```bash
python3 scripts/artifacts.py discover ./named-source.md ./named-folder --recursive
python3 scripts/artifacts.py extract ./named-source.md --start-line 20 --end-line 80
python3 scripts/artifacts.py quantify metrics.json --format json
python3 scripts/artifacts.py constraints plan.json --prompt 'Prepare exactly five slides'
python3 scripts/artifacts.py critique plan.json
python3 scripts/artifacts.py materialize plan.json --output report.md
python3 scripts/artifacts.py review report.md --plan plan.json
python3 scripts/artifacts.py diagram architecture.json --output architecture.svg
python3 scripts/artifacts.py review-diagram architecture.svg --model architecture.json
make capabilities
```

A typical agent workflow inventories only named inputs, extracts relevant ranges, builds evidence and findings with source locators, uses `quantify` for deterministic measures, creates and validates the plan, materializes only the requested format, then runs deterministic and semantic review. Existing Anvil Databricks adapters may provide evidence only when the user explicitly asks; existing read-only, bounded-query, approval, and no-mutation rules continue to apply.

## Runtime compatibility and verification

Communication is Anvil-owned and does not depend on OpenCode 2 features. The same lazy skill, `/review` command, installed Python helper, contracts, and renderers are available on supported OpenCode 1.x and 2.x configurations. Existing model neutrality, single-agent policy, default-deny permissions, Databricks optionality, and explicit-only persistent memory remain unchanged.

`tests/communication.py` uses local fixtures and the Python standard library. It covers required arithmetic, zero/negative baselines, percent versus percentage points, normalization, distributions, explicit exclusions, projections/scenarios, six audience lenses, five finance/architecture/performance/process/business cases, appendix selection, storyboard fallback, critique CLI, exact five-slide structure, input extraction limits, provenance, Markdown review, accessible SVG, off-canvas geometry, and edge-through-unrelated-node rejection. No model, workspace, external renderer, or network service is involved.

Future format adapters can use the same plan contracts. A renderer must preserve evidence and epistemic metadata, validate its output, and report unavailable capabilities explicitly; it must not change semantic findings or quantitative values.
