# Anvil runtime compatibility

**Checked:** 2026-10-16 (UTC)
**Anvil release:** `2.1.0`
**Policy:** OpenCode 1.x and 2.x supported; default major `1`; automatic major upgrade disabled.

| Anvil | OpenCode runtime | Minimum | Tested candidate | Profile | Support |
|---|---|---:|---:|---|---|
| 2.1.x | 1.x | 1.18.18 | 1.18.18 and 1.19.3 | `opencode-v1` | Supported |
| 2.1.x | 2.x | 2.0.0 | 2.0.31 | `opencode-v2` | Supported |

The tested candidates are the official stable releases resolved on the check date. They are observations, not versions pinned by Anvil. OpenCode 1 candidates are resolved from official GitHub release metadata and verified against the asset's published SHA-256 digest. OpenCode 2 candidates are resolved from the official `@opencode/cli` npm `latest` dist-tag and checked against the package's SHA-512 integrity metadata.

## Capability differences

Both profiles support the common Anvil agent, Markdown commands and skills, file memory, `/remember`, `/recall`, `/distill`, source registry, source freshness warnings, and explicit source reconciliation.

OpenCode 1 uses its singular `agent`/`permission` config shape. It has no Anvil native plugin tool or native References, so memory search uses the installed Python helper and named knowledge documents are read directly. Its native stats command produces terminal text. OpenCode 2 uses plural `agents`/`plugins`, ordered permissions, the local `anvil-core` read-only search tool, the `anvil-knowledge` Reference, and structured stats JSON.

The adapters deliberately share the same Anvil commands, skills, memory schema and source registry. Runtime-specific behavior is exposed through `scripts/runtime.py`; callers should check a capability rather than infer that every Anvil release requires the runtime with the same major number.

## Lifecycle and migration

- `make reforge` follows the configured default major on first installation and retains the detected OpenCode major when rebuilding an existing runtime.
- `make upgrade` upgrades Anvil and the current runtime release within its existing major. It does not perform an OpenCode major migration.
- `make migrate-runtime OPENCODE_MAJOR=N` is the explicit runtime-major migration operation. It stages a candidate, renders its profile, rehearses against copied config/data/state/memory, verifies a complete backup, applies the migration, runs doctor, and rolls back on postflight failure.
- `make upgrade DRY_RUN=1` and `make migrate-runtime OPENCODE_MAJOR=N DRY_RUN=1` stage and rehearse without creating a live backup or changing user files.

OpenCode session/database files remain opaque. The rehearsal starts the target runtime against copies through its native stats command and verifies config, commands and skills. It does not inspect undocumented SQLite schemas or authenticate against a provider.

## Known limitations

- OpenCode 1 does not receive the V2 native memory-search plugin or native knowledge Reference; the Anvil helper/direct-file fallbacks are used.
- Native OpenCode 1 stats are text and cannot be normalized into all fields from the OpenCode 2 JSON report.
- Download/install operations depend on access to `api.github.com` and official GitHub release assets for OpenCode 1, or `registry.npmjs.org` for OpenCode 2. The verified candidate is not silently replaced by a different artifact if a network or digest check fails.
- External system, organization and project configuration may still affect behavior. `make doctor` reports visible project overrides but does not modify them.

## Official sources

- [OpenCode 1.18.18 release](https://github.com/anomalyco/opencode/releases/tag/v1.18.18)
- [OpenCode 1 release list](https://github.com/anomalyco/opencode/releases)
- [OpenCode 1 documentation](https://opencode.ai/docs/)
- [OpenCode 1 skills](https://opencode.ai/docs/skills/)
- [OpenCode 1 commands](https://opencode.ai/docs/commands/)
- [OpenCode 2 migration from V1](https://dev.opencode.ai/v2/docs/migrate-v1/)
- [OpenCode 2 configuration](https://dev.opencode.ai/v2/docs/config/)
- [OpenCode 2 plugins](https://dev.opencode.ai/v2/docs/plugins/)
- [OpenCode 2 References](https://dev.opencode.ai/v2/docs/references/)
- [OpenCode 2 CLI stats](https://dev.opencode.ai/v2/docs/cli/commands/)
- [Official OpenCode 2 npm package](https://www.npmjs.com/package/@opencode/cli)

Revalidate both stable release sources, digests, config schemas, command/skill discovery, plugin and Reference capabilities, stats, data/state paths, and migration behavior before a later Anvil release.
