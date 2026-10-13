# Anvil

> **Anvil — A lean, model-agnostic OpenCode harness designed to maximize reliable task completion while minimizing unnecessary context and token usage.**
>
> **Better harness. Better execution.**

```bash
make inspect
make test
make upgrade
make doctor
```

Use `make reforge` for a clean installation or rebuild. Use `make rollback` to restore the latest verified runtime snapshot. `make stats` displays OpenCode's native usage report.

Anvil is a lean, model-agnostic harness and lifecycle layer for OpenCode. OpenCode remains responsible for models, providers, authentication, sessions, tools, and execution. Anvil supplies a focused behavioral environment: compact instructions, one primary agent, a small set of skills, explicit file memory, evidence-driven workflows, and safe upgrade and recovery operations.

## Why Anvil?

Anvil means a blacksmith's anvil: the stable base on which material is shaped, refined, and made useful. The anvil is not the material and does not supply all the energy; it provides a dependable surface for the work.

Anvil plays that role for language models. It does not create or route models. It gives the selected model disciplined context, useful skills and memory, clear execution rules, and verification. Models may change; the harness remains the foundation.

```text
Luna / Terra / Sol / Astra / Sonnet / other models
                         │
                         ▼
                   Anvil harness
       context · skills · memory · tools · rules
                         │
                         ▼
              reliable, verified execution
```

## Install and upgrade

Prerequisites: Linux or macOS, Bash, Python 3.11+, `tar`, and internet access to the official npm registry. Anvil resolves the current stable OpenCode 2 release when needed, stages one exact candidate, and verifies the published SHA-512 integrity metadata. Windows users can run Anvil under WSL.

`make inspect` reads the current OpenCode setup without changing it. `make test` checks the V2 config, memory behavior, upgrade lifecycle, rollback and failure recovery in isolated temporary environments, and smoke-tests the exact official stable candidate.

`make upgrade` is the normal path for an existing Anvil V1 installation. It rehearses migration using copied config, OpenCode data/state, and Anvil memory under a temporary HOME/XDG tree. Only after rehearsal succeeds does it create and verify a complete backup, install that exact tested candidate, and run post-upgrade doctor. Failed postflight checks trigger automatic rollback.

`make reforge` remains the clean install and rebuild path. It is also suitable for first installation or recovery from a corrupted managed setup. Anvil installs OpenCode under `~/.opencode/bin` and updates a supported shell startup file if necessary.

Backups live under `$XDG_DATA_HOME/anvil/backups/` (default `~/.local/share/anvil/backups/`). They use restrictive permissions and include checksums plus the prior config, installer runtime, OpenCode data and state, and install metadata. OpenCode databases are treated as opaque files; Anvil does not edit undocumented schemas. Backups may contain sensitive session or authentication state.

## Memory and knowledge

Anvil keeps Markdown memory under `$XDG_DATA_HOME/anvil/memory/`. Existing V1 entries remain readable without rewriting. Search is lexical, accent-insensitive, bounded, and can use aliases for multilingual retrieval. Memory is not a database, vector index, or automatic transcript store.

- `/remember` saves a specific fact or decision the user explicitly wants retained.
- `/recall` searches existing entries and returns a small relevant set.
- `/distill` turns explicitly named documents, pasted content, or evidence into a small set of reusable memories with provenance. It checks duplicates, preserves historical or conflicting claims, and detects unchanged sources so they are not reprocessed unnecessarily.

Persistent writes require explicit `/remember`, `/distill`, or direct user intent. Knowledge documents remain the source material; memory contains compact derived claims. The `anvil-knowledge` OpenCode Reference points to the separate `$XDG_DATA_HOME/anvil/knowledge/` directory.

Anvil's local `anvil-core` OpenCode 2 plugin exposes one bounded, read-only `anvil_memory_search` tool. It does not rewrite prompts, route models, or write memories.

## Models, agents, and skills

Anvil configures one model-neutral `anvil` primary agent. No model is pinned; select models through OpenCode as usual. The four built-in user-facing agents are disabled, subagents are denied, and no MCP servers are enabled by default. Five allowlisted skills cover memory, Spark performance, Delta Lake, Databricks, and data ingestion.

## Recovery and status

`make rollback` restores the latest verified pre-upgrade/rebuild OpenCode config, executable, data, and state snapshot. Current Anvil Markdown memory is archived separately before rollback and remains portable. Rollback restores the original runtime snapshot rather than trying to downgrade a migrated database.

`make doctor` checks the V2 config and agent policy, commands and skills, plugin files, memory, knowledge reference, source registry, migration metadata, and visible workspace overrides. It reports `HEALTHY`, `WARNING`, or `BROKEN`; exit codes are `0`, `2`, and `1` respectively. Workspace, system, or organization-managed configuration can still affect effective behavior.

## Version history

See [the V1/V2 capability matrix](docs/versions/README.md), [V1 history](docs/versions/v1.md), [V2 release notes](docs/versions/v2.md), [V1-to-V2 migration guide](docs/migrations/v1-to-v2.md), [memory behavior](docs/memory.md), and [OpenCode compatibility](docs/opencode-compatibility.md).
