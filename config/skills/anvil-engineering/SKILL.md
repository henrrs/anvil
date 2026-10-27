---
name: anvil-engineering
description: Use for large specifications, multiple milestones, cross-component implementations or interrupted engineering tasks that need requirements coverage, architecture constraints and resumable work state. Do not use for small isolated edits; escalate only when scope warrants it.
---

# Sustained engineering execution

Assess scope from the request and evidence already located. Multiple milestones, cross-component dependencies, durable schema/API changes, migrations, or a specification whose constraints cannot safely remain in context justify structured state. A rename, isolated validation, documentation edit or small bug fix normally does not. Do not scan a repository or create state merely to classify it. Escalate from direct work without restarting; de-escalate if the apparent scope disappears.

Before coding a long task, inspect existing architecture and extension points. Normalize the explicitly named specification into objective, requirements with source sections, constraints, acceptance criteria, boundaries/invariants, decisions, dependencies, risks, unknowns and deferred scope. This is semantic analysis: the helper inventories sources but cannot extract reliable requirements for you. Preserve constraints and distinguish required scope from optional ideas.

Maintain three separate models: requirements measure completeness; architecture constrains implementation; work records progress. Read [models.md](references/models.md) when creating or changing models. Use the local stdlib helper at `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py`; run `--help` for commands. State belongs under `${XDG_STATE_HOME:-$HOME/.local/state}/anvil/engineering/`, never in durable memory or arbitrary source directories. Persist concise decisions, evidence references and results, not hidden reasoning, secrets, raw logs or copied conversations.

Read [execution.md](references/execution.md) for the execution loop, completion gates and retry discipline. Select one coherent ready unit, inspect relevant source/requirements/decisions, validate assumptions, implement, verify, checkpoint architecture at meaningful boundaries, then update coverage and work state. Load only the current unit and relevant domain references. Use `anvil-system-design` when responsibility or dependency decisions matter; Spark/Databricks expertise does not assign architectural ownership.

Read [resume.md](references/resume.md) when interrupted, compacted or facing changed repository/specification evidence. `resume` reconstructs a bounded packet and executes no work. Inspect partial actions before reconciliation; do not replay a destructive action because its result is uncertain. An IMPLEMENTED unit is not VERIFIED. Never claim the task complete while required coverage, definitions of done, architecture checks or blocking unknowns remain unresolved.
