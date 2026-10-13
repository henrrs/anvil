# Operations

## Inspect before changing state

`make inspect` reports the OpenCode executable/version and installation paths, managed config and CLI paths, global agents, skills, plugins, MCPs and commands, safely detectable authentication/session presence, and current workspace overrides. It avoids printing credential values and does not change OpenCode state.

## Upgrade an existing Anvil installation

```bash
make inspect
make test
make upgrade
make doctor
```

`make upgrade` requires a supported Anvil V1 or V2 managed config plus a matching OpenCode major version. The executable can be Anvil-managed or resolved from the current `PATH`; a verified copy is included in the rollback snapshot. Close the OpenCode TUI and background service first. Anvil checks for a same-user OpenCode process and aborts before copying if one is active, so it does not snapshot a changing database.

Upgrade resolves the official npm `latest` dist-tag once, requires a stable OpenCode `2.x.y`, downloads and verifies the exact host package using its published SHA-512 SRI value, and stages one executable. The exact staged candidate is used for the isolated rehearsal and eventual install. Rehearsal copies the global config, OpenCode data/state, and Anvil memory to a private temporary HOME/XDG environment; runs native V2 stats on copied state; validates real candidate discovery of the Anvil agent, commands, skills, plugin, and Reference; and runs doctor. No provider/model request is made.

After the rehearsal succeeds, Anvil creates a mode-restricted backup and verifies its checksums before replacing live config or runtime. Then it records migration metadata and runs doctor. Failures after the first live mutation invoke automatic rollback. Set `ANVIL_YES=1` only for a reviewed non-interactive lifecycle run; otherwise the script asks for one confirmation after rehearsal.

## Clean reforge

`make reforge` remains the path for first install, explicit clean rebuild, or recovery from a corrupted managed setup. It replaces the managed global Anvil configuration baseline after staging and validating one exact official candidate and creating a backup. It is not the normal V1-to-V2 migration path.

## Doctor and stats

`make doctor` checks V2 config structure, the primary model-neutral agent and permissions, the managed skills and commands, plugin entrypoint, memory, knowledge root, source registry, installation/migration metadata, and visible project overrides. High-level statuses are `HEALTHY`, `WARNING`, and `BROKEN`; exit codes are `0`, `2`, and `1` respectively. A supported V1 installation is reported as `UPGRADE REQUIRED` with exit code `0`.

`make stats` invokes OpenCode's native structured stats in standalone mode and formats period, model, token, and available cost totals. It does not create a separate usage database. No historical usage is a valid empty result. Before OpenCode 2 is installed, it prints first-install or migration guidance and exits successfully without a report.

## Backup and sensitive data

Backups are stored under `$XDG_DATA_HOME/anvil/backups/<timestamp>/` with restrictive permissions. They include checksummed archives of the global config, `~/.opencode` installer directory, OpenCode data and state, plus inspection output and installation metadata. Archives preserve files opaquely; Anvil does not print tokens, inspect undocumented SQLite tables, or modify their schemas. Provider/authentication/session state can be sensitive, so treat the archive accordingly.

The manifest records config/runtime/data/state paths, whether they existed, prior Anvil/OpenCode versions where available, candidate version, executable details, PATH update metadata, and archive checksums. No exact V1 Anvil patch release is invented for an installation that did not record it.

## Rollback

```bash
make rollback
```

Rollback selects the newest valid backup, verifies checksums, and confirms it belongs to the current XDG/home paths. It restores the complete saved config, installer directory/binary, OpenCode data, and state. This restores the previous runtime snapshot; it does not attempt to downgrade migrated database files in place.

Before restoring, rollback archives current Anvil Markdown memory separately under `$XDG_DATA_HOME/anvil/memory-backups/` and leaves the current memory directory intact. The Anvil memory format remains V1-compatible. Knowledge, the source registry, and backup history remain in Anvil's data root.

If automatic rollback reports failure, preserve the backup and review its `manifest.json` and checksums. The command prints the verified backup path; do not delete it until recovery is complete.

## Project and organization overrides

Anvil changes only the managed user/global config boundary. It does not edit repository-owned `AGENTS.md`, `.opencode/`, `opencode.json(c)`, `.claude/`, or `.agents/` files. System-managed and organization remote configuration may also affect the effective runtime. Doctor reports visible project overrides but cannot enumerate inaccessible remote policy; use OpenCode's resolved config and debug commands where available. See [OpenCode compatibility](opencode-compatibility.md).
