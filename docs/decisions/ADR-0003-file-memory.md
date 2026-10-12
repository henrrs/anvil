# ADR-0003: Human-readable file memory

**Status:** Accepted

## Decision

Persistent memory is Markdown with YAML frontmatter under the Anvil XDG data directory. It uses local text search, duplicate-aware explicit updates, and atomic file replacement.

## Context

V1 needs durable, inspectable cross-session context but does not need a service, database, embedding model, or vector retrieval. Automatic extraction can preserve stale or inferred facts without user intent.

## Consequences

Users can review and edit entries with ordinary tools. Retrieval is lexical and may miss semantic matches. Reads are on demand; writes happen only after `/remember` or a direct explicit request. Automatic memory writes are deferred until they can be evaluated for correctness and consent.
