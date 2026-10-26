# Lifecycle hardening assessment

## Current lifecycle

`VERSION` is the target release. `installation.json` records the installed Anvil/OpenCode release and runtime path. `runtime_state.py` discovers the executable independently. `configure.py` audits global OpenCode profile shape. `lifecycle_state.py` combines those inputs for `inspect`, `doctor`, upgrade preconditions, and rollback lookup.

`make upgrade` validates the source profile, builds and audits a target profile, rehearses that target against copied runtime data, verifies backup capacity, quiesces the active runtime, snapshots the source, replaces global config, writes installation metadata, then runs local doctor. Detected post-mutation failures restore the snapshot. Runtime update/migration and reforge have parallel staging/snapshot/apply flows. `make rollback` verifies and restores the archive and prior installation record.

## Root cause

- **Symptom:** An Anvil 2.6.1 installation with supported OpenCode 1.19.3 was reported as corrupted by the 2.7.0 checkout, so `make upgrade` and its dry run stopped before applying the new profile.
- **Proximate cause:** the source profile audit compared its skill allowlist to the target checkout's complete skill set. The 2.7.0 target added `anvil-communication`; the valid 2.6.1 source did not yet grant it.
- **Architectural cause:** source validity, target validity, and migration compatibility shared one audit path. A target-only capability delta was interpreted as source corruption. Lifecycle labels also used exact installed/checkout version equality instead of semantic version ordering.
- **Why tests missed it:** lifecycle fixtures were generated from the current checkout. They therefore had the target skill already present and did not reproduce an installation created by the previous release.

## Other lifecycle risks found

- `doctor_data.py` compared complete command/skill directory sets and treated unrecognized files as errors, so user-owned additions were not represented separately.
- Managed config replacement removed the entire global config tree. Provider and CLI/TUI settings had specific preservation logic, but arbitrary user-owned files and command/skill additions had no ownership manifest.
- Installation metadata was committed last and atomic, and caught failures used verified snapshots. A hard process interruption between file replacement and metadata commit had no durable transaction marker to guide retry or recovery.
- Runtime-only update rebuilt config from the checkout while retaining the installed Anvil version in metadata, which could commit target Anvil config under source-release metadata.
- Rollback restored prior config and metadata coherently, but the checkout may be newer; that result should be reported as migration-required rather than corrupted.

## Target/source/transition model

- Source validation uses the source installation manifest when present, otherwise a constrained legacy-profile adapter. It checks source-owned files and runtime/config coherence without requiring target-only capabilities.
- Target validation remains strict and runs after a staged target is built.
- A migration plan compares managed source/target file inventories and reports additions, updates, removals, conflicts, and preserved user-owned files.
- Managed files carry a release manifest and digests. Mutable `opencode.jsonc` is validated structurally and merged; user-owned provider settings, CLI/TUI preferences, and unrecognized non-conflicting files are preserved.
- Semantic version comparison distinguishes current, older supported, newer checkout, and unknown source versions. A valid older installation is `MIGRATION_REQUIRED`; a newer installed release with an older checkout is `UNSUPPORTED`.
- Both upgrade and reforge reject a checkout older than the installed Anvil release before creating a snapshot or replacing managed files; reforge cannot be used to bypass the downgrade check.
- A durable transaction journal references the verified pre-mutation snapshot. A detected interrupted transaction is recoverable and never described as ordinary corruption.

## Compatibility and safety boundaries

Anvil upgrades preserve a compatible OpenCode executable and opaque OpenCode data/state. Runtime changes remain explicit. Databricks health remains an independent capability state and does not determine core Anvil installation integrity. `inspect`, `doctor`, and dry runs remain read-only. User-owned files that collide with new Anvil-owned paths block migration with a precise conflict instead of being overwritten.
