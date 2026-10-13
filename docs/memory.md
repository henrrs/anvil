# Memory and knowledge

## Knowledge versus memory

Knowledge is the user-selected source material: architecture documents, policies, runbooks, standards, code, configuration, tests, or other explicitly named evidence. Memory is a compact derived claim that may help a future engineering decision. The knowledge source remains authoritative; memory carries a traceable summary. Current evidence appropriate to the question takes precedence over memory, and unsupported model assumptions come last.

Anvil exposes a separate `$XDG_DATA_HOME/anvil/knowledge/` root as the native `anvil-knowledge` OpenCode Reference. Anvil does not synchronize or crawl knowledge directories. Users can place or link their own authorized materials there and name specific sources for `/distill`.

## Storage and compatible format

The memory source of truth is human-readable Markdown under `$XDG_DATA_HOME/anvil/memory/` (default `~/.local/share/anvil/memory/`). Existing V1 entries remain readable without migration or mass rewriting. Folder conventions are `company/`, `projects/`, `decisions/`, and `lessons/`; V1 types include `fact`, `decision`, `lesson`, and `project`.

Entries use YAML frontmatter. V1 fields such as `id`, `type`, `scope`, `tags`, `source`, `confidence`, `created`, and `updated` remain supported. V2 treats `aliases`, `status`, and richer `source`/`evidence` metadata as optional. Useful status values are `sourced`, `corroborated`, `conflicted`, `historical`, and `uncertain`; missing fields are valid for older entries. Provenance may identify the source type, path/origin, section, line range, repository, commit, SHA-256, or explicit user-provided content when those details are actually available.

Never persist actual credentials or secret values. A useful memory may describe a secret-handling policy without copying the secret itself.

## Retrieval

`/recall` searches existing entries on request. The plugin tool `anvil_memory_search` permits bounded read-only retrieval in the normal agent workflow. Results are lexical, ranked from names, frontmatter, aliases and body, and limited to a small number of entries and excerpts. Unicode accents are normalized so a Portuguese query can match aliases on English entries. Search uses `rg` when present and falls back to Python when it is absent. Search does not rewrite memory.

Memory is attributed context, not a source of truth. Verify consequential or version-sensitive claims against current source material. Preserve provenance and report conflicts rather than silently choosing one side.

## Explicit writes: `/remember` and `/distill`

Persistent writes require an explicit `/remember`, `/distill`, or direct user request to remember/store something. Ordinary conversation is never harvested automatically.

`/remember` is for information the user already identified for retention. It validates metadata, checks for duplicates, uses atomic file replacement, and reports the resulting path. `/distill` is for sources the user identifies; it synthesizes a small set of decision-relevant, atomic memories instead of chunking source text.

The `/distill` workflow asks the agent to inspect the provided source, search existing memory, check relevant active code paths/tests when requested or needed, distinguish normative requirements from current implementation, and preserve genuine conflicts, history, drift, and uncertainty. It does not infer unread images, recursively crawl unrelated folders, update source documents, or create memories from unsupported claims. For user-pasted content, provenance says so and does not invent a path or commit.

## Source registry and idempotency

Local source registry records live at `$XDG_DATA_HOME/anvil/sources/<source-id>.json`. Each record includes a stable ID, source origin/path, current SHA-256, available repository and commit, first/last distillation dates, and linked memory IDs. Writes use a private temporary file followed by atomic replacement. The registry is metadata; Markdown remains the memory store.

Before distillation, the command inspects the named local source and asks the registry to plan. If every selected source is unchanged since its last successful record, the workflow reports the existing memory IDs and skips writes. If a source changed, the agent re-evaluates relevant memories and the registry retains a limited previous-hash history. The registry never changes its source hash until the source has been reviewed and the user-authorized distillation was completed.

## Lifecycle

Memory remains outside OpenCode config, binary, data, and state rollback. Upgrade copies it into the isolated rehearsal but does not rewrite the live entries. `make rollback` first archives current Markdown memory under `$XDG_DATA_HOME/anvil/memory-backups/`, then leaves the memory directory intact so current and V2 memories remain portable. Source registry and knowledge files are also Anvil-owned and are kept in the separate Anvil data root.
