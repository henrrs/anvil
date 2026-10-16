# Anvil runtime compatibility

**Checked:** 2026-10-16 (UTC)
**Anvil release:** `2.3.0`
**Policy:** OpenCode 1.x and 2.x supported; default major `1`; automatic major upgrade disabled.

| Anvil | OpenCode runtime | Minimum | 2.3 offline profile fixture | Adapter | Support |
|---|---|---:|---:|---|---|
| 2.3.x | 1.x | 1.18.18 | 1.18.18 | `opencode-v1` | Supported |
| 2.3.x | 2.x | 2.0.0 | 2.0.0 | `opencode-v2` | Supported |

The 2.3 mandatory suite validates both adapter contracts using checked-in local CLI fixtures. It does not download or claim to smoke-test a live OpenCode release. The last recorded official candidate resolution in the preceding runtime release documentation was OpenCode 1 `1.19.3` and OpenCode 2 `2.0.31`; use the official release references below to revalidate live candidates before future releases.

## Common and runtime-specific capabilities

Both profiles provide the single Anvil agent, Markdown commands and skills, file memory, `/remember`, `/recall`, `/distill`, source registry, explicit reconciliation, and Databricks provider capability through shared scripts. Databricks does not require an OpenCode plugin, MCP, or a V2-only permission/tool API.

OpenCode 1 uses its singular `agent`/`permission` config shape. It has no Anvil native memory-search tool or native Knowledge Reference, so shared Python file search and named-file reads are used. Its native stats command produces terminal text. OpenCode 2 uses plural `agents`/`plugins`, ordered permissions, the local read-only `anvil-core` search tool, `anvil-knowledge` Reference, and structured stats JSON. Shared commands, skills, memory, and Databricks integration remain the same.

Runtime behavior is exposed through `scripts/runtime.py`. `make capabilities` combines runtime capability data with the current non-secret Databricks CLI/profile/compute state. `FORMAT=json make capabilities` emits one JSON object with `runtime`, `databricks`, and `databricks_capabilities` keys.

## Databricks CLI compatibility

**Documentation checked:** 2026-10-16 (UTC)
**Minimum supported CLI:** `1.0.0`
**Validated CLI range:** the offline CLI fixture exercised the `1.0.0` minimum boundary; no real CLI version was exercised by the mandatory suite. There is no upper version pin.

The preferred official `databricks` CLI minimum is 1.0.0. When a supported CLI is absent or too old, only an explicit `make databricks-setup` attempts installation from the official GitHub release with SHA-256 validation. Anvil installs it under its own user-local data directory, never elevates privileges, and retains the prior executable. See the [official installation guide](https://docs.databricks.com/aws/en/dev-tools/cli/install).

The CLI provider uses `databricks auth profiles`, non-sensitive `databricks auth describe`, `databricks current-user me`, supported cluster and warehouse list commands, and REST requests through `databricks api`. The SDK fallback uses the official Python SDK 0.141.0 in Anvil's isolated virtual environment and supports WorkspaceClient, Command Execution and Statement Execution. Both reuse supported Unified Authentication profiles. Anvil stores only a selected profile, workspace host, absolute executable path, provider health metadata, schema version, and capability map.

## Databricks integration limits

- Remote Python uses the Command Execution API on a running classic all-purpose cluster. It does not start stopped compute; serverless/job clusters are not selected for this path.
- SQL uses Statement Execution on a running SQL warehouse, with inline JSON results bounded to 100 rows and 1 MB. Multiple running resources require a user choice.
- System-table status probing uses a running warehouse only when exactly one is available. It does not start a warehouse or choose among several.
- SQL Connector is optional and specialized; Databricks Connect is for Spark development and is not the remote-Python fallback. The official VS Code extension is assisted, not automated.
- Workspace grants, cloud/region, table state, preview enrollment, catalog enablement, delivery latency, and configured retention determine live table access. The checked-in snapshot is dated guidance, not a runtime guarantee.
- Offline fixtures verify CLI/API contracts, provider routing, installation behavior, PATH regression, SDK fallback and error handling; no Databricks workspace was contacted for Anvil 2.3 validation.

## Lifecycle and migration

- `make reforge` follows the first-install policy default and retains the detected runtime major when rebuilding.
- `make upgrade` updates Anvil and preserves the installed OpenCode major.
- `make migrate-runtime OPENCODE_MAJOR=N` is the explicit runtime-major change operation.
- `make upgrade DRY_RUN=1` and runtime migration dry runs stage and rehearse without changing live user files.
- `make rollback` restores the latest verified runtime/config/data/state snapshot. Anvil's current Markdown memory remains portable and is archived separately.

OpenCode databases remain opaque files. Runtime-specific behavior is exercised using offline OpenCode CLI fixtures in `make test`; live candidate release and digest verification are part of installation/upgrade, not the mandatory test suite.

## Official sources

- [OpenCode 1 documentation](https://opencode.ai/docs/)
- [OpenCode 1 skills](https://opencode.ai/docs/skills/)
- [OpenCode 2 configuration](https://dev.opencode.ai/v2/docs/config/)
- [OpenCode 2 agents](https://dev.opencode.ai/v2/docs/agents/)
- [OpenCode skills](https://opencode.ai/docs/skills/)
- [OpenCode 1 releases](https://github.com/anomalyco/opencode/releases)
- [Official OpenCode 2 npm package](https://www.npmjs.com/package/@opencode/cli)
- [Databricks CLI installation](https://docs.databricks.com/aws/en/dev-tools/cli/install)
- [Databricks CLI authentication commands](https://docs.databricks.com/aws/en/dev-tools/cli/reference/auth-commands)
- [OAuth U2M authentication](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m)
- [Databricks unified authentication](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth)
- [Command Execution API](https://docs.databricks.com/api/command-execution/v2/command-execution)
- [Statement Execution API](https://docs.databricks.com/api/statement-execution/v1/statement-execution)
- [Databricks system tables](https://docs.databricks.com/aws/en/admin/system-tables)

Recheck official runtime releases, configuration schemas, CLI auth behavior, APIs, and system-table documentation before each release that changes these integration contracts.
