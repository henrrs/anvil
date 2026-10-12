# OpenCode compatibility

**Checked:** 2026-10-12 (UTC)

**Selected current stable:** `1.19.0`, released 2026-10-11

**Release channel:** official GitHub latest release endpoint, with `draft=false` and `prerelease=false` verified
**Distribution source:** official OpenCode installer documentation and official `anomalyco/opencode` release assets

Anvil does not hardcode this OpenCode major/minor version into the design. The staged installer resolves the latest official stable release, downloads its platform artifact, checks the SHA-256 digest published in the official GitHub release API, checks `opencode --version`, validates configuration with that exact candidate, then installs the same candidate. It does not resolve “latest” a second time after validation.

## Verified current behavior

- **Official installation:** OpenCode documents `https://opencode.ai/install` and supports a specific version or a local binary. Its user install directory is `~/.opencode/bin`; the installer can add that directory to the active shell's startup configuration. Anvil stages the official release asset itself so the API-provided SHA-256 can be checked, then places the tested binary in that same user install directory.
- **Config and precedence:** The server/runtime config is JSON or JSONC and uses `https://opencode.ai/config.json`. Default Linux paths use XDG directories: `~/.config/opencode` for config, `~/.local/share/opencode` for data, `~/.cache/opencode` for cache, and `~/.local/state/opencode` for state. `opencode debug paths` reports resolved paths. Remote organization defaults load before global config; project config and `.opencode` assets can override global settings; inline/managed config can be higher priority. Config objects are merged, so an empty user `mcp` object does not erase a higher-precedence remote MCP definition.
- **Agent schema:** Current agent definitions accept `mode`, `disable`, `model`, `variant`, `prompt`, and `permission`. `disable: true` removes named built-in agents from the available agent map. The current built-in user-facing ids are `build` (primary), `plan` (primary), `general` (subagent), and `explore` (subagent). `compaction`, `title`, and `summary` are hidden internal agents; Anvil leaves them enabled. `default_agent: anvil` selects the custom primary. Omitting Anvil's `prompt` avoids replacing the provider/model-native prompt.
- **Permissions:** Permissions accept `allow`, `ask`, and `deny`; `task` gates subagent calls and `skill` accepts name/pattern rules. The current OpenCode build defaults many tools to allow, so Anvil uses a per-agent `* : deny` baseline followed by explicit normal coding tools and exact Anvil skill names. Anvil keeps OpenCode's `.env` read prompts and asks before destructive Git operations such as hard reset, clean, force push, branch deletion, and dropping stashes. The provider's external-directory safeguards remain in OpenCode's permission implementation.
- **Skills and commands:** Global skill files are discovered under the OpenCode config directory's `skills/<name>/SKILL.md`; skill descriptions are discovered separately from bodies. Skill permission rules can allow/deny patterns. Markdown command files in the global `commands/` directory use frontmatter such as `description` and `agent`, plus an instruction template. Anvil uses these native mechanisms for its five lazy skills and two slash commands.
- **MCP and plugins:** Global MCP definitions use the `mcp` config object. Plugin config uses `plugin`; global plugin files may also be discovered under the config directory. User/project/remote/managed sources are distinct, so Anvil can guarantee that its fresh global config declares zero servers but cannot erase a higher-precedence organization or project MCP.
- **Native compaction and bounded output:** The current schema has `compaction.auto`, `prune`, `tail_turns`, `preserve_recent_tokens`, and `reserved`; `tool_output.max_lines` and `max_bytes` bound output before truncation; watcher exclusions use `watcher.ignore`. Anvil uses these native fields.
- **Inspection CLI:** `opencode debug config` shows resolved runtime config, `opencode debug paths` shows global data/config/cache/state paths, `opencode debug skill` lists discovered skills, and `opencode agent list` lists agents. `opencode --version` reports the running version.
- **Authentication and session storage:** OpenCode derives config/data/cache/state from XDG paths. Authentication and session data live in OpenCode-owned data/state, separate from the global config reset. Anvil leaves these stores in place and does not edit their SQLite schemas.

## Sources

- [Official stable release v1.19.0](https://github.com/anomalyco/opencode/releases/tag/v1.19.0)
- [Official installation instructions](https://opencode.ai/install)
- [OpenCode config documentation](https://opencode.ai/docs/config/)
- [Agent documentation](https://opencode.ai/docs/agents/)
- [Skills documentation](https://opencode.ai/docs/skills/)
- [Commands documentation](https://opencode.ai/docs/commands/)
- [MCP server documentation](https://opencode.ai/docs/mcp-servers/)
- [CLI documentation](https://opencode.ai/docs/cli/)
- [Rules and instruction precedence](https://opencode.ai/docs/rules/)
- [v1.19.0 config schema source](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/core/src/v1/config/config.ts)
- [v1.19.0 agent config source](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/core/src/v1/config/agent.ts)
- [v1.19.0 agent runtime source](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/agent/agent.ts)
- [v1.19.0 global path source](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/core/src/global.ts)

## Revalidation checklist

Before a future Anvil release, check whether OpenCode still supports: stable release API and asset digests; install path and platform artifact names; config XDG paths and merge precedence; global `AGENTS.md`; built-in agent ids, disable behavior, and hidden maintenance agents; permission rule names/patterns; native lazy skill discovery and Markdown commands; MCP/plugin config keys; compaction/output/watcher fields; `debug config`, `debug paths`, `debug skill`, and `agent list`; and data/state separation for authentication and sessions. Run `make test` against the new exact stable candidate before updating this document.
