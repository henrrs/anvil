# Operations

## Read-only inspection

`make inspect` reports the OpenCode executable/version and detectable install method; config, CLI, data, and state paths; global agents, skills, plugins, MCPs, commands, and instructions; safely detectable authentication/session presence; and current-workspace OpenCode/project instruction files. It reads config names/metadata, never prints provider credentials, and does not alter OpenCode state. The LOW/MEDIUM/HIGH context-pollution assessment is qualitative.

## Reforge

1. Confirm Bash, Python 3.11+, `tar`, `unzip` on macOS, internet access, and a writable user home.
2. Run `make inspect` and review global and current project state.
3. Run `make test`; it downloads the current official stable OpenCode artifact and validates it in a temporary HOME.
4. Run `make reforge`. It stages and validates one exact release, constructs the replacement config, then creates and verifies the backup.
5. Review the one confirmation prompt. Set `ANVIL_YES=1` only when a non-interactive run should proceed.
6. Reopen the shell if Anvil added `~/.opencode/bin` to its startup PATH.
7. Run `make doctor`.

If release metadata, checksum verification, candidate config validation, or backup verification fails, reforge aborts before destructive changes. If an operation fails after config replacement begins, the script attempts rollback from that verified backup. It reports the backup location if automatic rollback also fails.

## Backup contents and sensitive data

Backup directory permissions are restricted to the current user. Archives may contain provider config values, custom endpoints, user instructions, and plugin source from the old global config. They do not contain the contents of OpenCode authentication/session databases. A separate copy of the resolved executable is kept when readable; the full `~/.opencode` directory is also archived. The manifest records paths, versions, presence, path-entry changes, release candidate, and artifact checksums.

`make rollback` chooses the newest valid backup by timestamp and verifies every listed checksum before restoring. To avoid accidental restore into a different home/config root, the current config and installer paths must match the backup manifest. Rollback does not delete backups or Anvil memory. If reforge added a marked PATH line, rollback removes that exact line and its marker while retaining other startup-file content.

## What stays in place

OpenCode provider authentication, session databases, and other data/state remain in their OpenCode locations. Anvil does not clear them, export them, or update undocumented database tables. Existing provider definitions from the global JSON/JSONC config are copied into the new config; the old global default model is removed. Reforge replaces CLI UI preferences with the new clean config tree, but rollback restores them.

Project configuration, project skills/plugins/MCPs, system-managed settings, and organization remote config are outside Anvil's reset boundary. Inspect and doctor identify local project assets; the effective runtime may also include managed or remote sources described in [OpenCode compatibility](opencode-compatibility.md).

## Status codes

Doctor exits `0` for healthy, `2` when the managed baseline is valid but a project/environment override warning is active, and `1` for a broken Anvil baseline or missing required component. This makes warnings visible to automation without treating them as a failed global install.

## Recovery

If automatic rollback fails, use the printed verified backup path and run `make rollback` after resolving the stated issue. If the latest backup is invalid, rollback skips it and selects the newest valid one; backups are never removed automatically. If no backup is valid, restore the saved config and installer directory manually from the archive only after reviewing the `manifest.json` and checksums.
