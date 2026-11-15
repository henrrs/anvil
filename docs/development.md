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
- `make eval-analytical` runs deterministic analytical fixtures.
- `make eval-analytical-semantic` runs semantic fixture evaluation.
- Model evaluation can contact the configured provider and consumes its normal token budget. It is opt-in and is not part of `make test`.

## Release artifacts

Update `config/managed-inventory.json` from the shipped OpenCode 1 profile and verify it with:

```bash
python3 scripts/version_docs.py
python3 scripts/configure.py audit config/runtimes/opencode-v1.jsonc
```

The inventory is the checksum authority for managed runtime files. Do not edit generated installed files directly when preparing a release.
