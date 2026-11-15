# Development and tests

Anvil's tests are offline by default and use temporary HOME/XDG directories, local runtime fixtures, and network-denied guards.

## Validation

```bash
make test-core
make test-lifecycle
make test
```

Use `make test-core` for skills, memory, Databricks, analysis, communication, engineering, and evaluation contracts. Use `make test-lifecycle` for state normalization, operation planning, and isolated installation, upgrade, rollback, and recovery paths. `make test` runs the full suite once.

Do not point lifecycle tests at a real user profile. The test runner creates and removes its own temporary HOME and XDG roots.

## Optional evaluation

- `make eval-engineering` replays deterministic engineering and recovery fixtures.
- `make eval-engineering-model MODE=smoke|challenge|suite` runs selected fixtures with the locally configured OpenCode CLI.
- Model evaluation uses the real OpenCode 1 executable, configuration, authentication, and provider; it is opt-in and is not part of `make test`.

Start a new live evaluation with a smoke. It generates and prints a unique evaluation ID:

```bash
make eval-engineering-model MODE=smoke
```

Replace `ID_FROM_SMOKE` below with the exact ID printed by the smoke. Reuse it for every command in that comparison. A later smoke creates a new ID and leaves the previous budget and results intact:

```bash
EVALUATION_ID=ID_FROM_SMOKE make eval-engineering-model MODE=challenge TREATMENT=native-opencode FIXTURE=fast-control
EVALUATION_ID=ID_FROM_SMOKE make eval-engineering-model MODE=challenge TREATMENT=anvil-active FIXTURE=fast-control
EVALUATION_ID=ID_FROM_SMOKE make eval-engineering-model MODE=suite TREATMENT=native-opencode
EVALUATION_ID=ID_FROM_SMOKE make eval-engineering-model MODE=suite TREATMENT=anvil-active
```

Budgets, budget state, and reports are written under `${XDG_STATE_HOME:-~/.local/state}/anvil/evaluations/engineering/<evaluation-id>/`, outside the checkout. Fixture workspaces and the compiled Landlock shell remain temporary. The grader stays outside the model workspace and runs after each challenge. Per-call time, step, context, output, invocation, and aggregate token limits are enforced by the generated budget; automatic retries are disabled. `fast-control` must pass for a treatment before its full suite runs.

The live runner does not read or copy credentials. Its OpenCode subprocess uses the configured profile and provider. The fixture shell can write only to the disposable fixture and evaluation state subtree, and network syscalls from that shell are denied; OpenCode itself retains provider network access.

## Release artifacts

Update `config/managed-inventory.json` from the shipped OpenCode 1 profile and verify it with:

```bash
python3 scripts/version_docs.py
python3 scripts/configure.py audit config/runtimes/opencode-v1.jsonc
```

The inventory is the checksum authority for managed runtime files. Do not edit generated installed files directly when preparing a release.
