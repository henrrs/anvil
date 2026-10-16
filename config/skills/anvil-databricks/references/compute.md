# Classic compute discovery and Python execution

The provider adapter lists classic all-purpose clusters through the CLI when healthy or the official SDK fallback. It includes user/API-created classic clusters, excludes job, pipeline, and other compute sources, and reports ID, name, state, source, Databricks Runtime, worker/driver node type, fixed worker count, and autoscale bounds.

Use a running cluster for Command Execution. If more than one suitable cluster is running, ask the user to choose. If none runs, present stopped cluster choices and wait for approval before starting one. Anvil does not expose a cluster-start operation in its adapter.

Python execution uses the documented Command Execution API lifecycle:

```text
validate the selected workspace and cluster
→ POST /api/1.2/contexts/create
→ poll /api/1.2/contexts/status
→ POST /api/1.2/commands/execute
→ poll /api/1.2/commands/status
→ return bounded output
→ POST /api/1.2/contexts/destroy
```

Timeout requests cancellation before context cleanup. Only `Finished` is success; `Error`, cancellation, unknown states, and timeouts are reported. A user's explicit request must call for remote execution. Review code for destructive or externally visible effects and ask before running those effects.

The [Command Execution API](https://docs.databricks.com/api/command-execution/v2/command-execution) documents the `python` language, running cluster requirement, command status, cancellation, and context cleanup endpoints. The API is GA as checked on 2026-10-16. Runtime/platform restrictions can still make an otherwise running cluster unusable; report permission or API errors rather than switching or starting resources.
