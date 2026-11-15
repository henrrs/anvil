# Installation and lifecycle

Anvil manages its OpenCode 1 profile and helper files while preserving the user's runtime and data.

## Commands

- `make reforge` builds Anvil's managed profile. On first use it installs the policy-selected OpenCode 1 runtime if no usable supported runtime exists. With an existing supported runtime, it preserves that executable.
- `make upgrade` updates Anvil-managed files and metadata while preserving the exact OpenCode executable, data, and state.
- `make update-runtime` performs an explicit OpenCode update within the supported 1.x line.
- `make rollback` restores the latest verified snapshot.
- `make inspect` reports local state without changing it.
- `make doctor` checks the installed profile and local capabilities.

Use `make upgrade DRY_RUN=1` to review an Anvil upgrade plan. Dry run does not create a snapshot or signal OpenCode processes.

## Ownership

Anvil-owned profile files are listed by the installed `.anvil-managed.json` and validated against the repository's release inventory. Shared OpenCode settings are merged. User-owned files and settings are retained. A conflict that cannot be classified safely blocks an operation for manual review.

Anvil stores lifecycle metadata and backups under the configured XDG data directory. OpenCode authentication and session data remain in OpenCode's configured directories. Anvil does not read, copy, or modify credential contents during upgrade or reforge.

## Snapshots and recovery

A lifecycle snapshot records its scope, prior paths, and SHA-256 checksums. An Anvil-only upgrade snapshot covers the managed profile and Anvil metadata while preserving the OpenCode executable and OpenCode data/state. A verified rollback checks snapshot ownership and checksums before restoring it.

Lifecycle operations validate the prepared profile before activation, update installation metadata only after postflight verification, and attempt rollback if a post-activation step fails. If recovery cannot be verified, the snapshot and transaction journal remain available for diagnosis.
