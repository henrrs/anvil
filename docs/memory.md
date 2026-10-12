# Memory

## Storage and format

The default store is `~/.local/share/anvil/memory/`, or `$XDG_DATA_HOME/anvil/memory/`. It contains Markdown files with YAML frontmatter and a short body. Folders are `company/`, `projects/`, `decisions/`, and `lessons/`. Entries use one of four types: `fact`, `decision`, `lesson`, or `project`.

Each entry records an id, type, scope, tags, source, confidence, created date, updated date, and body. Source metadata may identify a user-explicit statement, repository path, document, URL, commit, test, or honest note. An entry must not claim evidence that was not actually checked. Provider secrets and credentials should not be saved in memory.

## Retrieval

Use `/recall` with a few distinctive terms, for example `/recall Databricks secrets` or `/recall project ingestion`. Search checks names, tags, frontmatter, and body, ranks textual matches, and displays a small number of entries. It does not load the complete store. If ripgrep is installed, it narrows candidates with `rg` first; standard-library scoring then ranks those candidates.

Memory is attributed prior context, not a source of truth. Verify version-sensitive or consequential facts against current repository files and official sources. If evidence conflicts, use the evidence and explain the difference. Preserve the memory source and confidence when summarizing.

## Explicit writes

Persistent writes happen only after `/remember` or a direct user request to remember, save, or store information. The command rejects ephemeral notes unless the user insists, searches for duplicates, reuses the closest matching id when appropriate, normalizes the body and tags, and includes honest provenance. The helper refuses a strong likely duplicate under a different id so the agent can review and update the existing entry.

The writer validates fields, limits unsafe ids/tags, writes one file through a same-directory temporary file, fsyncs, and atomically replaces the target. Files are private to the user. Recall never writes. Searching never writes. No automatic conversation extraction or summarization runs.

## Lifecycle

Memory is outside OpenCode's global config tree, so `make reforge` preserves it. Rollback leaves it in place; without Anvil's command and harness it has no effect on OpenCode. Backups do not include the memory store because Anvil does not change it during reforge.
