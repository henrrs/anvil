# Anvil

> Anvil — A lean, model-agnostic OpenCode harness designed to maximize reliable task completion while minimizing unnecessary context and token usage.
>
> **Better harness. Better execution.**

```bash
make inspect
make test
make reforge
make doctor
```

Restore the most recent pre-reforge setup with `make rollback`.

Anvil is a model-agnostic harness for OpenCode. OpenCode remains responsible for providers, authentication, models, sessions, native tools, file access, shell execution, and compaction. Anvil standardizes the global instructions, one primary coding agent, five lazy skills, two memory commands, and a small file-based memory store.

## Why Anvil?

An anvil is the steady base on which metal is shaped, refined, and made useful. It is not the material being worked, and it does not replace the craft or energy that shapes it. It provides a reliable surface for that work.

Anvil plays the same role for language models. It does not create or select a model. It gives the model a disciplined environment: focused context, relevant skills and memory, useful tools, clear execution rules, and verification. The model can change; the harness remains the consistent foundation.

```text
Luna / Terra / Sol / Astra / Sonnet / other models
                         │
                         ▼
                   Anvil harness
       context · skills · memory · tools · rules
                         │
                         ▼
              reliable, verified execution
```

## Why `make reforge`?

To forge is to shape material into something useful; to reforge is to shape it again. `make reforge` rebuilds the global OpenCode harness from a clean Anvil baseline. It validates the selected OpenCode release and creates a verified backup before applying that setup.

## Install

Prerequisites: Linux or macOS, Bash, Python 3.11+, `tar`, and internet access for the official OpenCode release check and download. On macOS, `unzip` is also needed for the official release archive. On Windows, run Anvil under WSL.

`make inspect` reads the active global and current project setup without changing it. `make test` downloads the current official stable OpenCode candidate, verifies the release checksum, tests it under an isolated HOME, and runs fixture backup/rollback/failure checks. It never uses the real OpenCode directories for test state.

`make reforge` stages and validates one exact OpenCode release before replacing the active global config. It creates a verified backup first, then asks once before the reset. For a confirmed automation run, set `ANVIL_YES=1`. The official user install location is `~/.opencode/bin`; if needed, Anvil adds that directory to the selected shell startup file so a new shell can find it.

Backups are stored at `~/.local/share/anvil/backups/<timestamp>/` (or under `$XDG_DATA_HOME/anvil/backups/`). Each contains a manifest, SHA-256 checksums, the old global config and installer directory, inspection output, and a copy of the previous executable when available. Backups can contain provider configuration and are restricted to the current user.

`make doctor` checks the installed Anvil baseline and the current workspace for project overrides. Exit codes are `0` healthy, `2` warning, and `1` broken. A warning means repository or environment configuration is active and may change the effective agent or capabilities.

## Rollback

`make rollback` verifies and restores the newest valid backup. It restores the global config and the previous `~/.opencode` installer directory, and removes only the PATH entry Anvil added. It does not delete backups. Anvil memory remains under `~/.local/share/anvil/memory/`; it is inert when the Anvil global harness is not active.

Provider authentication and session databases remain in their OpenCode data/state locations throughout reforge and rollback. Anvil does not copy or mutate those databases. The old global CLI config is archived and removed from the active reset config; rollback restores it.

## Using memory

Memory is human-readable Markdown under `$XDG_DATA_HOME/anvil/memory/`, organized into company, project, decision, and lesson folders. Retrieval is narrow text search. There is no database, embedding index, or automatic extraction.

Use `/remember` or explicitly ask OpenCode to remember, save, or store durable information. The command checks for duplicates, keeps the entry's provenance and confidence, and reports its file. Memory is never written just because a conversation contains something that seems important.

Use `/recall` followed by a few search terms. It returns only relevant entries and their provenance; current repository or official source evidence takes precedence over memory.

## Skills and models

OpenCode discovers Anvil's five skills lazily: `anvil-memory`, `anvil-spark-performance`, `anvil-delta-lake`, `anvil-databricks`, and `anvil-data-ingestion`. Anvil denies arbitrary discovered skills and enables only these names. Skills route work to the evidence and reasoning that matter for that domain; they are not reference encyclopedias.

The Anvil agent has no model or variant configured and adds no custom prompt that replaces the provider's native system prompt. Switch models through OpenCode as usual. Anvil does not route or select them.

## What reforge changes

Reforge replaces the user/global OpenCode config tree with the Anvil files. It removes old global agents, skills, plugins, commands, MCP definitions, CLI settings, and global rules from the active config. It selectively carries forward the old OpenCode `provider` definitions so custom provider/model availability is retained, while dropping old global model defaults. It does not merge old global harness files into Anvil.

Reforge does not edit repository-owned `AGENTS.md`, `.opencode/`, `opencode.json(c)`, `.claude/`, or `.agents/` files. Project configuration has higher precedence than the global config. `make inspect` and `make doctor` report project rules, agents, skills, plugins, MCP servers, and config files. Managed system or organization-provided remote configuration may also override user settings; see [OpenCode compatibility](docs/opencode-compatibility.md).

## Troubleshooting

- If reforge stops before its confirmation, no global setup was changed. Check the candidate release download, checksum, or isolated OpenCode smoke-test output.
- If installation fails after the reset begins, Anvil attempts rollback automatically. The verified backup path is included in the error output.
- If `make doctor` returns `2`, inspect its project/environment override paths. The global Anvil installation can be healthy while a repository adds its own agent, skill, or MCP configuration.
- If `opencode` is not found in a new shell, confirm `~/.opencode/bin` is in `PATH` and reopen the shell. Anvil updates the first suitable startup file for the detected shell.
- To validate installed CLI details, use OpenCode's `opencode debug config`, `opencode debug skill`, `opencode agent list`, and `opencode debug paths` commands.

See [operations](docs/operations.md), [architecture](docs/architecture.md), [memory](docs/memory.md), and [testing](docs/testing.md) for the lifecycle details.
