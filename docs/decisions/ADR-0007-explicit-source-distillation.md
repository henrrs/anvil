# ADR 0007: Distill only named sources and preserve evidence conflicts

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Persistent memory is useful only when claims can be traced, refreshed, and distinguished from policy or historical descriptions. Automatic transcript harvesting and recursive crawling would blur provenance and create noise.

## Decision

Add `/distill` as an explicit source-driven command. Record local source identity and content hashes in a private file registry. Keep concise Markdown claims with source/evidence metadata, label historical material, distinguish normative policy from current implementation, and surface disagreement. Skip unchanged registered sources.

## Consequences

The agent performs semantic synthesis, so tests can verify evidence fixtures, registry behavior, provenance, and idempotent skip decisions but cannot guarantee the quality of every model-generated summary. No vector database or background crawler is added.
