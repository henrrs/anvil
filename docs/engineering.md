# Adaptive engineering and long-horizon work

Anvil 2.10.0 judges the requested change, not the repository's overall size or complexity. Local, reversible work stays on the direct path even when a large project or active Work Model exists: locate the relevant code and focused test, make the smallest coherent change, verify proportionally, and stop. There is no required `/fast`, `/deep`, or other user mode.

Anvil expands reasoning only when evidence changes the next safe action: dependent work needs coordination, a public contract or component boundary changes, persistent state/migration/retry semantics are involved, significant uncertainty remains, interruption recovery matters, or the user explicitly asks for a deep review. Expansion is selective and can collapse again after a decision. See [adaptive execution policy](adaptive-engineering.md).

## Long-horizon engineering

For a genuine multi-milestone task, ask Anvil naturally to preserve named requirements, architectural boundaries and progress across interruptions. Example: “Implement specification.md using the existing boundaries; track required acceptance, architecture invariants and dependent milestones; verify each milestone and report unfinished scope.” The `anvil-engineering` skill retains the separate Requirements, Architecture and Work models. The `anvil-system-design` skill is used only when responsibility, dependency, contract, state, or failure ownership needs a decision. Spark and Databricks references remain evidence-selected.

Requirements answer what must be delivered and verified. Architecture records what must remain true. Work records meaningful units and progress. Completion still requires required coverage, task/milestone/project definitions of done, successful architecture checks and resolved blocking unknowns. Implemented work is not automatically verified. Scope reduction requires actual user authorization.

Task state is private JSON under `${XDG_STATE_HOME:-$HOME/.local/state}/anvil/engineering/<repository-id>/<task-id>/`. It is separate from durable memory, knowledge, source registry and OpenCode sessions. Startup, direct/local work, capability reporting, assessment, and a small request create no state. Reforge, Anvil upgrade, runtime migration and rollback leave this task store outside their config/runtime snapshots.

To continue work after interruption, tell Anvil which task/repository to resume or run the helper:

```bash
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py" --help
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py" list --repository /path/to/project
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py" resume \
  --repository /path/to/project --id TASK --format json
```

Resume reconstructs a bounded packet and executes no work. An active unit may have partial effects; inspect them before reconciliation. A changed branch/HEAD, named source, or specification triggers stale-evidence review rather than automatic replay. Recovery from corruption is explicit and invalidates previous verification.

## Scoped verification and architecture

Prefer the smallest check that can falsify the implementation. Use focused tests for local behavior; broaden checks for shared contracts, material blast radius, unexpected failures, state/migration semantics, milestone gates or a release requirement. Never claim a check that did not run. A cheap failing test is evidence to inspect, not an automatic reason to run the full suite.

`checkpoint --milestone M3 --revision N` checks only missing or invalid invariants declared for the completed milestone, preserving valid evidence for untouched boundaries. `checkpoint --revision N` with no milestone runs an explicit full architecture audit. A changed file invalidates invariant evidence only if it belongs to that invariant's named scope or changes a declared glob's matched files. Semantic architecture judgments still need an attributed review.

For a disposable helper demonstration, copy `evals/engineering/ingestion/fixture/` and its `specification.md` into a temporary Git repository, then initialize with the corresponding `models.json`. That JSON is explicit benchmark normalization, not automatic requirement extraction. Run deterministic fixtures with:

```bash
python3 evals/engineering/run.py --mode replay --repeats 3 --output /tmp/anvil-eval.json
python3 evals/engineering/adaptive.py --output /tmp/anvil-adaptive-eval.json
```

The first command exercises ingestion and unrelated scheduler continuity without a model or real project. The second checks 18 paired activation cases and compares archived structured/adaptive protocol-replay evidence. It does not measure model behavior or actual source files read.

## Upgrade and runtime

Use `make capabilities` for supported features. No runtime upgrade, new MCP, extra agent, model routing, or Python package is required. `make upgrade DRY_RUN=1`, then `make upgrade` installs Anvil 2.10.0 while preserving the exact validated OpenCode runtime. Read [the 2.9-to-2.10 migration guide](migrations/v2.9.0-to-v2.10.0.md). The supported migration window retains the Anvil 2.6 source line.
