# Anvil V1 and OpenCode 1 runtime migration

This guide covers Anvil V1 installations that use OpenCode 1. The current Anvil 2.1 release can run on supported OpenCode 1.x; installing Anvil 2.1 does not require moving to OpenCode 2.

## Upgrade Anvil and keep OpenCode 1

If the company-approved OpenCode 1 runtime should remain in place, upgrade only the Anvil product:

```bash
make inspect
make upgrade DRY_RUN=1
make upgrade
make doctor
```

The upgrade rebuilds the global Anvil config using the OpenCode 1 adapter and updates the stable runtime candidate within 1.x. It preserves supported V1 provider settings, CLI/TUI preferences, Markdown memory, Anvil data, and opaque OpenCode data/state. The normal upgrade rehearsal, verified backup, doctor, and rollback safeguards still apply.

## Migrate the runtime to OpenCode 2

If OpenCode 2 is explicitly approved, request a runtime migration:

```bash
make migrate-runtime OPENCODE_MAJOR=2 DRY_RUN=1
make migrate-runtime OPENCODE_MAJOR=2
make doctor
make stats
```

The migration renders the native V2 config, maps supported V1 provider/model fields, retains CLI/TUI preference files, and stages one exact stable OpenCode 2 candidate from the official npm package. It verifies npm's SHA-512 integrity metadata before extraction. OpenCode 2 migration changes and plugins are based on the [official V2 V1 migration guide](https://dev.opencode.ai/v2/docs/migrate-v1/).

Before live changes, Anvil copies the config, OpenCode data/state, and Markdown memory into a private temporary HOME/XDG tree. The candidate runs native stats against copied state and Anvil checks the loaded V2 config, commands, skills, plugin, and Knowledge Reference. The rehearsal does not use provider credentials or make a model request. After rehearsal, Anvil creates and verifies a complete backup; postflight failure restores the prior V1 runtime and files.

Use `ANVIL_YES=1 make migrate-runtime OPENCODE_MAJOR=2` only for automation that has already reviewed the migration plan. `make rollback` restores the prior V1 config, runtime, data, and state without attempting an in-place database downgrade.

## Compatibility and data handling

| Data | Anvil 2.1 on OpenCode 1 | Explicit migration to OpenCode 2 |
|---|---|---|
| OpenCode sessions/database | Left in place; backed up opaquely | Copied to rehearsal, left in place during migration, backed up opaquely |
| Authentication | Not printed or used by rehearsal | Copied as opaque state; no provider request |
| Global Anvil config | Rendered using singular V1 schema | Rendered using native V2 schema |
| Provider definitions | Kept in V1 format | Supported provider/model fields mapped to V2 |
| Commands and skills | Shared Markdown files | Shared Markdown files |
| Memory and source registry | Same Markdown/JSON helpers | Same Markdown/JSON helpers |
| Native memory search | Python file helper fallback | Bounded read-only Anvil plugin tool plus helper |
| Knowledge files | Named files read directly | Native Reference plus direct file reads |

The managed global OpenCode config tree is replaced by Anvil's target profile. Other user files inside that tree are retained in the verified pre-migration backup and can be restored with rollback. Project-level, system, or organization-managed configuration is not deleted.

## Failure and rollback

- Candidate, profile-audit, or rehearsal failure stops before backup and live mutation.
- Backup creation/verification failure stops before live mutation.
- Failure after the first live change triggers rollback from the verified snapshot.
- Power loss, disk exhaustion, or filesystem failure can interrupt both migration and automatic rollback; retain the backup directory for recovery.

OpenCode databases are treated as opaque. Rehearsal starts the target runtime against copied state using its documented native stats path; it does not inspect SQLite tables or claim that every unexercised TUI/authentication flow was tested. For the current policy, version floor, and profile differences, see [runtime compatibility](../runtime-compatibility.md).
