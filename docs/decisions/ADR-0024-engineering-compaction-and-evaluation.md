# ADR-0024: Engineering continuity at native compaction and deterministic evaluation

**Status:** Accepted<br>
**Date:** 2026-11-13

## Context

Anvil 2.9+ already stores optional long-running task state in separate Requirements, Architecture, and Work models. Explicit resume reconstructs state and invalidates evidence affected by repository drift. Session compaction, however, could summarize away task identifiers or the next action unless the agent explicitly resumed. The task state is the correct source of truth; conversational transcripts are neither needed nor appropriate as a durable recovery store.

Engineering guidance also existed across agent instructions and skills, but did not provide a focused, discoverable reference for general code-quality work. Existing deterministic replays cover engineering continuity but do not exercise an independent software behavior acceptance test.

## Decision

- Use the documented OpenCode 2 `compaction` session hook as an optional adapter. At hook time, resolve the session repository, ask the existing engineering CLI for one bounded packet, and append it to the native compaction system context. Do not intercept prompts, route models, change tools, or replace native summarization.
- Keep packet generation read-only, transcript-free, bounded to 8 KiB at the data layer, and fail-soft at the plugin boundary. Do not create state during compaction. Skip when no active task exists or multiple active tasks make selection ambiguous.
- Keep V1 behavior unchanged and rely on existing explicit resume because V1 does not expose this V2 API.
- Add quality guidance as a lazy reference in the existing engineering skill; do not clone full process frameworks or add mandatory language toolchains.
- Add deterministic acceptance fixtures to the existing evaluation runner. Keep live model evaluation explicit, isolated, and opt-in; do not infer a model-quality or efficiency improvement from deterministic replays.
- Keep the existing Databricks runtime discovery logic; isolate its minimum-version unit fixture from host-installed executables.

## Consequences

An interrupted V2 task has a better chance of retaining its task-local objective, active unit, criteria, decisions, evidence status, blockers, and next action in OpenCode's native summary. This is a capability hypothesis backed by packet and source tests, not yet by live compaction observations. No task store migration or new dependency is required. V1 and unsupported V2 builds remain usable without the optional integration.
