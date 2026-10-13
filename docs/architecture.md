# Architecture

## Responsibility boundary

OpenCode owns providers, model selection, authentication, sessions, TUI, filesystem and shell execution, and native compaction. Anvil owns the user-global harness, lifecycle safety, allowlisted skills, explicit Markdown memory, the source registry, and its narrow read-only memory search plugin.

The managed config lives at `$XDG_CONFIG_HOME/opencode` (default `~/.config/opencode`). OpenCode data lives under `$XDG_DATA_HOME/opencode`; state lives under `$XDG_STATE_HOME/opencode`. Anvil's memory, knowledge, source registry, installation metadata, and backups are separate under `$XDG_DATA_HOME/anvil`. `anvil-knowledge` is a native OpenCode Reference to `$XDG_DATA_HOME/anvil/knowledge`; it is not the memory store.

Project, system-managed, and organization settings are outside Anvil's global ownership boundary. They may affect effective behavior; inspect and doctor report visible project overrides without deleting user or team files.

## Agent and policy

OpenCode 2 native configuration defines one model-neutral `anvil` primary agent and disables the built-in `build`, `plan`, `general`, and `explore` user-facing agents. The model is not pinned. Ordered `{action, resource, effect}` permissions begin with deny-all and explicitly allow normal coding tools, prompt for sensitive `.env` reads and destructive Git operations, allowlist the five Anvil skills and the single memory search tool, and deny subagents. Global MCP servers are empty by default.

The local `anvil-core` plugin uses the official OpenCode 2 plugin API to register only `anvil_memory_search`. Search is lexical and bounded: it returns a small number of short excerpts and never writes memory. The plugin does not add context hooks, prompt mutation, model routing, retries, or custom compaction.

## Skills and commands

Five native lazy skills cover memory, Spark performance, Delta Lake, Databricks, and data ingestion. Native Markdown commands provide `/remember`, `/recall`, and `/distill`, all assigned to the Anvil agent. Persistent memory writes require explicit `/remember`, `/distill`, or direct user intent.

## Upgrade lifecycle

`make upgrade` is the normal V1-to-V2 and V2-update path. It first checks the managed paths and running OpenCode processes, detects a supported Anvil V1 or V2 config/runtime pair, resolves one exact stable OpenCode 2 candidate, verifies and stages its platform artifact, generates the V2 config, and rehearses migration under a private temporary HOME/XDG tree. The rehearsal copies config, OpenCode data and state, and Anvil Markdown memory. It starts the candidate against copied data with native stats, validates the actual V2 CLI registration of the agent, commands, skills, plugin, and Reference, then runs doctor.

After rehearsal, Anvil creates and verifies a checksummed backup of global config, installer runtime, OpenCode data/state, prior installation metadata, and inspection output. It installs the same staged executable and config, records release/migration metadata, and runs postflight doctor. A failure after live mutation triggers rollback from that backup.

`make reforge` is a separate clean installation/rebuild path. It remains suitable for first install or explicit reset. It does not serve as the V1-to-V2 migration mechanism.

## Backup and rollback boundary

Backups are private, timestamped directories under `$XDG_DATA_HOME/anvil/backups/`. Checksums cover each archived artifact. OpenCode databases and authentication/session state are copied and restored as opaque files; Anvil does not read or edit undocumented database schemas. `make rollback` restores the exact saved config, installer runtime, data, and state snapshot instead of attempting a database downgrade.

Anvil memory is outside the OpenCode config and runtime snapshot. Before rollback, current Markdown memory is archived separately under `$XDG_DATA_HOME/anvil/memory-backups/`, then left at its normal path. Source registry and knowledge are also Anvil-owned and remain in the Anvil data root.

## Memory and source registry

Markdown is the source of truth under `$XDG_DATA_HOME/anvil/memory/`. V1 entries remain readable without mass migration. Optional V2 aliases, status, evidence, sections, line ranges, repository and content-hash provenance are handled when present. Lexical search normalizes Unicode accents and falls back to the standard library when `rg` is unavailable.

The file-based source registry lives at `$XDG_DATA_HOME/anvil/sources/`, one atomic JSON record per explicitly distilled local source. It records the source identity, hash, available Git metadata, dates, and linked memory IDs. `/distill` first inspects and plans each named source. Unchanged registered sources can be skipped; changed sources are surfaced for review rather than blindly duplicated. Knowledge files remain untouched.

Distillation is a model-guided semantic workflow defined in `config/commands/distill.md`, not an automatic parser or chunker. It asks the Anvil agent to assess source claims, check relevant active code paths and tests where requested, distinguish normative requirements from implementation behavior, preserve conflicts and historical status, deduplicate, and record honest provenance. The deterministic registry supplies hash-based idempotency; tests do not claim to prove an LLM's semantic quality.

## Native runtime controls

V2 uses OpenCode's native References, ordered permissions, compaction controls, bounded tool output, and structured `stats --json`. `make stats` formats native statistics without maintaining a separate telemetry store. The installation record stores Anvil/OpenCode versions, release artifact integrity, previous versions, migration status, and backup path.
