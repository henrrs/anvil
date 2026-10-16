# Changelog

Release notes for user-visible Anvil changes. See [version history](docs/versions/README.md) and [release discipline](docs/RELEASING.md).

## [2.3.0] - 2026-10-16

### Added

- Capability-based Databricks provider resolution with the official CLI, isolated Python SDK, optional SQL Connector, Databricks Connect detection, and VS Code assisted status.
- Explicit `make databricks-setup` CLI installation attempt from official GitHub releases with SHA-256 verification and a user-local, no-elevation install path.
- Anvil-owned isolated SDK environment and Unified Authentication profile reuse when CLI setup is blocked or unavailable.
- PATH-resilient CLI discovery, atomic schema-versioned provider metadata, provider-aware doctor/capabilities, and `make databricks-setup DRY_RUN=1`.
- Offline provider tests for install outcomes, PATH changes, SDK routing, VS Code detection, state security, setup idempotency, and dry-run behavior.

### Changed

- Databricks capability is no longer hard-coupled to the CLI; the CLI remains preferred when healthy, with per-capability SDK fallback.
- `make reforge` and `make upgrade` no longer prompt to configure Databricks or perform Databricks network/install work.
- CLI or SDK installation blockage is reported independently from the Anvil lifecycle and other available Databricks providers.

### Preserved

- OpenCode 1.x and 2.x compatibility, existing Anvil 2.2 execution bounds, profile non-switching, secret-free Anvil state, and the no-silent-remote-mutation guardrails.
- One model-neutral Anvil agent, no mandatory MCP, and no model routing.

### Limitations

- The mandatory test suite uses local doubles and does not contact a Databricks workspace or install real providers.
- CLI and SDK installation require access to official GitHub/PyPI sources when `make databricks-setup` is explicitly run. VS Code is assisted; Anvil does not automate the IDE.

## [2.2.0] - 2026-10-16

### Added

- Optional, runtime-independent Databricks capability through the official CLI and REST APIs, including cross-session profile selection, Python Command Execution, bounded SQL Statement Execution, live system-catalog discovery, and setup/doctor/capabilities integration.
- Dated system-table catalog snapshot, focused references, seven aggregate query recipes, and deterministic FinOps analysis with an Evidence Confidence Score.
- Offline Databricks CLI and OpenCode runtime fixtures. `make test` no longer resolves or downloads external runtime candidates.

### Changed

- Condensed the global harness and clarified execution evidence, recovery, validation, scope, Databricks mutation, secret, and FinOps guardrails.
- Skill descriptions now explain when each skill should and should not be used.
- `make capabilities` reports runtime and live Databricks state in one text or JSON document.

### Preserved

- One model-neutral primary agent, explicit-only durable memory, no default MCP requirement, and support for OpenCode 1.x and 2.x without implicit major migration.
- Databricks credentials remain under CLI-managed authentication; Anvil stores only the selected profile and workspace host.

### Limitations

- Mandatory validation is fully offline and does not claim a live Databricks or OpenCode service connection was tested.
- Databricks requires CLI 1.0.0 or newer, valid workspace permissions, a running classic all-purpose cluster for remote Python, and a running SQL warehouse for SQL execution.

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
