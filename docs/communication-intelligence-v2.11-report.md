# Anvil 2.11 Communication Intelligence Engineering Report

**Release state: NOT RELEASE READY.** The implementation specification requires measurable improvement to an existing Anvil presentation. No current Anvil PPTX/GIF or supported equivalent was present in the repository. The available regression source is a generated Markdown quantitative fixture; it cannot stand in for a rendered deck or prove natural visual quality.

## Current Architecture Assessment

Before this change, Anvil had explicit source inventory/extraction, evidence/finding/quantitative contracts, Decimal recomputation, executive/technical/mixed planning, Markdown report and slide-outline rendering, semantic architecture SVG, and deterministic provenance/numeric/structure review. It had no per-page visual intent, explicit editorial appendix selection, motion storyboard, or plan-level editorial critic. Binary PPTX/DOCX/PDF and dynamic animation renderers were unavailable.

## Architecture Evolution

The schema-1 plan was extended additively. `contracts.py` now accepts OBSERVED/CALCULATED/INFERRED and SCENARIO labels plus finding qualifiers, editorial decision/context, appendix selections, semantic visual intent, color roles, and bounded storyboard states. `planning.py` exposes the six audience lenses and applies measured-only policies to appendix material too. `editorial.py` provides audience profiles and bounded candidate signals. `materialize.py` renders decision context, materiality, evidence focus, and selected supporting analysis. SVG QA remains in the existing diagram/review code. No PPTX-specific analysis path or new required dependency was added.

## Analytical Intelligence

Existing Decimal values are recomputed from baseline/current observations before rendering. The new OBSERVED/CALCULATED/INFERRED aliases and SCENARIO classification distinguish direct evidence, deterministic derivation, interpretation, hypothetical outcomes, and unknowns. Findings can preserve counter-evidence, alternatives, impact materiality, implications, and limitations. Missing source facts remain unknown; no evidence is invented by the deterministic layer.

## Editorial Intelligence

The audience lenses now cover executive, financial, technical leadership, engineering, technical, and mixed readers. An optional decision and materiality note gives the artifact a purpose; appendix IDs preserve supporting analysis without giving every metric equal prominence. When an editorial selection is active, unreferenced findings and insights are retained in the appendix. The critic asks for review when important findings lack implications, titles may label topics, forms repeat, cards dominate, or evidence appears exhaustive.

## Visual Reasoning

Page-level visual intent names the relationship, candidate form, primary message, supporting evidence, prominence, semantic color roles, and motion purpose. It contains no coordinates. The Markdown renderer retains this intent as a readable outline; it does not render charts or silently turn storyboards into GIFs. Architecture remains a semantic graph rendered to accessible SVG.

## Number Intelligence

Executive amount comparisons use compact approximate display values and retain periods. Financial wording prioritizes observed baseline-to-current actuals and the change. Technical leadership gets concise baseline/current context; engineering/technical views retain raw values and period detail. Stored decimal values and provenance do not change. A five-case audience evaluation verifies that communication policy changes while underlying insight JSON stays equal.

## Motion Intelligence

Animated intent requires an allowed information-bearing purpose and at least two states with distinct changes/new information. The current renderer preserves the storyboard in Markdown and states the static fallback. No dynamic animation is produced.

## Critic

`critique PLAN.json` returns advisory signals for generic assertions, card-heavy/repeated form use, equal prominence, relationship/form mismatch, excessive semantic color roles, repeated motion states, static-renderer fallback, unsupported precision, exhaustive evidence inventory, missing so-what implications, and generic corporate phrases. It returns `PENDING_MODEL_REVIEW`; deterministic checks do not judge truth, audience fit, naturalness, or taste.

## Visual QA

Diagram planning already rejects overlapping nodes, incomplete boundaries, edge crossings through unrelated nodes, and now routes outside the canvas. SVG review rejects measurable rect/circle/ellipse/line/polyline/text-anchor geometry outside `viewBox`, malformed geometry, active elements, and remote resources. Without a model it reports geometry-only QA. Font-dependent glyph clipping, raster contrast, and visual rendering remain unverified.

## Baseline and Before/After Review

