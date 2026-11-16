---
name: anvil-engineering
description: Use when the requested work itself has dependent milestones, consequential boundaries/state changes, or needs durable interruption recovery. Do not use this skill just because the repository is large, complex, or already has an active Work Model; local tasks stay local unless new evidence requires escalation.
---

# Adaptive engineering

## Activate only for this task

Judge the requested change, not the project around it. For a clear, local and reversible change, inspect the relevant implementation, caller and test; make the change, run a focused check and stop. Existing project state alone does not require a plan or a state update.

When changing a public contract, persistence, filesystem behavior or an external effect, identify the accepted inputs, error behavior, authorized side effects and protected state before editing. For a refactor that moves responsibilities, identify each owner and the intended dependency direction. Check one relevant failure or boundary case that could disprove the implementation. If a focused check fails, inspect and fix the cause or report the blocker; do not treat the check as completed. These decisions do not require a document or checklist for a small task.

Expand only when dependent changes need coordination, a consequential contract or state transition changes the next safe action, the scope remains unclear, or interruption recovery matters. A long specification alone is not a trigger. Read only the evidence needed for the current decision, then return to the active change.

## When long-horizon structure is justified

For dependent milestones or durable recovery, inspect extension points and interpret the named specification before implementation. Preserve its constraints, acceptance criteria, risks and unknowns. Read [models.md](references/models.md) when creating or changing Requirements, Architecture and Work models; keep the active context limited to the current unit.

Use a short plan to coordinate dependencies or meaningful uncertainty. Persist models only when multiple milestones, compatibility/state transitions or interruption continuity justify them. Private helpers and reversible choices inside established boundaries need no architecture reconciliation.

Work on one coherent ready unit. Record meaningful implementation, verification and blockers. Checkpoint architecture for a changed boundary, contract, state or failure decision, a risky operation, or a milestone gate. Update persistent state only for a material transition needed for recovery.

Use the smallest checks that can falsify the implementation. Broaden them for shared interfaces, state/migration semantics, milestone gates or unexpected evidence. A passing test proves only its declared scope; never report a check that was not run.

Read [quality.md](references/quality.md) for detailed debugging, refactoring, test design, review, performance, security or dependency/API guidance. Read [execution.md](references/execution.md) for stateful transitions and completion gates. Use `anvil-system-design` only for a real responsibility, dependency, durable-state, contract or failure-ownership decision. Load domain references only when the task needs them.

## Interruption and completion

Read [resume.md](references/resume.md) only for interrupted structured work or stale evidence. Inspect partial external effects before reconciliation; never replay an uncertain external action. An IMPLEMENTED unit is not VERIFIED, and required gates and blocking unknowns still govern completion.

The helper is `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py`; use it only when structured state is justified. State belongs under `${XDG_STATE_HOME:-$HOME/.local/state}/anvil/engineering/`, never in durable memory or project sources.
