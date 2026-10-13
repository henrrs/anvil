# OpenCode compatibility

**Checked:** 2026-10-13 (UTC)

**Anvil version described:** `2.0.0`.

**Selected stable candidate at check time:** `2.0.28`, published 2026-10-13 08:16 UTC.

**Release channel:** npm's official `latest` dist-tag for `@opencode/cli`. The V2 resolver requires an exact `2.x.y` version and does not select a beta, RC, or preview package.

The installer queries the official npm package metadata at execution time, selects the current `latest` dist-tag once, verifies that the CLI declares the host's native optional package, downloads that exact package, and verifies its published SHA-512 SRI value. `make upgrade` and `make reforge` then smoke-test and install the same staged executable. The patch version above is a dated compatibility observation, not a version pinned in source.

## Verified behavior

- **Distribution:** OpenCode 2's official `@opencode/cli` package declares platform-specific CLI packages. The resolver selects the Linux or macOS x64/arm64 artifact and the suitable Linux musl/baseline package. It extracts only `package/bin/opencode` from the integrity-verified tarball.
- **Global paths:** The V2 candidate's `opencode debug paths` reports XDG-based config, data, cache, and state paths. The managed config remains `$XDG_CONFIG_HOME/opencode`; OpenCode data and state remain in `$XDG_DATA_HOME/opencode` and `$XDG_STATE_HOME/opencode`. Anvil memory, knowledge, registry, and backups remain separately under `$XDG_DATA_HOME/anvil`.
- **Config and migration:** V2 uses native plural `agents` and `plugins` keys, `providers`, `references`, and ordered agent `permissions`. The V1-to-V2 guide documents provider field mappings and config migration. The V2 runtime uses the same global config directory. Existing V1 `tui.json` preferences are retained for the documented native migration to `cli.json` on V2 terminal startup.
- **Agents:** V2 agent definitions use `mode`, `disabled`, `model`, `prompt`, and other V2 fields. Anvil disables the four standard built-ins and defines one model-neutral `anvil` primary. Hidden maintenance agents are left to OpenCode.
- **Permissions:** V2 permissions are ordered `{action, resource, effect}` objects; later matching rules override earlier ones. Anvil starts with a deny-all rule, allows the normal coding tools and its one memory tool, denies `subagent`, prompts for sensitive `.env` reads and destructive Git operations, and allowlists only the five Anvil skills.
- **Skills and commands:** V2 discovers global skills under the OpenCode config directory's `skills/<id>/SKILL.md` path and global Markdown commands under `commands/`. The actual candidate API smoke test waits for lazy registry initialization and checks all five skills and `/remember`, `/recall`, and `/distill`.
- **Plugins:** V2 loads local plugin directories configured in `plugins`. The V2 plugin API uses `Plugin.define` from `@opencode/plugin` and supports `ctx.tool.transform`; the candidate smoke test verifies `anvil-core` is active. The plugin is limited to bounded read-only Markdown search.
- **References:** Native configuration maps an alias to `{path, description}`. Anvil points `anvil-knowledge` at an absolute path under its separate XDG data root; the smoke test checks the alias is registered.
- **Compaction and output:** V2 supports native `compaction.auto`, `compaction.keep.tokens`, and `compaction.buffer`, plus `tool_output.max_lines` and `max_bytes`. Anvil uses these native V2 controls and `watcher.ignore`.
- **Stats:** V2 supports `opencode stats --standalone --days N --models --cost --json`. `make stats` formats that JSON and creates no separate telemetry store.
- **State migration:** OpenCode owns session, authentication, and database schemas. Upgrade copies data/state into a private rehearsal environment and starts the V2 runtime through native stats; Anvil never reads or edits undocumented SQLite tables. Backups retain OpenCode data/state as opaque archives.

The migration design is based on the official V2 documentation and the candidate's actual runtime behavior. The rehearsal does not open an interactive TUI or make a provider/model request; it therefore does not claim to verify terminal rendering or authentication against a live provider.

## Official sources

- [OpenCode CLI package](https://www.npmjs.com/package/@opencode/cli) and [npm package metadata](https://registry.npmjs.org/@opencode%2fcli)
- [Install OpenCode](https://opencode.ai/install)
- [Migrate from V1](https://dev.opencode.ai/v2/docs/migrate-v1/)
- [Configuration](https://dev.opencode.ai/v2/docs/config/)
- [Agents](https://dev.opencode.ai/v2/docs/agents/)
- [Permissions](https://dev.opencode.ai/v2/docs/permissions/)
- [Skills](https://dev.opencode.ai/v2/docs/skills/)
- [Commands](https://dev.opencode.ai/v2/docs/commands/)
- [Plugins](https://dev.opencode.ai/v2/docs/plugins/)
- [Build a V2 plugin](https://dev.opencode.ai/v2/docs/build/plugins/)
- [References](https://dev.opencode.ai/v2/docs/references/)
- [CLI configuration](https://dev.opencode.ai/v2/docs/cli-config/)
- [Compaction](https://dev.opencode.ai/v2/docs/compaction/)
- [CLI and stats](https://dev.opencode.ai/v2/docs/cli/commands/)
- [V2 API schema](https://dev.opencode.ai/v2/docs/api)

## Revalidation checklist

Before a future Anvil release, check the official npm `latest` tag, package optional dependencies and integrity metadata; platform artifact naming; XDG path behavior; V1 config/provider migration; V2 agent and permission schema; skills, commands, local plugin, References, compaction, CLI settings, stats, and opaque data/state migration. Run `make test` against the exact current stable candidate and update this dated record.
