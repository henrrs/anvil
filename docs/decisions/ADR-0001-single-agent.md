# ADR-0001: One visible primary agent

**Status:** Accepted

## Decision

Anvil V1 defines one visible primary agent, `anvil`, disables the built-in user-facing agent IDs where supported, and denies subagent calls from Anvil.

## Context

Multiple planner, reviewer, explorer, or model-router agents add prompt, selection, and coordination overhead. The product goal is reliable task completion with minimum unnecessary context. OpenCode already supplies the native tools and hidden maintenance agents needed for runtime behavior.

## Consequences

The primary agent follows one compact global harness and chooses tools directly. Domain guidance loads lazily as skills. OpenCode's compaction/title/summary agents remain available internally. This baseline does not claim multi-agent coordination improvements.
