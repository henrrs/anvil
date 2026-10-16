# Changelog

Release notes for user-visible Anvil changes. See [version history](docs/versions/README.md) and [release discipline](docs/RELEASING.md).

## [2.1.0] - 2026-10-16

### Added

- OpenCode 1 and 2 runtime adapters with a checked-in runtime policy and machine-readable capabilities.
- `make capabilities`, `make migrate-runtime OPENCODE_MAJOR=N`, and rehearsed `DRY_RUN=1` support for product upgrades and explicit runtime migration.
- OpenCode 1 config generation, stable release resolution, SHA-256 artifact verification, native text stats, and file-based search/knowledge fallbacks.
- Recall freshness warnings for memories linked to changed or missing registered sources.

### Changed

- `make upgrade` now upgrades Anvil while preserving the installed OpenCode major. `make reforge` follows the approved policy on first install and preserves an existing runtime major when rebuilding.
- Runtime profile rendering, compatibility checks, capabilities, stats, and doctor behavior now use the central runtime adapter.

### Fixed

- Anvil's product release is no longer coupled to OpenCode 2. The complete Anvil 2.1 command, skill, Markdown memory, `/distill`, and source-registry workflow is available on supported OpenCode 1.x and 2.x runtimes, with native-only features gated by capability.
- `make stats` uses OpenCode 1's native text report and continues to return a non-error notice when stats cannot be obtained.
- OpenCode major migration can no longer occur implicitly during `make upgrade`.

### Preserved

- One model-agnostic primary agent, no model pinning, no default MCP servers, Markdown memory, and explicit-only persistent memory writes.
- OpenCode data and state remain opaque files in rehearsal, backup, and rollback.

## [0.1.0] - 2026-10-12 (V1 repository baseline; no release tag recorded)

This entry records the implemented V1 repository baseline from the initial Anvil history, not a separately verified public release.

### Added

- One model-neutral Anvil primary agent with compact global instructions, default-deny tool permissions, and five allowlisted skills.
- Explicit `/remember` and `/recall` commands backed by human-readable Markdown memory.
- Read-only `make inspect`, isolated `make test`, clean `make reforge`, `make doctor`, and config/installer `make rollback` workflows.
- Checksummed backups of the managed global config and OpenCode installer directory.

### Preserved limitations

- V1 did not provide a V1-to-V2 migration rehearsal or snapshot OpenCode data/state for a runtime-generation rollback.
- V1 had no `/distill`, source registry, Knowledge Reference, OpenCode 2 plugin, native stats target, model router, vector index, or automatic memory extraction.

## [2.0.0] - 2026-10-13

### Added

- Native OpenCode 2 configuration with a model-neutral Anvil primary agent, explicit permission rules, and the existing five skills.
- Safe `make upgrade` with exact stable candidate resolution, isolated V1 migration rehearsal, complete config/runtime/data/state backup, postflight doctor, and automatic rollback.
- Minimal local `anvil-core` plugin exposing bounded, read-only `anvil_memory_search`.
- `/distill`, a source-driven knowledge workflow with explicit provenance, source hash registry, drift checks, reconciliation guidance, and unchanged-source idempotency.
- Native `anvil-knowledge` Reference, `make stats`, expanded V2 doctor, and formal version/migration documentation.
- Backward-compatible memory metadata for aliases, status, evidence, source hashes, sections, and line ranges.

### Changed

- OpenCode V2 uses its native plural `agents` and `plugins` config keys, ordered permissions, references, and compaction settings.
- `make rollback` restores the full saved OpenCode config, installer runtime, data, and state while retaining and separately archiving current Anvil memory.
- `make reforge` remains a clean rebuild path; `make upgrade` is the normal forward migration/update path.

### Preserved

- One model-neutral Anvil primary agent, no model routing, subagents denied, and zero MCP servers by default.
- `/remember`, `/recall`, explicit-only persistent memory writes, V1 Markdown compatibility, and the five V1 skills.

### Compatibility

- V1 Markdown memory remains readable without rewriting entries.
- Provider definitions and CLI/TUI settings are staged through the V1-to-V2 migration path.
- OpenCode databases are copied and restored as opaque files; Anvil does not edit their schema.
