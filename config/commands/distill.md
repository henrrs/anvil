---
description: Distill explicitly provided sources into a small set of reusable, traceable Anvil memories
agent: anvil
---

Distill only the source or sources named by the user in this request:

$ARGUMENTS

This command is explicit authorization to create or update durable Anvil memory. It is not permission to crawl unrelated folders or harvest conversation history.

## Workflow

1. Identify the exact documents, pasted content, URLs, commits, or code paths the user supplied. For each local file, run `python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/source_registry.py" inspect PATH`. Read the source and the relevant surrounding context. Do not recursively ingest a directory unless the user explicitly asked for that scope.
2. Pass the collected inspect results as one JSON array to `source_registry.py plan`. If every source is unchanged and it returns `action: skip`, do not write memories or update the registry. Report `Source already distilled`, the existing memory IDs, and `Created: 0; Updated: 0`.
3. Understand the source before extracting claims. Distillation is semantic synthesis, never fixed-size chunking. Prefer a few atomic claims that could change a future engineering decision; omit generic knowledge, boilerplate, temporary status, speculation, and duplicated prose.
4. Reconcile requested sources with each other and with current repository evidence when requested or necessary. Check whether relevant code participates in an active code path and is reachable from current entrypoints; search callers, imports, tests, and configuration. An old unused file is not current implementation truth. Use focused Git history or blame only when it clarifies why current behavior exists.
5. Keep normative truth (what policy or design requires) separate from implementation truth (what active code currently does). Record a conflict when both are relevant. Current source-of-truth evidence outranks prior memory and unsupported model knowledge. Historical decisions stay labeled historical.
6. Treat diagrams and images as uninspected unless you actually opened and understood them. Never infer unreadable image contents. If a claim depends on an uninspected image, skip it or mark evidence insufficient.
7. Search before each write with the `anvil_memory_search` tool or the installed `memory.py search` helper. Reuse an equivalent memory ID; update its wording/provenance, or create a distinct memory only for a genuinely new atomic claim. Do not make `-2`, `-new`, or similar IDs to bypass deduplication.
8. For every persisted claim, record honest source metadata: `source.type` (`document`, `code`, `repository`, `commit`, or `user-explicit`), relative path/origin, section, line range, repository, commit, and SHA-256 when actually available. Add short aliases in the user's language when useful. Choose `status` from `sourced`, `corroborated`, `conflicted`, `historical`, `uncertain`; choose confidence based on the evidence rather than tone.
9. Persist only through `memory.py write-json`, one atomic JSON memory at a time. Include `evidence` strings when multiple files or tests support the claim. Do not claim the write succeeded until the helper confirms it.
10. After successful writes, record each local source using `source_registry.py record` with the exact JSON object returned by `inspect`, plus the final `memory_ids`. Include an empty list when the source yielded no durable claims. Never record a new hash until the source was fully reviewed.

The installed helpers are under `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/`. Memory is Markdown under `${XDG_DATA_HOME:-$HOME/.local/share}/anvil/memory/`; the source registry is JSON under `${XDG_DATA_HOME:-$HOME/.local/share}/anvil/sources/`. Knowledge source files remain under `${XDG_DATA_HOME:-$HOME/.local/share}/anvil/knowledge/`; OpenCode 2 exposes this path through the `anvil-knowledge` Reference, while OpenCode 1 uses ordinary file reads. Knowledge sources are never rewritten by this command.

## Result

Summarize the source paths, claim decisions, conflicts or drift, memories created/updated/skipped, and registry status. If evidence is insufficient, say so and do not create a confident claim. Never report an image as reviewed unless it was inspected.
