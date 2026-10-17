# Databricks security boundaries

- The CLI, SDK and supported Unified Authentication own credentials and OAuth refresh. Anvil owns a separate profile file under its config directory, writes it atomically with `0600` permissions in a `0700` directory, and stores only non-secret provider metadata in state. Provider state rejects token, password, secret, credential and authorization fields.
- No privilege elevation is used. Anvil installs the CLI only to its own user-local data directory and installs the SDK only into its isolated virtual environment.
- Anvil never prints token output or requests sensitive auth modes. Provider errors are normalized and raw CLI stderr is not forwarded because it may include user data.
- CLI/SDK child output is drained with a 4 MB aggregate capture limit. Provider processes use bounded operation timeouts and are terminated as a process group on timeout or oversized output. Failure diagnostics include normalized provider, operation, timeout, profile, executable, and scope metadata without copying raw stderr.
- Anvil does not create PATs, log out of Databricks, or modify existing external auth profiles. It only creates and updates profiles in its own managed config. It does not inspect VS Code private files, copy IDE binaries, or modify shell startup files.
- Databricks and cloud CLI child processes receive an isolated environment. Inherited `DATABRICKS_*` values are removed; conflict output includes names only, never values. Anvil does not change the parent shell environment.
- SQL and Python results are bounded; SQL uses inline results when using Statement Execution rather than signed external result URLs. Results are not persisted.
- System-table queries filter and aggregate before data reaches the model. Raw table dumps do not go to durable Anvil memory.
- Read-only discovery is the default. The adapter offers no cluster, warehouse, job, pipeline, permission, or system-schema mutation endpoints. DDL/DML SQL requires explicit user approval and an explicit flag; potentially destructive Python code must be reviewed and approved before execution.
- Stopped compute is never started silently. Doctor performs only read-only identity and metadata list calls. Capability checks and dry-run do not contact the workspace; normal setup performs only read-only readiness probes apart from the explicitly selected authentication flow. None of these checks starts compute or changes workspace resources. `make databricks-setup RESET=1` replaces only Anvil-owned configuration after validating the candidate and retaining a private backup.

These are agent and adapter guardrails, not a substitute for Databricks grants, compute policies, SQL permissions, workspace controls, corporate policy, or the user's review of code and queries.
