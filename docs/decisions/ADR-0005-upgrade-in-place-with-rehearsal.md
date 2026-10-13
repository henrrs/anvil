# ADR 0005: Upgrade in place with an isolated rehearsal

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

OpenCode 2 changes its config and runtime generation. Reusing V1's destructive clean-rebuild flow for an ordinary upgrade would risk losing provider preferences and leave database migration untested.

## Decision

Add `make upgrade` as the forward migration path. Resolve one exact official stable candidate, rehearse it against copies of config/data/state/memory under temporary HOME/XDG roots, back up the full live snapshot, and install the same candidate. Rollback restores the previous binary/config/data/state snapshot as opaque files. Keep `make reforge` as the explicit clean rebuild path.

## Consequences

The rehearsal needs temporary disk space and requires OpenCode to be closed for a consistent state copy. It does not make or authenticate a model request. Verified backups are larger because they contain OpenCode data/state and the prior executable.
