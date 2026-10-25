# Communication & Artifact Intelligence architecture assessment

Assessment completed against Anvil 2.6.2 before implementation.

## Existing architecture

- Anvil keeps one model-neutral primary agent. OpenCode 1 and 2 have separate config adapters; subagents and MCP are denied by default. OpenCode 2's local plugin exposes only bounded, read-only memory search.
- User-facing workflows are mostly native Markdown commands and lazily loaded skills. `/remember`, `/recall`, and `/distill` are the existing command patterns. `/distill` accepts only named sources, extracts durable claims with provenance, and persists only under explicit user intent.
- The memory helper and source registry provide useful patterns for typed input validation, bounded reads, content hashes, provenance, atomic writes, and no-write analysis. Memory is not suitable as an artifact cache and must not receive generated evidence or one-off findings.
- `scripts/capabilities.py` combines runtime capability data with local/cached Databricks state. Databricks provider resolution, bounded subprocess calls, read-only SQL/query paths, and the FinOps analyzer live under `scripts/databricks*`; FinOps evidence already distinguishes estimates and attribution limits but is intentionally domain-specific.
- There is no existing document, presentation, chart, diagram, or generated-artifact subsystem. There is no dependency manifest or installed `python-pptx`, `python-docx`, Pillow, pandas, or NumPy. `pdftotext` is present on this development host but is not an Anvil prerequisite; D2, Graphviz, and LibreOffice are not present.
- `make test` uses standard-library Python, local OpenCode/Databricks fixtures, temporary HOME/XDG roots, and a network guard. `scripts/version_docs.py` enforces release-history consistency.

## Reuse and extension

- Reuse the single-agent/lazy-skill design for natural-language intent, semantic source analysis, audience adaptation, and narrative. Add one compact `anvil-communication` skill and a generic `/review` command; do not add agent roles or many artifact-specific commands.
- Reuse source-registry provenance conventions without writing the registry or memory as a side effect of artifact analysis. Inputs must be explicitly named, and directory traversal must be opt-in/bounded.
- Keep Databricks access behind the existing explicit, read-only-capable integration. An artifact workflow must never initiate remote execution or mutate compute without the user's direct authorization.
- Reuse standard-library JSON/CSV/XML/ZIP handling for deterministic contracts and document inspection. Keep optional PDF text extraction behind capability detection. Keep semantic reasoning in the Anvil agent and deterministic arithmetic, validation, and rendering in small independent Python modules.
- Extend runtime-neutral config allowlists, install/smoke fixtures, release documentation, and offline tests. No OpenCode 2 feature is required.

## Gaps and proposed first coherent release

The repository has no structured artifact request, evidence/finding/quantitative-insight contracts, communication planner, renderer interface, architecture model, artifact reviewer, or artifact UX. The first release introduces these as a small standard-library package, with a Markdown report path, a constrained slide-outline Markdown path, deterministic quantitative analysis and visual-selection policy, semantic architecture-to-SVG rendering, and structural/evidential/quantitative review. Quantitative chart materialization remains explicitly deferred. Natural-language source interpretation and audience-specific synthesis remain instructions for the model-backed skill, which emits validated structured contracts for deterministic materialization.

Input discovery will support explicitly named Markdown, text, CSV, JSON, source/config files, and OOXML DOCX/PPTX/XLSX text extraction with bounded reads. PDF extraction will be optional and will report unavailable when `pdftotext` is missing. Unsupported binary content and uninspected embedded media remain explicit unknowns. No source will be recursively scanned unless the user names a directory and opts into recursion.

## Explicitly not introduced

- No generic agent graph, multi-agent framework, model router, vector database, remote renderer, BI platform, arbitrary crawler, background ingestion, or automatic memory persistence.
- No required Python package or external renderer. PPTX/DOCX/PDF binary artifact generation and animation are not part of the first vertical slice; unsupported requested formats must return a typed renderer-unavailable result and an available Markdown alternative.
- No automatic Databricks query or mutation. A specific user request may guide the agent to use existing Anvil Databricks tools under their existing authorization and safety rules.

## Compatibility and risks

- The product change is backward compatible and does not alter persistent Anvil or Databricks schemas. A MINOR Anvil release is appropriate because this introduces new user capabilities.
- Adding a skill requires updating both OpenCode config profiles, the generated-config allowlist, candidate smoke checks, and the single-agent/skill budget regression. The existing memory, lifecycle, Databricks, OpenCode 1, and OpenCode 2 contracts remain unchanged.
- Semantic extraction quality cannot be guaranteed by deterministic tests. Tests can verify evidence provenance, confidence/epistemic labels, arithmetic, hard constraints, renderer validity, and reviewer detection. The skill must instruct the model to qualify ambiguous claims and to request clarification when a hard constraint conflict cannot be resolved safely.
- Layout algorithms can prove node/edge collision properties only for their supported graph model. The SVG renderer will validate output geometry and reject collisions instead of implying that visual quality has been verified when it has not.
