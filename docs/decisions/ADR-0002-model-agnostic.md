# ADR-0002: Do not pin or route models in V1

**Status:** Accepted

## Decision

Anvil has no model-specific prompt, agent model, variant, router, or automatic escalation. OpenCode/session model selection remains the user's choice.

## Context

V1 has no controlled benchmark evidence that model-specific harnesses improve results enough to justify added context and maintenance. Pinning a model would interfere with normal model switching and undermine the same-harness requirement.

## Consequences

The agent adds no `prompt` field, preserving the provider/model-native base prompt where OpenCode permits it. Future model profiles require empirical evidence and a separate decision.