The stored baseline was generated from the repository's pre-change five-slide quantitative fixture. It is not an existing user deck.

- Baseline: [v2.10 Markdown output](../tests/fixtures/communication/baseline-v2.10-quantitative.md), **2,804 bytes**; baseline SHA-256: `41dd8887ce2a5890574090f93c4897460b3b9df47a8d918ff29191697d8bf98e`.
- Candidate plan: [financial pilot fixture plan](../tests/fixtures/communication/communication-benchmark-plan.json), SHA-256 `05cb739d5fbc26503202dab4dea676ecebc6f0bdb8b250f92e2674b9134ccabe`.
- Candidate: [v2.11 editorial Markdown output](../tests/fixtures/communication/candidate-v2.11-editorial.md), **4,453 bytes**, SHA-256 `115ff959f365c449587de4774b6a717487e863e703933d5508df12fa61d5bd28`.

| Dimension | Candidate evidence | Limit |
| --- | --- | --- |
| Message clarity | Lead title states that spend fell while the success rate declined. | No live-model adjudication. |
| Storyline | Decision context precedes the five-slide sequence; exact count is retained. | The sample is synthetic. |
| Evidence discipline | Evidence IDs and provenance remain in the output; supporting rate detail moves to an appendix. | Does not independently prove source truth. |
| Audience fit | Five fixtures produce different audience policies with unchanged values. | Policy fixtures are not a human communication study. |
| Visual hierarchy | Dominant/supporting/context prominence is represented in plan data. | Markdown does not demonstrate rendered spatial hierarchy. |
| Semantic visualization | Relationship/form pairs are represented independently of coordinates. | No quantitative chart renderer. |
| Numerical communication | Repeated `330,000.00 USD` display is reduced from two occurrences to one compact `~330k`; exact source values remain in provenance. | No rendered typography evaluation. |
| Naturalness | Candidate plan produces no heuristic critic signals. | A zero signal count is not aesthetic proof. |
| Motion semantics | Process fixture validates state transitions and static fallback. | No animation renderer or GIF comparison. |
| Technical integrity | Contracts recompute derived values and validate all evidence links. | No live runtime/model integration executed. |
| Visual QA | Off-viewBox geometry and off-canvas routes are covered by regression checks. | Text glyph bounds depend on fonts/renderers. |

The candidate adds decision context, a qualified trade-off and a guardrail, demotes a secondary metric to supporting analysis, and changes executive precision. The raw measurements and evidence were not removed. Since no current Anvil deck is available, this demonstrates intent on a fixture, not a measurable improvement to the actual product presentation.

## Evaluation and Known Limitations

Offline communication tests cover finance, architecture, Spark performance, process/motion, and unrelated business cases; scenario labeling; audience transformations; appendix retention; critique CLI; SVG bounds; and existing arithmetic/provenance/constraint behavior. `make test` passed all offline checks: OpenCode 1/2 profile fixtures, Databricks fakes/FinOps, communication regressions, 25 engineering unit/fault/replay tests, lifecycle upgrade/reforge/rollback scenarios, and release documentation. No external OpenCode, Databricks, or model service was used.

## Performance

A local microbenchmark compared `render_markdown` from the pre-change `HEAD` with the candidate on the same small five-slide quantitative plan (five samples of 500 calls, warm imports). Median render time was **0.4023 ms** before and **0.7166 ms** after, an added **0.3143 ms** per plan (**78.1% relative**). The absolute overhead is below one millisecond for this fixture and excludes model generation, source extraction, and filesystem writes; it is not a live artifact-generation latency result.

No PPTX, GIF, rasterized slides, live model, OpenCode session, network service, or Databricks workspace was available or used for semantic evaluation. The actual current Anvil deck regression from the specification remains outstanding.

## Release Status

**NOT RELEASE READY.** The actual Anvil presentation benchmark is a stated release blocker. Supply the current deck and its generation inputs; render through its supported path; record a before/after visual/editorial review; then rerun the offline release suite. Do not describe this candidate as fully satisfying the deck-improvement requirement before that work succeeds.

Release Recommendation: **NOT READY**.
