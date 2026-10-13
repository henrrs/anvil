# Changelog

Release notes for user-visible Anvil changes. See [version history](docs/versions/README.md) and [release discipline](docs/RELEASING.md).

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
