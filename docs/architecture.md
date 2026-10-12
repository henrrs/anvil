# Architecture

## Responsibility boundary

Anvil controls the user/global OpenCode harness: global `AGENTS.md`, the `anvil` agent definition, the explicit skill allowlist, the two memory commands, global context limits, backups, and a file-based memory store. OpenCode controls providers, authentication, model selection/switching, sessions, filesystem and shell tools, native compaction, and runtime execution.

Anvil installs the neutral harness into OpenCode's global config directory (`$XDG_CONFIG_HOME/opencode`, default `~/.config/opencode`). It does not change repository-owned `AGENTS.md`, `.opencode`, `opencode.json(c)`, `.claude`, or `.agents` assets. Project configuration has higher precedence and can add capabilities; inspect and doctor report this state rather than deleting team files.

## Installation lifecycle

`make reforge` resolves the latest non-prerelease GitHub release, records its exact version, selects the platform asset, and checks its SHA-256 against the official release API. It downloads that exact version into a temporary staging directory, validates the binary version, writes Anvil into a separate temporary HOME, and asks that candidate OpenCode to resolve the config, list skills, and list agents. Only after those checks pass does it create and verify a protected backup of the active global config and `~/.opencode` installer tree. After one confirmation, it replaces the global config and installs the already-tested binary at OpenCode's official user installer location. A post-reset error invokes rollback.

The old config archive includes provider definitions, global harness files, CLI settings, and any config-local MCP/plugin data. Anvil constructs a fresh config tree. It carries forward only OpenCode `provider` definitions, because those describe how OpenCode exposes user-selected providers/models; it drops the old global `model` and `small_model` defaults. It does not carry forward old agent, skill, command, plugin, MCP, or instruction files.

## Agent and prompt

The global config disables OpenCode's built-in `build`, `plan`, `general`, and `explore` entries using the current `disable` field, and names `anvil` as the default `primary` agent. The Anvil agent has no `model`, `variant`, or custom `prompt`. This leaves the provider/model-native system prompt intact; the compact global `AGENTS.md` adds behavior without replacing that base prompt.

Anvil's tool policy is default-deny. It allows the normal read, search, edit, shell, web, language-server, and interaction tools; it denies `task` and arbitrary skills, and allows only the five Anvil skill names. It retains OpenCode's `.env` read prompts and asks before destructive Git commands. OpenCode's external-directory safeguards remain in place. Hidden maintenance agents such as compaction, title, and summary are not disabled.

## Skills and commands

Skills use OpenCode's native lazy skill discovery under the global `skills/` directory. Their descriptions identify when to load them, while their concise bodies outline the evidence and reasoning workflow. The global prompt does not duplicate domain knowledge.

`remember.md` and `recall.md` are native OpenCode command templates assigned to Anvil. They call a small standard-library memory helper copied into the global config tree. A memory write is available only through an explicit command or direct user request; reads are narrow and on demand.

## Memory

Memory is Markdown plus YAML frontmatter under `$XDG_DATA_HOME/anvil/memory/`, default `~/.local/share/anvil/memory/`. There is no database or index service. The helper searches with ripgrep when available and scores a small candidate set using local text. Writes validate metadata, reject likely duplicates, and atomically replace one file. Memory and OpenCode data are separate: rollback may leave inert Anvil memory in place.

## Reset, backup, and rollback boundary

Backups live in `$XDG_DATA_HOME/anvil/backups/<timestamp>/`. They contain the user/global config archive, the OpenCode installer directory archive, a previous executable copy where available, a read-only inspection, path-update metadata, a manifest, and checksums. Directory archives preserve symlinks without following them; rollback validates members before restoring them.

Provider authentication, OpenCode databases, and session history stay in place. Anvil does not read secrets from those stores or mutate undocumented SQLite schemas. The backup manifest records state paths and whether known files exist, not their contents. Rollback restores global config and the prior installer tree; memory and backups remain.

## Project and organization overrides

The global config cannot remove higher-precedence project config, managed system config, or organization remote config. Reforge only resets the user/global boundary. Doctor reports project files and environment variables that override normal config. It reports the managed global file's MCP count; remote and system policy may add settings outside that file and should be inspected with OpenCode's resolved-config command where the account permits it.
