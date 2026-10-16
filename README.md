# Anvil

> **Anvil — A lean, model-agnostic OpenCode harness designed to maximize reliable task completion while minimizing unnecessary context and token usage.**
>
> **Better harness. Better execution.**

Anvil 2.3's release theme is **Databricks Provider Independence**: integrate with Databricks capabilities, not one client.

```bash
# First installation
make reforge
make doctor

# Upgrade Anvil while keeping the installed OpenCode major
make test
make upgrade DRY_RUN=1
make upgrade

# Explicitly migrate runtime major when approved
make migrate-runtime OPENCODE_MAJOR=2 DRY_RUN=1
make migrate-runtime OPENCODE_MAJOR=2
```

Use `make inspect` to review the current setup before changing it. Use `make capabilities` to see the features and fallbacks available with the detected runtime; `FORMAT=json make capabilities` prints machine-readable output. Use `make rollback` to restore the latest verified runtime snapshot. `make upgrade` upgrades Anvil without changing the OpenCode major. Runtime-major changes require the explicit `make migrate-runtime OPENCODE_MAJOR=N` command.

Anvil is a lean, model-agnostic harness and lifecycle layer for OpenCode 1.x and 2.x. Anvil's release version is independent from the OpenCode major. OpenCode owns model/provider authentication, sessions, its native tools, and runtime state. Anvil supplies a focused behavioral environment: compact instructions, one primary agent, a small set of skills, explicit file memory, evidence-driven workflows, safe upgrade and recovery operations, and an optional CLI-backed Databricks capability.

## Why Anvil?

Anvil means a blacksmith's anvil: the stable base on which material is shaped, refined, and made useful. The anvil is not the material and does not supply all the energy; it provides a dependable surface for the work.

Anvil plays that role for language models. It does not create or route models. It gives the selected model disciplined context, useful skills and memory, clear execution rules, and verification. Models may change; the harness remains the foundation.

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

## Install and upgrade

Prerequisites: Linux or macOS, Bash, Python 3.11+, `tar`, and access to the official OpenCode release source when installing or upgrading the managed runtime. OpenCode 1 candidates come from official GitHub release artifacts with published SHA-256 digests. OpenCode 2 candidates come from the official npm package with published SHA-512 integrity metadata. Windows users can run Anvil under WSL. Databricks is optional and does not affect the rest of Anvil.

`make inspect` reads the current OpenCode setup without changing it. `make test` validates both runtime profiles, memory behavior, lifecycle, rollback, failure recovery, and Databricks contracts with local fixtures. It makes no external OpenCode, Databricks, or model calls.

For a first installation, run `make reforge`, then `make doctor`. The checked-in runtime policy supports OpenCode 1.x and 2.x and defaults to OpenCode 1.x; an existing supported runtime major is preserved during a reforge. Set `default_major` in `config/runtime-policy.json` only when a different runtime is approved for new installations. `make inspect`, `make capabilities`, and the Anvil memory helpers can be used without OpenCode 2.

`make upgrade` upgrades Anvil and keeps the installed OpenCode major. It rehearses the target config/runtime using copied config, OpenCode data/state, and Anvil memory under a temporary HOME/XDG tree. `make upgrade DRY_RUN=1` stages and rehearses the change, reports the candidate and target adapter, and stops before creating a live backup or changing user files. A normal upgrade creates and verifies a complete backup before installing the exact rehearsed candidate. Failed postflight checks trigger automatic rollback.

Use `make migrate-runtime OPENCODE_MAJOR=2` only when a move to OpenCode 2 is explicitly approved. The command requires the requested major, rehearses against copied user state, backs up the current runtime/config/data/state, and rolls back on a post-mutation failure. `make migrate-runtime OPENCODE_MAJOR=1` provides the reverse migration path when OpenCode 1 is approved and supported.

`make reforge` remains the clean install and rebuild path. It follows the approved runtime policy for first installation and preserves the detected OpenCode major for rebuilds. Anvil installs a managed OpenCode candidate under `~/.opencode/bin` and updates a supported shell startup file if necessary.

## Databricks

Databricks is optional. Normal `make reforge` and `make upgrade` do not install Databricks tools or contact a workspace. Run `make databricks-setup` when you explicitly want Anvil to configure Databricks. It attempts the official CLI release first, verifies its SHA-256 checksum, installs only under Anvil's user-local data directory without privilege elevation, and prepares an isolated Python SDK fallback if CLI setup is unavailable.

