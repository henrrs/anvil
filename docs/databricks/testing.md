# Offline Databricks tests

The mandatory suite uses `tests/fixtures/bin/databricks`, placed first on `PATH` and selected through `ANVIL_DATABRICKS_CLI`. It supplies realistic CLI profile, cluster, warehouse, API status, permission, and system-table fixtures. The fake records only endpoint names and bounded request metadata; it never logs Python source, SQL text, credentials, or result payloads.

Tests cover profile validation and persistence, single/multiple/stopped compute and warehouse discovery, explicit selection, Python context/command polling and cleanup, SQL status polling and result bounds, failure and permission paths, safe handling of stopped compute, mutation guards, system-schema discovery, all required FinOps evidence scenarios, and SQL recipe contracts. Existing lifecycle tests run both OpenCode profile shapes with local CLI fixtures.

`make test` requires only local Python 3.11+, Bash, and system utilities already used by Anvil. It does not resolve or download OpenCode, contact Databricks, or call an LLM. Real-service smoke tests are optional and are not part of mandatory validation. A green offline suite validates adapters and contracts; it does not claim a live workspace connection succeeded.
