# Offline Databricks tests

The mandatory suite uses local fakes for `tests/fixtures/bin/databricks`, Azure CLI, SDK, installer archive, and VS Code CLI. It does not open a browser, perform real OAuth, access a Databricks workspace, or require network access. The tests do not resolve/download OpenCode.

Coverage includes clean `anvil-dev` creation, legacy external-profile migration, multiple external profiles, no external-profile adoption or modification, Anvil config ownership/collision/corruption handling, atomic reset backups, `0600` config/state files and `0700` directories, environment override isolation, secret-free diagnostics, Azure CLI session reuse/device-code orchestration, topology-aware auth selection, CLI OAuth U2M fallback, idempotency, SDK use of the Anvil profile, CLI/SDK provider routing, timeout/cancellation, human/JSON presentation, and dry-run no-write behavior.

The full `make test` suite exercises both supported OpenCode runtime profiles and existing lifecycle, upgrade, rollback, network-denial, runtime-independence, and organization-hygiene regressions. It requires local Python 3.11+, Bash, and the utilities already used by Anvil. No live workspace validation is claimed.
