# Anvil V1 to V2 migration

## Prerequisites

- Linux or macOS with Bash, Python 3.11+, `tar`, and network access to the official npm registry.
- The Anvil-managed OpenCode executable under `~/.opencode/bin/opencode` (or the matching home/XDG paths).
- A valid V1 Anvil global config and enough free disk space for a temporary copy of OpenCode data/state and a private backup.
- Close OpenCode's TUI and background service before starting. Anvil checks for a running OpenCode process and stops before copying if it finds one.

Read-only `make inspect` and `make doctor` can help identify the current setup. `make test` validates the current stable OpenCode 2 candidate in isolated directories.

## What `make upgrade` does

1. Confirms the current global config matches the V1 Anvil baseline (or a valid V2 config for a later V2 update) and the managed binary reports the matching OpenCode generation.
2. Resolves the official npm `latest` tag once to an exact stable OpenCode 2 version, downloads its platform package, checks npm's SHA-512 integrity, and stages the exact executable.
3. Builds the V2 config from repository templates, migrates supported V1 provider/model fields, and retains CLI/TUI preference files.
4. Rehearses the candidate using a private temporary HOME/XDG environment. It copies the current global config, OpenCode data/state directories, and Anvil Markdown memory; applies V2 config there; starts OpenCode 2 against the copied state through native stats; and checks the candidate's actual agent, commands, skills, plugin, and knowledge Reference.
5. Creates and verifies a restrictive, checksummed backup of global config, `~/.opencode`, OpenCode data, OpenCode state, previous installation metadata, executable version, and inspection output.
6. Replaces the live config and executable with that same tested candidate, initializes the separate Anvil knowledge/source directories, writes migration metadata, and runs doctor.
7. Automatically restores the verified snapshot if config replacement, installation, or postflight doctor fails.

For automation, `ANVIL_YES=1 make upgrade` skips the single confirmation after the rehearsal. The upgrade still requires the same safety checks and backup.

## OpenCode migration details

The V2 candidate runs its normal runtime migration only against copied state during rehearsal. OpenCode databases and other state files are copied and archived as opaque files. Anvil does not query SQLite tables or try to downgrade a database schema.

V1 provider definitions are converted to V2 `providers` with the documented `package`, `settings`, `headers`, `body`, and `modelID` forms where applicable. `cli.json`, `tui.json`, and `tui.jsonc` files are retained so OpenCode can perform its documented CLI preference migration on V2 terminal startup. The rehearsal tests native V2 startup and stats; it does not run an interactive TUI.

## Data handling

| Data | Upgrade behavior |
|---|---|
| OpenCode sessions/database | Copied to the rehearsal, retained in place for live migration, backed up opaquely |
| Authentication | Copied as opaque state, never printed or used to make a model request during rehearsal |
| Global OpenCode config | Converted to Anvil V2 and backed up in full |
| CLI/TUI settings | Retained for OpenCode's native V2 preference migration |
| Anvil commands and skills | Replaced with V2 Anvil commands/skills; the pre-upgrade config archive preserves the full V1 tree |
| Anvil Markdown memory | Copied to rehearsal, left in place during upgrade, not rewritten |
| Anvil knowledge | Separate from memory; its reference points to `$XDG_DATA_HOME/anvil/knowledge` |
| OpenCode data/state | Backed up separately as opaque archives |
| Backups | Stored under `$XDG_DATA_HOME/anvil/backups/<timestamp>/` with checksums and restrictive permissions |

Custom provider definitions supported by V1 are migrated. Other user files placed inside the global OpenCode config tree may be replaced by the managed V2 Anvil tree; the full pre-upgrade tree is in the verified backup and can be restored with `make rollback`.

## Post-upgrade checks

`make upgrade` runs doctor after installation. Review:

```bash
make doctor
make stats
```

Doctor validates config and performs an isolated runtime smoke test without using the live OpenCode database. Stats reads OpenCode's native local usage data in standalone mode.

## Rollback

Run:

```bash
make rollback
```

Rollback restores the saved V1 config, installer tree/binary, OpenCode data, and OpenCode state. It does not attempt an in-place database downgrade. Current Anvil memory is archived before rollback and remains at `$XDG_DATA_HOME/anvil/memory/`.

If automatic rollback itself fails, the command reports the verified backup path. Keep the backup intact and inspect its manifest/checksums before any manual recovery.

## Failure behavior and known risks

- A candidate/rehearsal failure aborts before live backup or mutation.
- A backup creation or verification failure aborts before live mutation.
- After the first live mutation, failures invoke rollback using the just-created verified snapshot.
- A power loss, forced process termination, filesystem failure, or full disk can prevent both upgrade completion and automatic rollback. The backup remains the recovery source.
- OpenCode data may contain credentials and session content. Backups are private to the user and should be handled accordingly.
- System/organization/project settings and environment overrides can affect the effective OpenCode runtime outside Anvil's managed global config.
