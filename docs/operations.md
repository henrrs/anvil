# Operations

## Inspect before changing state

`make inspect` reports local Anvil/OpenCode versions, the absolute executable, runtime adapter and compatibility, PATH readiness, local provider inventory, config paths, agents, skills, plugins, MCPs and commands, and current workspace overrides. It does not contact release services or a Databricks workspace.

`make capabilities` answers which features are available on the detected runtime. `FORMAT=json make capabilities` emits machine-readable JSON. `make doctor` answers whether the installed Anvil/runtime combination and configured Databricks integration are healthy. Doctor performs read-only identity and core metadata requests only when an Anvil-owned Databricks profile exists; with no profile it stays local.

## Upgrade Anvil

```bash
make inspect
make upgrade DRY_RUN=1
make upgrade
make doctor
```

`make upgrade` upgrades Anvil only and preserves the exact validated OpenCode executable and version. It uses local runtime discovery, builds the matching Anvil config, and rehearses with the local runtime against copied config, OpenCode data/state, and Anvil Markdown memory under a temporary HOME/XDG tree. It does not resolve a release, download or install OpenCode, edit `PATH`, contact Databricks, or change OpenCode data/state. It creates an Anvil-scoped backup, applies Anvil files and metadata, and runs doctor in local-only postflight mode. Failed postflight checks restore Anvil config/metadata while leaving OpenCode untouched.

`make upgrade DRY_RUN=1` is fully local and stops after rehearsal before a live backup or file change. It prints `Network required NO` and `PRESERVE EXACT VERSION`. Set `ANVIL_YES=1` only for reviewed non-interactive runs.

## OpenCode runtime update

```bash
make update-runtime DRY_RUN=1
make update-runtime
```

This explicit operation resolves and installs the latest stable supported OpenCode release within the current major. It rehearses against the current Anvil config and copied user state, backs up runtime/config/data/state, and updates the executable. It preserves the installed Anvil release and config. A release lookup or download failure leaves both products unchanged.

## Explicit runtime migration

A major migration is a separate operation and must name its target:

```bash
make migrate-runtime OPENCODE_MAJOR=2 DRY_RUN=1
make migrate-runtime OPENCODE_MAJOR=2
```

Use `OPENCODE_MAJOR=1` for the reverse migration. The requested major must be supported and differ from the current major. Migration uses profile-specific config, official candidate verification, isolated rehearsal, a complete backup, doctor, and rollback. It never runs implicitly as part of `make upgrade`.

## Reforge

`make reforge` rebuilds Anvil config using the exact existing healthy supported runtime and does not resolve or replace it. If OpenCode is genuinely absent, a first installation follows `config/runtime-policy.json` (currently OpenCode 1), and network access may be needed to resolve/install that runtime. An existing but unhealthy or unsupported executable is reported for explicit repair/update instead of silently replaced. Reforge creates an Anvil-only backup when reusing a runtime and a full runtime snapshot when provisioning one.

Close OpenCode's TUI and background service before reforge, upgrade, or runtime migration. Anvil checks for an active same-user OpenCode process and aborts before copying if one is running, so the snapshot does not race a changing database.

OpenCode 1 stable candidates come from official GitHub releases and are checked against published SHA-256 asset digests. OpenCode 2 stable candidates come from the official npm `@opencode/cli` package and are checked against published SHA-512 integrity metadata. Network or digest failures stop staging; Anvil does not substitute an unverified binary.

## Doctor and stats

`make doctor` checks Anvil release metadata, local runtime support/profile, matching config adapter, agent policy, commands/skills, memory, knowledge access, source-registry validity/drift, migration metadata, Databricks readiness, and visible project overrides. With a configured Anvil profile it validates current identity, cluster listing, and warehouse listing using bounded read-only calls. A missing profile is reported as `NOT_CONFIGURED` without network access. Doctor does not use OpenCode release services. Lifecycle postflight sets `ANVIL_DOCTOR_LOCAL=1` to avoid workspace requests. It reports `HEALTHY`, `WARNING`, or `BROKEN` for the Anvil/runtime installation with exit codes `0`, `2`, and `1`; Databricks readiness is printed as its own domain result. A supported older Anvil install is reported as `UPGRADE AVAILABLE` with exit code `0`.

`make stats` uses the detected runtime's native output. OpenCode 1 provides terminal text; OpenCode 2 provides structured JSON that Anvil formats. If stats are unavailable or fail, Anvil prints a notice and exits successfully without inventing token or cost values. No separate usage database is created.

## Backup and sensitive data

Backups are stored under `$XDG_DATA_HOME/anvil/backups/<timestamp>/` with restrictive permissions. Each manifest records `anvil` or `runtime` scope. Anvil-scope snapshots contain managed config and Anvil runtime/installation metadata only. Runtime-scope snapshots also contain the `~/.opencode` installer directory, OpenCode data/state, inspection output, and executable backup. OpenCode files remain opaque; Anvil does not print tokens, inspect undocumented SQLite tables, or modify their schemas. Provider/authentication/session state can be sensitive, so handle runtime archives accordingly.

The manifest records config/runtime/data/state paths, whether they existed, prior Anvil/OpenCode versions where available, candidate version, executable details, PATH update metadata, and archive checksums. Legacy installations without Anvil version metadata remain explicitly unversioned.

## Rollback

```bash
make rollback
```

Rollback selects the newest valid backup, verifies checksums, and confirms it belongs to the current home/XDG paths. The snapshot scope determines what is restored: Anvil-only rollback restores Anvil config/metadata and preserves OpenCode executable/data/state; runtime rollback restores the saved config, installer directory/binary, OpenCode data, and state instead of attempting an in-place database downgrade.

Before restoring, rollback archives current Anvil Markdown memory separately under `$XDG_DATA_HOME/anvil/memory-backups/` and leaves the live memory directory intact. Knowledge, source registry, and backup history remain under the Anvil data root.

If automatic rollback reports failure, preserve the verified backup and review its manifest/checksums. The command prints its path; do not delete it until recovery is complete.

## Project and organization overrides

Anvil changes only the managed user/global config boundary. It does not edit repository-owned `AGENTS.md`, `.opencode/`, `opencode.json(c)`, `.claude/`, or `.agents/` files. System-managed and organization remote configuration may also affect effective behavior. Doctor reports visible project overrides but cannot enumerate inaccessible remote policy; use OpenCode's resolved config/debug commands where available. See [OpenCode compatibility](opencode-compatibility.md) and [runtime compatibility](runtime-compatibility.md).