Use `make databricks-setup DRY_RUN=1` to inspect the proposed actions and local auth/provider discovery without network access or state changes. A healthy CLI stays the preferred general provider. If installation is blocked, the official Databricks SDK can reuse supported Unified Authentication profiles in `.databrickscfg`; Anvil stores only non-secret provider metadata. The optional SQL Connector and Databricks Connect are recognized for their specialized paths. The official VS Code extension is reported as an assisted workflow, never automated through private IDE APIs.

Anvil discovers a previously verified CLI by its absolute path even if a later shell has a different `PATH`. `make doctor` and `make capabilities` report PATH visibility, provider health, and the active provider per capability. Databricks capabilities still preserve Anvil 2.2's running-compute checks, bounded Python/SQL results, system-table read-only behavior, and no-silent-mutation rules. See [Databricks setup and provider docs](docs/databricks/README.md).

Backups live under `$XDG_DATA_HOME/anvil/backups/` (default `~/.local/share/anvil/backups/`). They use restrictive permissions and include checksums plus the prior config, installer runtime, OpenCode data and state, and install metadata. OpenCode databases are treated as opaque files; Anvil does not edit undocumented schemas. Backups may contain sensitive session or authentication state.

## Memory and knowledge

Anvil keeps Markdown memory under `$XDG_DATA_HOME/anvil/memory/`. Existing V1 entries remain readable without rewriting. Search is lexical, accent-insensitive, bounded, and can use aliases for multilingual retrieval. Memory is not a database, vector index, or automatic transcript store.

- `/remember` saves a specific fact or decision the user explicitly wants retained.
- `/recall` searches existing entries and returns a small relevant set.
- `/distill` turns explicitly named documents, pasted content, or evidence into a small set of reusable memories with provenance. It checks duplicates, preserves historical or conflicting claims, and detects unchanged sources so they are not reprocessed unnecessarily.

Persistent writes require explicit `/remember`, `/distill`, or direct user intent. Knowledge documents remain the source material; memory contains compact derived claims. The `anvil-knowledge` OpenCode Reference points to the separate `$XDG_DATA_HOME/anvil/knowledge/` directory.

On OpenCode 2, Anvil's local `anvil-core` plugin exposes one bounded, read-only `anvil_memory_search` tool. OpenCode 1 uses the same Python lexical search helper through the `/recall` and memory skill workflow. Neither adapter rewrites prompts, routes models, or writes memories implicitly. Native `anvil-knowledge` References are available on OpenCode 2; OpenCode 1 accesses explicitly named knowledge files through normal file reads.

## Models, agents, and skills

Anvil configures one model-neutral `anvil` primary agent. No model is pinned; select models through OpenCode as usual. The four built-in user-facing agents are disabled, subagents are denied, and no MCP servers are enabled by default. Five allowlisted skills cover memory, Spark performance, Delta Lake, Databricks, and data ingestion.

## Recovery and status

`make rollback` restores the latest verified pre-upgrade/rebuild OpenCode config, executable, data, and state snapshot. Current Anvil Markdown memory is archived separately before rollback and remains portable. Rollback restores the original runtime snapshot rather than trying to downgrade a migrated database.

`make doctor` checks the selected config adapter and agent policy, commands and skills, runtime support, memory, knowledge access, source registry, migration metadata, and visible workspace overrides. It reports `HEALTHY`, `WARNING`, or `BROKEN`; exit codes are `0`, `2`, and `1` respectively. A supported installation on an older Anvil release is reported as `UPGRADE AVAILABLE` with exit code `0`. `make stats` uses OpenCode 2's structured JSON report or OpenCode 1's native text report; unavailable metrics are reported without invented values.

## Version history

See the [runtime capability matrix](docs/versions/README.md), [V1 history](docs/versions/v1.md), [V2 release notes](docs/versions/v2.md), [Anvil 2.1 release notes](docs/versions/v2.1.md), [Anvil 2.2 release notes](docs/versions/v2.2.md), [Anvil 2.3 release notes](docs/versions/v2.3.md), [runtime compatibility](docs/runtime-compatibility.md), [V1-to-V2 migration guide](docs/migrations/v1-to-v2.md), [Anvil 2.0-to-2.1 migration guide](docs/migrations/v2-to-v2.1.md), [Anvil 2.1-to-2.2 migration guide](docs/migrations/v2.1-to-v2.2.md), [Anvil 2.2-to-2.3 migration guide](docs/migrations/v2.2-to-v2.3.md), [memory behavior](docs/memory.md), and [OpenCode compatibility](docs/opencode-compatibility.md).
