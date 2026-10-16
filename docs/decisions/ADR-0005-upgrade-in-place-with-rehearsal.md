# ADR 0005: Upgrade in place with an isolated rehearsal

- **Status:** Superseded by [ADR 0008](ADR-0008-runtime-independence.md) for Anvil 2.1 lifecycle semantics
- **Date:** 2026-10-13

## Context

OpenCode 2 changes its config and runtime generation. Reusing V1's destructive clean-rebuild flow for an ordinary upgrade would risk losing provider preferences and leave database migration untested.

## Decision

For Anvil 2.0, `make upgrade` was the forward V1-to-V2 migration path. It resolved one exact official stable candidate, rehearsed it against copies of config/data/state/memory under temporary HOME/XDG roots, backed up the full live snapshot, and installed the same candidate. Rollback restored the previous binary/config/data/state snapshot as opaque files. Anvil 2.1 retains this rehearsal and rollback safety but moves major migration to the explicit `make migrate-runtime` operation.

## Consequences

The rehearsal needs temporary disk space and requires OpenCode to be closed for a consistent state copy. It does not make or authenticate a model request. Verified backups are larger because they contain OpenCode data/state and the prior executable.
