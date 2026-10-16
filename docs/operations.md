# Operations

## Inspect before changing state

`make inspect` reports the OpenCode executable/version and installation paths, managed config/CLI paths, global agents, skills, plugins, MCPs and commands, safely detectable authentication/session presence, and current workspace overrides. It avoids printing credential values and does not change OpenCode state.

`make capabilities` answers which features are available on the detected runtime. `FORMAT=json make capabilities` emits machine-readable JSON. `make doctor` answers whether the installed Anvil/runtime combination is healthy.

## Upgrade Anvil

```bash
make inspect
make upgrade DRY_RUN=1
make upgrade
make doctor
```

`make upgrade` updates Anvil and preserves the installed OpenCode major. It stages the latest stable candidate within that existing major, builds the matching runtime config, and rehearses against copies of config, OpenCode data/state, and Anvil Markdown memory under a temporary HOME/XDG tree. The candidate starts on copied state through its native stats command; Anvil validates its config, agent, commands and skills. Only after rehearsal succeeds does Anvil create and verify a complete backup, install the exact tested candidate, record migration metadata, and run postflight doctor. Failed postflight checks trigger rollback.

`make upgrade DRY_RUN=1` performs candidate staging and isolated rehearsal, prints the target runtime profile and capability differences, then stops before a live backup or file change. Set `ANVIL_YES=1` only for reviewed non-interactive runs.

## Explicit runtime migration

A major migration is a separate operation and must name its target:

```bash
make migrate-runtime OPENCODE_MAJOR=2 DRY_RUN=1
make migrate-runtime OPENCODE_MAJOR=2
```

Use `OPENCODE_MAJOR=1` for the reverse migration. The requested major must be supported and differ from the current major. Migration uses profile-specific config, official candidate verification, isolated rehearsal, a complete backup, doctor, and rollback. It never runs implicitly as part of `make upgrade`.

## Reforge

`make reforge` is the clean install/rebuild path for first install, explicit rebuild, or recovery from a corrupted managed setup. A first install follows `config/runtime-policy.json` (currently OpenCode 1). When a runtime already exists, reforge preserves its detected major. It stages and validates a candidate, creates a backup, applies the matching config adapter, installs the candidate, and runs doctor.

Close OpenCode's TUI and background service before reforge, upgrade, or runtime migration. Anvil checks for an active same-user OpenCode process and aborts before copying if one is running, so the snapshot does not race a changing database.

OpenCode 1 stable candidates come from official GitHub releases and are checked against published SHA-256 asset digests. OpenCode 2 stable candidates come from the official npm `@opencode/cli` package and are checked against published SHA-512 integrity metadata. Network or digest failures stop staging; Anvil does not substitute an unverified binary.

## Doctor and stats

`make doctor` checks Anvil release metadata, runtime support/profile, matching config adapter, agent policy, commands/skills, memory, knowledge access, source-registry validity/drift, migration metadata, and visible project overrides. It reports `HEALTHY`, `WARNING`, or `BROKEN` with exit codes `0`, `2`, or `1`. A supported older Anvil install is reported as `UPGRADE AVAILABLE` with exit code `0`.

`make stats` uses the detected runtime's native output. OpenCode 1 provides terminal text; OpenCode 2 provides structured JSON that Anvil formats. If stats are unavailable or fail, Anvil prints a notice and exits successfully without inventing token or cost values. No separate usage database is created.

## Backup and sensitive data

Backups are stored under `$XDG_DATA_HOME/anvil/backups/<timestamp>/` with restrictive permissions. They include checksummed archives of global config, the `~/.opencode` managed installer directory, OpenCode data/state, inspection output, and installation metadata. OpenCode files remain opaque; Anvil does not print tokens, inspect undocumented SQLite tables, or modify their schemas. Provider/authentication/session state can be sensitive, so handle archives accordingly.

The manifest records config/runtime/data/state paths, whether they existed, prior Anvil/OpenCode versions where available, candidate version, executable details, PATH update metadata, and archive checksums. Legacy installations without Anvil version metadata remain explicitly unversioned.

## Rollback

```bash
make rollback
```

Rollback selects the newest valid backup, verifies checksums, and confirms it belongs to the current home/XDG paths. It restores the saved config, installer directory/binary, OpenCode data, and state instead of attempting an in-place database downgrade.

Before restoring, rollback archives current Anvil Markdown memory separately under `$XDG_DATA_HOME/anvil/memory-backups/` and leaves the live memory directory intact. Knowledge, source registry, and backup history remain under the Anvil data root.

If automatic rollback reports failure, preserve the verified backup and review its manifest/checksums. The command prints its path; do not delete it until recovery is complete.

## Project and organization overrides

Anvil changes only the managed user/global config boundary. It does not edit repository-owned `AGENTS.md`, `.opencode/`, `opencode.json(c)`, `.claude/`, or `.agents/` files. System-managed and organization remote configuration may also affect effective behavior. Doctor reports visible project overrides but cannot enumerate inaccessible remote policy; use OpenCode's resolved config/debug commands where available. See [OpenCode compatibility](opencode-compatibility.md) and [runtime compatibility](runtime-compatibility.md).
