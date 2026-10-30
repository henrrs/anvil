# ADR-0019: Analytical, Editorial & Visual Communication Intelligence

- **Status:** Accepted
- **Date:** 2026-10-30
- **Release:** Anvil 2.11.0 candidate

## Context

The 2.7 communication pipeline already separates bounded input extraction, evidence contracts, Decimal analysis, audience/constraint planning, Markdown materialization, semantic architecture-to-SVG rendering, and deterministic review. It preserves provenance and keeps `semantic_claim_review: PENDING_MODEL`. It does not represent decision context, appendix selection, semantic per-page visual intent, storyboard motion, or a bounded editorial critic. The audience contract covers only executive, technical, and mixed readers, and number formatting does not distinguish financial and leadership contexts.

The repository has no existing Anvil PPTX/GIF presentation artifact. Binary presentation and animation rendering are not supported, and a current-deck before/after validation cannot be claimed.

## Decision

Extend the version-1 artifact plan additively. Keep analytical, editorial, visual-intent, and renderer responsibilities renderer-independent. Add OBSERVED/CALCULATED/INFERRED/SCENARIO epistemic labels while retaining legacy aliases; allow findings to carry materiality, counter-evidence, alternatives, implications, and limitations; add decision and appendix metadata; add six distinct audience lenses; and allow sections/slides to declare semantic visual intent without renderer coordinates or raw colors.

Add a standard-library editorial critic that returns candidate signals and a `PENDING_MODEL_REVIEW` status. It does not rewrite plans, decide business meaning, or turn aesthetic preferences into automatic failures. Preserve exact numeric values in contracts and source evidence while selecting audience-appropriate display precision. Keep motion as a semantic storyboard and report a static fallback when dynamic rendering is unavailable.

Extend deterministic SVG validation to reject routes outside the declared canvas and off-viewBox measurable geometry. Font-dependent text glyph clipping remains outside this geometry-only guarantee.

Do not add a PPTX dependency, animation renderer, model call, background agent, persistent artifact store, or automatic memory write. No user-data or OpenCode runtime migration is introduced.

## Consequences

- Analysis, editorial policy, visual intent, Markdown/SVG rendering, and review remain separate and model/runtime independent.
- Decision-relevant material can lead while unselected findings and insights remain available in a supporting appendix; source provenance remains in the artifact.
- Audience, evidence status, visual relationship, and motion intent become testable offline without claiming semantic truth.
- A genuine existing-deck comparison is still a release blocker. The implementation candidate must not be marked release-ready until that input is supplied and reviewed.

Release decision: **NOT RELEASE READY** until the actual Anvil deck benchmark has a before/after review.
