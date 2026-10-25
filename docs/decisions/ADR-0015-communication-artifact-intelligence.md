# ADR-0015: Communication & Artifact Intelligence

- **Status:** Accepted
- **Date:** 2026-10-25
- **Release:** Anvil 2.7.0

## Context

Anvil needs a reliable path from authorized heterogeneous evidence to a useful, audience-specific explanation and artifact. The repository already has one model-neutral agent, lazy skills, explicit source provenance conventions, OpenCode 1/2 adapters, isolated standard-library tests, and an optional bounded Databricks capability. It has no document or diagram subsystem. Persistent memory is explicit-only and must not become an artifact cache.

Binary renderers and external layout tools are not installed or justified as required dependencies. A large format-first generator would hide the reasoning and evidence risks the capability must address.

## Decision

Add one lazy `anvil-communication` skill and one generic `/review` command. Keep natural language as the interface and keep semantic source synthesis with the existing Anvil agent. Add a small standard-library package with versioned evidence, finding, quantitative insight, plan, and architecture contracts; bounded explicit-path input adapters; deterministic decimal arithmetic; constraint and audience policy; Markdown report/slide-outline materialization; semantic architecture-to-SVG materialization; and deterministic structural/provenance/quantitative review.

This capability is runtime-independent: the same contracts and helper run under the supported OpenCode 1.x and 2.x adapters. Plan validation reports `semantic_claim_review: PENDING_MODEL` until semantic accuracy has actually been reviewed.

Require measured values in artifact plans to reference evidence IDs. Recompute derived quantitative fields from the observations before a plan can render. Mark semantic truth review pending rather than equating structural checks with factual correctness. Keep artifact evidence out of persistent memory and the source registry. Continue to use the existing Databricks adapter only when explicitly requested and within its read-only/no-mutation controls.

Ship no required dependency, no agent graph, no remote renderer, no automatic source crawler, and no persistent artifact store. Report binary PPTX/DOCX/PDF and quantitative chart rendering unavailable. Optional PDF text extraction uses `pdftotext` only when present.

No third-party Python package is required; the core is implemented with the Python standard library.

## Consequences

- Markdown and SVG provide complete local first-slice renderers without requiring a Python package or OpenCode 2.
- Provenance, arithmetic, constraint structure, and output safety have offline regression coverage.
- Semantic extraction and narrative truth remain model/human responsibilities and are labeled accordingly.
- OOXML adapters read bounded text/value subsets and explicitly report uninspected media, charts, notes, formulas, and scanned pages.
- Future renderers can reuse the semantic plan but must preserve evidence and epistemic status and add format-specific validators.
- The new lazy skill expands the allowlist by one; both runtime config profiles and smoke fixtures must stay aligned.

## Alternatives considered

1. **Start with PPTX/DOCX dependencies:** rejected because it makes output format the architecture and does not validate evidence reasoning first.
2. **Use Mermaid/D2/Graphviz as the semantic diagram:** rejected because source syntax alone cannot enforce provenance, epistemic status, or node-crossing constraints.
3. **Add artifact-specific commands and agents:** rejected because it adds permanent surface area and duplicates the natural-language Anvil workflow.
4. **Persist analysis in memory:** rejected because one-off source evidence is not durable user memory and writes are explicit-only.
