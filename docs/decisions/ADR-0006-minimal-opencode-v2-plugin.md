# ADR 0006: Keep the OpenCode 2 plugin limited to memory search

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

V2 needs a native read-only memory-search tool. Recreating the V1 memory flow through hooks or prompt rewriting would add hidden behavior and couple Anvil to more OpenCode internals.

## Decision

Ship one local `anvil-core` plugin that registers bounded `anvil_memory_search` through the OpenCode 2 plugin API. It calls the existing Markdown helper. Keep persistent writes in explicit `/remember` and `/distill` workflows.

## Consequences

Memory remains portable Markdown and searchable without an index service. The plugin must remain server-side, read-only, bounded, and free of hooks, routing, and automatic writes.
