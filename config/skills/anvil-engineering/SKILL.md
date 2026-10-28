---
name: anvil-engineering
description: Use when the requested work itself has dependent milestones, consequential boundaries/state changes, or needs durable interruption recovery. Do not use this skill just because the repository is large, complex, or already has an active Work Model; local tasks stay local unless new evidence requires escalation.
---

# Adaptive sustained engineering

## Activate only for this task

Judge the requested change, not the project around it. If the next safe action is clear, local, reversible and bounded, locate the relevant implementation/caller/test, act, run a focused check, and stop. Do not read or resume long-horizon state, rebuild requirements, run architecture conformance, or create a plan for an unrelated local fix just because the repository has a complex system or active project state.

Expand when uncertainty or meaningful risk changes the next safe action: dependent changes need coordination; a public contract, responsibility/dependency boundary, persistent state, runtime/provider seam, migration, retry/failure ownership or compatibility guarantee changes; required scope is unclear; the user explicitly asks for deep review; or interruption recovery matters. A long request/spec is a prompt to inspect scope, not an activation rule by itself. Let semantic judgment choose whether to expand; do not use a score or repository-size threshold.

Depth is local and reversible. Preserve evidence when escalating, load only the requirements/architecture/work slice that affects the current decision, and narrow again after a design decision is settled. A local task inside a long project normally bypasses its Work Model. Explicitly continuing that project activates enough state to identify the current milestone, blockers and safe next step, then return to the active unit.

## When long-horizon structure is justified

Before implementation, inspect relevant extension points and semantically normalize the named specification. Preserve provenance, constraints, acceptance criteria, boundaries, risks, unknowns and deferred scope. Read [models.md](references/models.md) when creating/changing models. Keep Requirements, Architecture and Work separate; full explicit scope may remain in durable state, while active context should contain only the current unit and relevant slices. The helper inventories a source but does not extract its meaning.

Use a short plan only to coordinate dependent work or meaningful uncertainty. Use persistent models when multiple milestones, compatibility/state transitions or interruption continuity justify them. Keep implementation choices inside established boundaries free: private helpers, local decomposition and reversible details do not need architecture reconciliation.

During work, choose one coherent ready unit and inspect only its named evidence. Record meaningful implementation, verification and blockers. Checkpoint architecture when a boundary/contract/state/failure decision changes, a risky operation completes, or a milestone closes—not for each helper, local conditional, fixture or formatter. Update requirements/work state when the tracked scope or progress materially changes. Persist only transitions needed for safe recovery; the helper provides atomic generations, checksums, locks and revision checks.

Prefer the smallest checks that can falsify the implementation. Low-risk local changes use focused verification; broader integration, architecture and resume checks are for shared interfaces, material blast radius, state/migration semantics, milestone gates or unexpected evidence. A passing test proves only its declared scope. Never report a check that was not run.

Read [execution.md](references/execution.md) for stateful transitions and completion gates. Use `anvil-system-design` only when responsibility, dependency, durable-state, contract or failure ownership is at issue. Load only relevant Spark/Databricks references when the task needs their domain evidence. These skills add domain knowledge; they do not by themselves require long-horizon process.

## Interruption and completion

Read [resume.md](references/resume.md) only when continuing interrupted/compacted structured work or investigating stale evidence. Resume is read-only: inspect partial effects before reconciliation and never replay uncertain external actions. Revalidate affected evidence selectively; changed specifications require semantic re-normalization. An IMPLEMENTED unit is not VERIFIED. Completion still requires every required gate, architecture invariant and blocking unknown to be resolved.

The helper lives at `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py`; use `--help` only when structured state is justified. State belongs under `${XDG_STATE_HOME:-$HOME/.local/state}/anvil/engineering/`, never in durable memory or project sources. No state is created by direct work, assessment or capability inspection. Do not promote task state into memory.
