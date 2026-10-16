# Architecture

## Responsibility boundary

OpenCode owns providers, model selection, authentication, sessions, TUI, filesystem and shell execution, runtime state, and native compaction. Anvil owns the user-global harness, lifecycle safety, allowlisted skills, explicit Markdown memory, source registry, and runtime-independent task workflows.

Anvil's product release is independent of the OpenCode major. `config/runtime-policy.json` records supported runtime majors, minimum versions, the first-install default, and the prohibition on automatic major upgrades. `scripts/runtime.py` centralizes runtime inspection and capability reporting. The V1 and V2 config templates live beside each other; common `AGENTS.md`, commands, skills, memory helpers and source registry are shared.

The managed config lives at `$XDG_CONFIG_HOME/opencode` (default `~/.config/opencode`). OpenCode data is under `$XDG_DATA_HOME/opencode`; state is under `$XDG_STATE_HOME/opencode`. Anvil memory, knowledge, source registry, installation metadata and backups are separate under `$XDG_DATA_HOME/anvil`. The knowledge directory is not the memory store.

Project, system-managed, and organization settings are outside Anvil's global ownership boundary. They may affect effective behavior; inspect and doctor report visible project overrides without deleting user or team files.

## Runtime profiles and agent policy

OpenCode 1 uses its singular `agent`, `permission`, and `plugin` config fields. Anvil defines one model-neutral `anvil` primary agent, denies `task`, prompts for sensitive `.env` reads and destructive Git shell operations, and allowlists only the five Anvil skills. The global plugin list is empty for this profile.

OpenCode 2 uses plural `agents` and `plugins` fields and ordered permissions. It defines the same model-neutral primary agent, denies subagents, prompts for sensitive `.env` reads and destructive Git shell operations, and allowlists the same five skills plus one memory-search tool. No global MCP servers are enabled by default. Neither profile pins a model or replaces the provider's native system prompt.

## Capabilities and progressive enhancement

Callers use the central capability record rather than treating every Anvil release as one OpenCode generation. OpenCode 2 adds the local `anvil-core` plugin, native `anvil-knowledge` Reference, ordered permissions, bounded tool output, and structured stats JSON. OpenCode 1 uses its native config, commands/skills, and text stats; shared Python memory search and direct reads of explicitly named knowledge files provide the fallbacks. `scripts/capabilities.py` combines those runtime capabilities with live Databricks CLI/profile/resource status in one text or JSON result.

The V2 plugin uses the OpenCode 2 API to register only bounded, read-only `anvil_memory_search`. It does not add context hooks, prompt mutation, model routing, retries, memory writes, or custom compaction. Capabilities are visible through `make capabilities` and `make doctor`.

## Skills and commands

Five native lazy skills cover memory, Spark performance, Delta Lake, Databricks, and data ingestion. Native Markdown commands provide `/remember`, `/recall`, and `/distill`, all assigned to the Anvil agent. Persistent memory writes require explicit `/remember`, `/distill`, or direct user intent.

## Databricks capability

Anvil 2.3's optional Databricks capability uses a per-capability resolver. The official CLI remains preferred for general workspace APIs, Bundles and existing execution paths. An isolated Python SDK is the headless fallback for identity, compute, warehouse, Command Execution and Statement Execution. SQL Connector and Databricks Connect are specialized providers; VS Code is assisted only. The CLI and SDK reuse supported Unified Authentication profiles. Atomic state under `$XDG_CONFIG_HOME/anvil/databricks.json` records profile, host and provider metadata only; credentials remain in supported Databricks auth storage.

CLI installation is attempted only by an explicit `make databricks-setup`; the user-local executable is downloaded from official releases and SHA-256 checked. General reforge and upgrade flows neither install Databricks clients nor probe workspace auth. Discovery remembers a verified absolute CLI path and reports whether it is visible through the current `PATH`. Provider health is revalidated when used. The integration works with OpenCode 1 and 2 and adds no plugin, MCP, or model dependency.

The Databricks skill references a dated official system-table snapshot, focused schema notes, and query recipes. Live workspace discovery takes precedence for a task. SQL recipes aggregate and bound operational data before it enters model context. Remote execution requires a clear user request; compute and workload mutations are not exposed by the adapter, and stopped compute is never started automatically. FinOps output distinguishes measured usage identifiers, list-price estimates, and approximate shared-compute allocation, with a deterministic evidence-quality score.

## Upgrade lifecycle

`make upgrade` is the normal Anvil product upgrade. It detects the installed OpenCode major, resolves a stable candidate within that same major, generates and audits the matching profile, and rehearses against a private copy of config/data/state/memory. It then verifies a full backup, applies the exact rehearsed candidate, records runtime/migration metadata, runs postflight doctor, and rolls back after a post-mutation failure. `DRY_RUN=1` ends after rehearsal without creating a live backup or changing user state.

`make migrate-runtime OPENCODE_MAJOR=N` is the only operation that changes runtime major. It uses the same rehearsal, backup, postflight, and rollback path with a target adapter named explicitly by the user. `make reforge` follows the default runtime policy on first installation and preserves the detected runtime major when rebuilding.

## Backup and rollback boundary

Backups are private, timestamped directories under `$XDG_DATA_HOME/anvil/backups/`. Checksums cover each archived artifact. OpenCode databases and authentication/session state are copied and restored as opaque files; Anvil does not read or edit undocumented database schemas. `make rollback` restores the exact saved config, installer runtime, data, and state snapshot instead of attempting a database downgrade.

Anvil memory is outside the OpenCode config/runtime snapshot. Before rollback, current Markdown memory is archived separately under `$XDG_DATA_HOME/anvil/memory-backups/`, then remains at its normal path. Source registry and knowledge also remain in the Anvil data root.

## Memory and source registry

Markdown is the source of truth under `$XDG_DATA_HOME/anvil/memory/`. Historical entries remain readable without mass migration. Optional aliases, status, evidence, source sections, line ranges, repository and content-hash provenance are handled when present. Lexical search normalizes Unicode accents and falls back to the standard library when `rg` is unavailable.

The file-based source registry lives at `$XDG_DATA_HOME/anvil/sources/`, one atomic JSON record per explicitly distilled local source. It records source identity/hash, available Git metadata, timestamps and linked memory IDs. `/distill` inspects and plans only sources named by the user. Unchanged sources can be skipped; changed or missing sources mark linked memory as potentially stale and are surfaced for review instead of causing destructive rewrites. Knowledge files remain untouched.

Distillation is a model-guided semantic workflow defined in `config/commands/distill.md`, not an automatic parser or chunker. It asks the Anvil agent to assess claims, check relevant active code paths and tests where useful, distinguish normative requirements from implementation behavior, preserve meaningful conflicts and historical status, deduplicate, and record honest provenance. Deterministic tests cover the registry and workflow evidence rules, not an LLM's semantic quality.

## Runtime controls and installation record

Each installation record stores Anvil version separately from OpenCode runtime major/version and release artifact digest. Native stats use the current runtime interface and do not maintain a separate telemetry store. See [runtime compatibility](runtime-compatibility.md) for tested versions and capability gaps.
