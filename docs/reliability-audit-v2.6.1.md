# Fresh-install reliability audit

Audit performed against Anvil 2.6.1 before implementation of the fresh-install and Databricks bootstrap hardening work.

## Existing architecture

- GNU Make is a thin dispatcher to public Bash and Python entrypoints. Bash lifecycle scripts use `set -Eeuo pipefail`; GNU Make prints its normal target failure line when those scripts return non-zero.
- Runtime discovery is centralized in `runtime_state.py`, while Anvil installation state is inferred independently from config files, installation metadata, runtime paths, and backup paths by each command.
- Databricks provider readiness is centralized in `databricks.py` and persisted provider state. SDK calls cross a subprocess boundary through `sdk.py` and `sdk_worker.py`.
- `make test` builds a temporary directory and constrains `PATH`, but the top-level test invocation does not isolate all HOME/XDG roots. `tests/databricks.py` also starts with the caller's HOME and XDG environment, then patches only selected paths per test.

## Root causes confirmed

1. **Lifecycle state is inferred piecemeal.** `inspect` and `doctor` treat a missing OpenCode executable as “not installed” even if managed config files exist. Partial and corrupted managed states are not represented consistently. Upgrade scripts separately check config, runtime, and installation records.
2. **Missing rollback state is reported as an implementation detail.** In a clean HOME, `make rollback` prints `backup directory does not exist` from `state.py` instead of explaining that no snapshot exists or how to create one.
3. **Test isolation is incomplete.** The Databricks test runner sanitizes `PATH` but leaves process-wide HOME/XDG values intact. That makes tests depend on the host account despite their per-test temporary directories.
4. **Doctor can discard Databricks failures.** It redirects all status stderr and ignores every non-zero status. The status presenter also labels an absent readiness record stale even when the integration is `NOT_CONFIGURED`.
5. **SDK bootstrap conflates distinct blockers.** `install_sdk()` invokes `python -m venv` and then `python -m pip` without checking executable, venv, or pip separately. A missing pip is therefore reduced to a generic installation failure.
6. **SDK environment identity is lost.** SDK installation and discovery call `Path.resolve()` on `<Anvil data>/venv/bin/python`; a venv symlink can be persisted and executed as the underlying system interpreter.
7. **SDK failure context is dropped.** The worker reports a normalized category but no phase. The adapter reads only that category and creates a generic domain error, so the presenter cannot distinguish initialization, authentication/configuration, request, or response failure.
8. **Unexpected Python failures can escape command boundaries.** `capabilities.py` has no top-level exception presenter. `databricks.py` handles expected domain errors but does not provide a general sanitized boundary for unforeseen exceptions.

## Isolated pre-install command reproduction

An empty HOME with isolated XDG directories was used for public Make commands. `help`, `inspect`, `doctor`, `capabilities`, and `stats` completed. `upgrade`, runtime update/migration, and rollback returned non-zero without tracebacks, but rollback's message was not actionable. Databricks setup dry-run completed; real setup stopped safely in the headless/no-profile case. `make` appended its standard failure line for blocked operations.

## Lifecycle definitions for this release

- `REPOSITORY_ONLY`: no Anvil-managed config, install record, runtime state, or managed OpenCode executable exists in the selected HOME/XDG roots. A system OpenCode runtime by itself does not make Anvil installed.
- `NOT_INSTALLED`: retained as a human label for `REPOSITORY_ONLY` in commands whose purpose is installation status.
- `PARTIALLY_INSTALLED`: one or more Anvil-managed artifacts exist, but the managed config and a supported usable runtime are not both present.
- `INSTALLED`: Anvil config and a supported usable OpenCode runtime are present; release metadata may be from an earlier Anvil version.
- `READY`: the installation record matches this repository release and required config/runtime checks pass.
- `DEGRADED`: core installation is usable, but a non-core local artifact such as the memory directory is absent. This does not imply Databricks readiness.
- `BLOCKED`: an operation cannot proceed because its explicit lifecycle precondition is unmet; this is an operation result, not a persisted installation state.
- `CORRUPTED`: a managed artifact expected to be valid is malformed, unsafe, non-executable, or fails the relevant integrity/configuration audit.

## Intended public behavior

`make inspect` and `make doctor` report the shared lifecycle state. Upgrade, runtime update/migration, and rollback use that same evaluator for their installation/backup preconditions. `make reforge` remains the bootstrap command and accepts repository-only and recoverable partial states subject to its existing path-safety and runtime checks. Capabilities and stats remain useful before installation. Databricks readiness remains independent of OpenCode lifecycle state.

This audit is recorded before source changes, as required by the implementation specification. The release report will append the final test evidence and any remaining limitations.

## Implementation and verification report for Anvil 2.6.2

- Added `lifecycle_state.py` as the shared evaluator used by inspect, doctor, upgrade, runtime update/migration, and rollback preconditions. It distinguishes repository-only, partial, installed, ready, degraded, and corrupted states, and gives first-use and recovery guidance.
- Doctor now reports lifecycle integrity and preserves Databricks status diagnostics. Commands that need an installation or rollback snapshot fail with an actionable prerequisite instead of exposing internal state errors.
- The public Python entrypoints use a safe exception boundary. `DEBUG=1` enables diagnostic frames with sensitive values redacted.
- Databricks SDK bootstrap checks Python, virtual environment and pip availability independently, preserves the selected interpreter invocation path, constructs an explicit SDK `Config`, and transports normalized failure phase/status metadata without forwarding exception messages or response bodies.
- Test execution now uses isolated HOME/XDG roots, a restricted PATH and an external-network guard. Fresh-install and post-reforge public Make command matrices cover offline behavior, failed operations, rollback, and partial/corrupted states.
- Documentation now defines command contracts and lifecycle behavior; ADR-0014 records the shared lifecycle and safe-bootstrap decision. The supported release is 2.6.2, with OpenCode 1/2 support and Databricks readiness as independent contracts.

Verification completed:

- `make test` — passed the full offline suite, including Databricks provider contracts, OpenCode 1/2 profiles, fresh HOME/XDG matrices, reforge/upgrade/rollback journeys, injected failures, process shutdown, and HTTP 403 boundary checks.
- `python3 scripts/version_docs.py` — passed for Anvil 2.6.2.
- `git diff --check` — passed.

No release-network, external Databricks workspace, or model service was used by the suite. No unresolved implementation limitation was found in the covered contracts.
