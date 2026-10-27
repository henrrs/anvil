# OpenCode compatibility

**checked_at:** 2026-10-27
**Anvil version:** `2.9.0`
**Supported runtime majors:** OpenCode 1.x and 2.x
**Default major for a first installation:** OpenCode 1.x
**Automatic major upgrade:** disabled.

Anvil version and OpenCode runtime major are independent. Compatibility limits and validation method are maintained in [runtime compatibility](runtime-compatibility.md). The 2.9 mandatory suite uses local CLI fixtures and does not resolve live release candidates. Separate 2026-10-27 smoke checks downloaded and digest-verified official OpenCode 1 `1.19.3` and OpenCode 2 `2.0.31`, then validated generated candidate profiles in isolated HOME/XDG roots. Both discovered the engineering/system-design skills; V2 plugin/Reference checks also passed. No model or live workspace was invoked. Official native skill documentation was rechecked for lazy discovery on both generations.

## Runtime-specific behavior

- OpenCode 1 uses singular `agent`, `permission`, and `plugin` config keys and supports its native plugin API. The Anvil V1 profile leaves that plugin facility unused because `anvil-core` targets the OpenCode 2 plugin API; shared commands, skills, explicit Markdown memory, source registry, and `/distill` remain active. Its native stats command emits terminal text; memory search and knowledge use file-based helpers/reads.
- OpenCode 2 uses plural `agents` and `plugins`, ordered permissions, native local plugins, References, native compaction/output settings, and structured `stats --json`. Anvil's local `anvil-core` plugin exposes only bounded, read-only Markdown search; it does not route models or rewrite prompts.
- Commands and skills are Markdown files shared between profiles. OpenCode 1 and 2 discover the same global `commands/` and `skills/` trees.
- The Anvil Databricks capability uses shared provider scripts, CLI/SDK integrations, and a per-capability resolver. It does not depend on OpenCode plugins, MCP, or V2-specific permissions.
- OpenCode owns authentication, session/database schemas, and runtime state. Anvil copies these paths opaquely during rehearsal and backup, and never edits undocumented database tables.

## Distribution and version selection

The OpenCode 1 resolver is used only for explicit runtime operations or fresh runtime provisioning. It selects the latest stable `1.x.y` GitHub release and matching platform artifact. It requires an official asset digest and verifies the downloaded archive with SHA-256 before extracting the executable.

The OpenCode 2 resolver is used only for explicit runtime operations or fresh runtime provisioning. It selects the official npm `latest` dist-tag for `@opencode/cli`, requires an exact stable `2.x.y`, verifies the host optional package and SHA-512 SRI metadata, and extracts only the executable from the verified tarball.

The resolved patch versions are compatibility observations and are not pinned in Anvil source. Network errors identify the official endpoint; a missing or invalid digest stops the operation rather than silently substituting another binary.

## Lifecycle

- `make reforge` reuses an existing healthy runtime exactly; only a fresh install resolves and provisions OpenCode.
- `make upgrade` updates Anvil only, works offline, and preserves the exact validated OpenCode executable and version.
- `make update-runtime` is the explicit same-major runtime update path; it resolves, rehearses, backs up and installs a candidate while preserving Anvil release/config.
- `make migrate-runtime OPENCODE_MAJOR=N` is the explicit major migration path. It rehearses the target profile with copied state, verifies a full backup, performs postflight doctor, and rolls back on failure.
- `make upgrade DRY_RUN=1` uses local state and rehearses without release lookup, backup, or live changes.

OpenCode 1 and 2 have different configuration and capability models. See [the official V2 V1 migration guide](https://dev.opencode.ai/v2/docs/migrate-v1/) for V2 field and plugin changes. Anvil runtime migration details are in [the 2.0-to-2.1 guide](migrations/v2-to-v2.1.md), [the 2.1-to-2.2 guide](migrations/v2.1-to-v2.2.md), and [the 2.2-to-2.3 guide](migrations/v2.2-to-v2.3.md).

## Official references

- [OpenCode 1 releases](https://github.com/anomalyco/opencode/releases)
- [OpenCode 1.18.18 release](https://github.com/anomalyco/opencode/releases/tag/v1.18.18)
- [OpenCode 1 configuration and CLI docs](https://opencode.ai/docs/)
- [OpenCode 1 skills](https://opencode.ai/docs/skills/)
- [OpenCode 1 commands](https://opencode.ai/docs/commands/)
- [OpenCode 2 configuration](https://dev.opencode.ai/v2/docs/config/)
- [OpenCode 2 skills](https://dev.opencode.ai/v2/docs/skills/)
- [OpenCode 2 plugins](https://dev.opencode.ai/v2/docs/plugins/)
- [OpenCode 2 References](https://dev.opencode.ai/v2/docs/references/)
- [OpenCode 2 CLI stats](https://dev.opencode.ai/v2/docs/cli/commands/)
- [Official OpenCode 2 npm package](https://www.npmjs.com/package/@opencode/cli)

Before the next Anvil release, recheck stable release sources, official assets and digests, minimum supported versions, config schema, agent permissions, command/skill discovery, plugin API, References, stats, state paths, and migration behavior. `make test` validates both runtime contracts offline; it does not download or smoke-test live OpenCode candidates.
