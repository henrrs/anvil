# Anvil 2.17.1 — Installed-State Convergence Engineering Report

## Scope and evidence

This patch addresses the gap between a clean repository fixture and an existing Anvil installation. It keeps the lifecycle Planner, ChangePlan, durable journal, snapshot, verify, commit and rollback boundaries already in the repository. No Analytics product capability or OpenCode runtime migration was added.

The reported machine findings came from the user's real-machine inspection. Repository causes below were independently confirmed against the `2.17.0` source baseline unless called out as pre-existing installed-state drift. All validation described here is offline and fixture-based; it does not claim a live corporate registry, systemd user manager, Databricks workspace, OpenCode model or Windows-to-WSL browser test.

## Root causes and fixes

| Finding | Classification | Change |
|---|---|---|
| Invalid Analytics `WorkingDirectory` in a previously generated unit | Installed-state drift plus a missing validation gate. The current source already used a distinct path serializer, but generated candidates were not passed through systemd verification before publication. | Validate absolute existing config paths and run `systemd-analyze --user verify` on the candidate when available, including a staged-interpreter substitution for syntax verification. The regression uses a path containing spaces and quotes. |
| Staged `venv/bin/python` rejected when it is a normal symlink | Repository bug. | Validate existence, executable permission, actual interpreter startup, expected `sys.prefix`, pinned versions and required imports. Broken/missing and wrong-prefix interpreters fail. |
| `abort`, `restore` and `finalize` could reach lock parsing | Repository bug. | Give each dependency-manager action its own argparse contract and return immediately after lifecycle actions. Restore/finalize do not need a requirements lock. |
| Rollback removed staged dependency state before restoring the old config pointer | Repository ordering bug. | Stop the service, restore managed config/runtime pointers, then restore or clean the staged dependency runtime; restore the captured database and service baseline afterward. |
| SQLite schema migration was outside rollback even though an older runtime could reject the new schema | Lifecycle design gap. | Declare rollback policy per schema transition. For `BACKUP_RESTORE_REQUIRED`, capture and verify a consistent SQLite backup before activation with SQLite's backup API, then restore it only when the recorded contract requires it. Datasets and Parquet snapshots remain outside rollback copies. |
| A dead URL remained attached to an OpenCode adapter | Repository bug. | Clear both the saved URL and adapter after failed health so startup cannot re-adopt a dead handle. Each probe is capped at 500 ms and retried within the existing bounded startup deadline. |
| A foreground Analytics server could mask an inactive managed service | Repository/service ownership gap. | `make analytics` continues to use the managed service path. During convergence Anvil stops only a same-user legacy Analytics process whose command, port and working directory all match; an unknown port owner is never signaled. |
| A 203/EXEC unit or invalid candidate could pass into activation | Missing pre-activation validation. | Verify generated unit syntax before publishing; validate staged interpreter semantics and ensure the final unit points at the content-addressed runtime target. |
| `runtime-policy.json` was absent from an older installed target | Installed-state drift: older releases did not ship the artifact. The current release inventory already declares it. | Fresh and upgrade packaging checks require the artifact and managed checksum; the 2.16 fixture verifies that upgrade supplies it without manual copying. |
| Dirty source could be mistaken for an authoritative release | Release-authority gap. | Before snapshot or dependency staging, compare release artifacts and lifecycle control files to `HEAD` and verify version/manifest agreement. Production upgrade blocks with changed paths; isolated tests have an explicit test-mode boundary. |
| Corporate registry failures could look like a missing package version | Repository diagnostic gap. | Prioritize observable connection/proxy/network signals over generic pip “no matching distribution” text. Reports expose a sanitized source label and fallback policy. Anvil reads existing pip config, does not rewrite it, and does not harvest credentials from unrelated tools. |
| Interrupted lifecycle journal could blindly repeat rollback or require manual clearing | Repository recovery gap. | Classify pre-activation abandonment, post-activation recovery, restore-in-progress, committed-but-unfinalized and unknown journals. Verify the captured baseline before repeating restore, including config-directory presence and the source profile hash when proving an interrupted recovery; normal rollback still permits supported shared-setting merges. Finalize only when installed version and managed manifest prove the target. Unknown/ambiguous state blocks with the snapshot intact. PID start-time identity avoids treating a reused PID as the live owner after reboot. |
| Analytics dependency actions could delete a runtime still referenced by active config | Repository ordering bug. | Restore the managed config/runtime pointer before cleaning the staged target. Journal recovery retries are durable and idempotent; restore progress is recorded before the restore attempt and verified before journal removal. |

The reported Databricks `403` was not changed in this patch. The previously run baseline `python3 tests/databricks.py` passed its four checks; the Databricks/provider behavior is outside this Analytics lifecycle correction.

## Installed artifact and package-source contracts

The managed manifest covers deployed Anvil-owned artifacts such as `config/runtime-policy.json`, `scripts/analytics/runtime.py`, the SQLite store and Analytics runtime adapter. Host-side lifecycle tools such as `analytics_service.py`, `analytics_dependencies.py` and `lifecycle_recovery.py` are release-authority inputs but are not installed managed-config artifacts. Packaging tests compare the shipped generated set to the declared manifest and reject stale checksums or host-only paths in that manifest.

Package source precedence remains explicit Anvil source, configured pip sources and then policy-controlled public PyPI. The selected source type/label and whether a corporate source is configured are visible without credentials. Public fallback from a configured corporate source remains opt-in. Global pip configuration is never changed.

## Offline verification

The targeted test matrix covers systemd unit verification and 203/EXEC repair; venv symlink and broken-interpreter behavior; dependency action contracts and credential redaction; stale OpenCode URL and first-probe timeout recovery; release authority; interrupted journal classification; SQLite schema-2 → schema-3 migration and rollback; legacy listener identity and unknown port protection; fresh/upgrade artifact manifests; repairable drift and user-file preservation.

The isolated lifecycle fixture also drives `make upgrade` across an older installed config with missing `runtime-policy.json`, drifted `runtime.py`, a corporate pip config, a pending pre-activation journal and a schema-2 SQLite control store. It exercises both successful schema migration and a forced post-migration failure that restores the original compatible database and config. A subsequent rollback restores schema 2; repeated dry-run does not modify the migrated database. The dry-run assertion ignores only SQLite's transient `context.db-shm` lock bytes; the database, WAL and other persistent state remain byte-for-byte unchanged.

`make test` passed in full. The Analytics offline block ran 118 tests in 13.468 seconds; lifecycle integration passed across OpenCode 1 and 2, including successful upgrade, idempotency, recovery, explicit rollback and injected failures. The full gate also passed the Databricks offline contracts, release/version documentation checks, runtime profiles, communication artifacts and engineering evaluations. `git diff --check` passed. A pass does not establish access to an actual Nexus, systemd user session, Databricks workspace, live OpenCode model or Windows-to-WSL browser session.

## Real-machine rehearsal

```bash
make inspect
make doctor
make capabilities
make upgrade DRY_RUN=1
make upgrade
make inspect
make doctor
make capabilities
make upgrade
```

The production upgrade must run from a committed, verifiable checkout. The last upgrade is the idempotency check; when no drift exists it should avoid dependency rebuilding, service regeneration, database migration and runtime/session restart.
