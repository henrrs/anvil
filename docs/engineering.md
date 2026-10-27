# Long engineering tasks

Anvil 2.9.0 adds optional local engineering continuity on both OpenCode generations. Ask the Anvil agent naturally to implement a named specification, preserve architectural boundaries, work through milestones, and resume after interruption. Small fixes retain the direct workflow and create no task store. Complexity can emerge later; escalation preserves evidence already gathered.

For example: “Implement specification.md using the existing architecture. Track requirements, architecture invariants and coherent milestones. Verify each unit and report unverified scope.” The `anvil-engineering` skill guides that workflow. `anvil-system-design` handles responsibility, dependency, state/retry ownership and design pressure when needed. The existing Spark skill routes to focused execution/Arrow/JDBC/shuffle/memory/Delta references; it does not load them all or assign architectural ownership to Spark.

Requirements answer what must exist and how it is verified. Architecture records what must remain true. Work records what is pending, active, implemented, verified or blocked. An IMPLEMENTED task has not necessarily passed its checks. Completion requires required coverage, task/milestone/project definitions of done, architecture conformance and resolved blocking unknowns. Required deferred work still blocks completion; scope reduction requires actual user authorization.

Task state is private JSON under `${XDG_STATE_HOME:-$HOME/.local/state}/anvil/engineering/<repository-id>/<task-id>/`. It is separate from durable memory, knowledge, source registry and OpenCode sessions. Nothing is written merely by startup, capabilities, complexity assessment, or a small request. Reforge, Anvil upgrade, runtime migration and rollback leave this task store outside their config/runtime snapshots.

To resume, tell Anvil the task ID and repository. It uses a bounded recovery packet rather than rereading every source. The packet includes objective, relevant requirements/decisions, architecture, current unit, verified work, blockers and next action. Resume does not execute commands. An active unit may have partial effects; Anvil must inspect those before reconciliation. A changed branch/HEAD, named source, or specification triggers stale-evidence review rather than automatic replay.

The helper is available after `make upgrade` at:

```bash
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py" --help
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py" list --repository /path/to/project
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/engineering.py" resume \
  --repository /path/to/project --id TASK --format json
```

For a disposable CLI demonstration, copy `evals/engineering/ingestion/fixture/` and `specification.md` into a temporary Git repository, then initialize with the corresponding `models.json`. That JSON is a benchmark's explicit normalization, not an automatic spec parser. `python3 evals/engineering/run.py --mode replay --repeats 3 --output /tmp/anvil-eval.json` exercises both offline fixtures without using a model or changing a real project.

Use `make capabilities` for supported capabilities. There is no required OpenCode upgrade, new MCP, extra agent, model routing or Python package. Use `make upgrade DRY_RUN=1`, then `make upgrade` to install Anvil 2.9.0 while preserving the exact validated OpenCode runtime. Read [the migration guide](migrations/v2.8.0-to-v2.9.0.md) and [testing methodology](engineering-evaluation.md) for validation scope.

If `WORK_STATE_STALE` appears, inspect affected files and use revalidation/replanning. If the specification changed, normalize its affected requirements first. If `WORK_STATE_CORRUPTED` appears, Anvil leaves it unchanged; inspect the previous generation and use explicit recovery only after reviewing it. Recovery invalidates completion evidence. A bad task file does not mean the installed Anvil runtime is corrupted. Archive finished tasks explicitly; deletion/retention and promotion to durable memory remain user choices.
