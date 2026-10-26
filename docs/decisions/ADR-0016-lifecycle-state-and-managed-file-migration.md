# ADR-0016: Lifecycle state and managed-file migration

**Status:** Accepted

**Date:** 2026-10-25

## Context

Anvil 2.7.0 added a skill and command. Its target-release audit was also used to judge 2.6.x installations before upgrade, so an expected target delta could be mislabeled as corruption and block the command that would apply the delta. The same lifecycle code did not order releases semantically, distinguish downgrade from migration, identify Anvil-owned files, or recover after process death between config replacement and metadata write.

## Decision

Model installed source, repository target, and transition independently. Numeric semantic release comparison determines whether the source is current, stale at an earlier patch, migratable, unsupported, or newer than the checkout. Automatic migration supports the same Anvil major and a two-minor source window. Downgrades are blocked.

New installations receive `.anvil-managed.json`, which lists Anvil-owned relative file paths and SHA-256 digests. `opencode.jsonc` is listed with a null digest because user provider/model settings are user-editable and separately audited. Installation metadata stores the SHA-256 of the manifest. Unknown extra files are user-owned and preserved; a collision with a target-owned path blocks the transition. The target staging tree is validated before the real operation.

After a verified snapshot, mutating lifecycle commands create a durable transaction journal before the first live rename. Config is copied to a sibling staging directory and activated by rename. A later invocation validates and restores the snapshot before retrying an interrupted transaction. The journal is removed only after successful postflight or successful automatic rollback. `inspect` and dry run remain read-only.

Anvil product updates and OpenCode runtime changes remain separate. Anvil upgrade keeps the exact supported runtime. Same-major runtime updates preserve installed Anvil metadata and config. Runtime-major migration requires current Anvil so its config manifest and installed-release metadata cannot diverge.

## Consequences

- `inspect` and doctor can distinguish `MIGRATION_REQUIRED`, `UNSUPPORTED`, `CORRUPTED`, and `RECOVERY_REQUIRED`.
- Legacy 2.6.x/2.7.x profiles are inferred from their recorded source release until their first manifest-backed upgrade.
- Reforge can rebuild missing or modified managed files when the manifest itself is intact; an unreadable or mismatched manifest still blocks automatic ownership decisions.
- Rollback to a supported earlier release is a migration state, not corruption.
- `upgrade` and `reforge` both reject a checkout older than the installed Anvil release; rebuilding files cannot be used to bypass downgrade protection.
- A hard interruption leaves a verified snapshot and journal for deterministic recovery. Recovery requires the same HOME/XDG roots and a stopped OpenCode process.

## Alternatives rejected

- Requiring `make reforge` for every ordinary update would reconstruct valid profiles and could lose user-owned files.
- Comparing directory contents to the target release cannot distinguish an expected upgrade delta from corruption or a user addition.
- Automatically downgrading installed Anvil when the checkout is older risks replacing newer managed behavior and metadata.
- Keeping no durable journal leaves a process-kill window where config and installation metadata describe different releases.
