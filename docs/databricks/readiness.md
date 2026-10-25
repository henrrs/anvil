# Databricks readiness contract

Anvil 2.6 treats `READY` as a recently proven runtime property. A saved profile or a successful login alone is not enough. Setup, status, and doctor use the same Databricks provider adapter and readiness evaluator.

## State progression

```text
CONFIGURED
    ↓ Anvil-owned profile parses; host and config path match
AUTHENTICATED
    ↓ intended CLI/SDK auth context is accepted
WORKSPACE_VALIDATED
    ↓ read-only current-user request returns an identity for that host
PROVIDER_VALIDATED
    ↓ selected production provider completes through Anvil's adapter
CAPABILITIES_DISCOVERED
    ↓ cluster-list and warehouse-list results are checked
READY
```

The stored `state` is the highest stage whose conditions passed. `overall` is `NOT_CONFIGURED`, `NOT_READY`, `DEGRADED`, or `READY`:

- `READY` requires authenticated identity, a reachable workspace, a validated CLI or SDK provider, and verified `compute.list` plus `warehouse.list` results.
- A successful empty list is verified and available with a count of zero. Running compute, SQL, and system-table access are not setup requirements.
- `DEGRADED` means some core capability works while another is unavailable, such as a permission-denied cluster list with a successful warehouse list.
- `NOT_READY` means identity, workspace reachability, provider health, or all core capabilities could not be proven.
- `NOT_CONFIGURED` means Anvil has no selected Anvil-owned workspace profile.

## Audit findings and execution map

The pre-2.6 setup path did validate profile ownership and call `current-user`, but it then built setup readiness from the locally discovered provider inventory. `resolver.overall_state` treated installed CLI/SDK providers plus a successful identity check as evidence for `workspace.list`, `compute.list`, `warehouse.list`, Python, and SQL. It did not run the core cluster and warehouse list operations before promoting a new profile. The old status path did run cluster and warehouse discovery, but a caught provider error only became a `limitation`; final readiness was then recomputed from installed provider inventory and identity. A timeout could therefore coexist with a `READY` result. Those are the direct false-readiness causes in the repository baseline.

The same path also repeated remote profile discovery and identity validation on later calls, then used a generic 20-second CLI request budget. This added authentication/network work before the requested operation and gave cold identity acquisition and metadata lists the same budget. `subprocess.run(capture_output=True)` collected both streams, but had no output bound or process-group cleanup for descendants. These are reliability and observability gaps; the core defect was that setup/status inferred capability health from provider inventory rather than proving the production operation.

Current call path:

```text
make databricks-setup
  → scripts/databricks.py setup
  → owned_config.stage_profile + explicit auth strategy
  → _authenticate_workspace / candidate identity
  → _setup_summary / _probe_readiness
  → json_from_cli → _call_provider → resolver
  → run_cli → owned_config.child_environment → process.run
       or sdk.call → bounded SDK worker
  → on provider-specific CLI health failure only: explicit setup may install SDK,
    refresh provider inventory, and repeat the same production probes
  → validate current-user + clusters list + warehouses list
  → atomically promote candidate config and save schema-3 state

new session
  → status performs the same read-only readiness probe
  → local cached capabilities apply a 15-minute freshness limit
  → capability commands use resolve_profile's Anvil-owned local state
    and json_from_cli → the same provider adapters and child environment
```

`scripts/databricks_providers/auth.py` owns explicit interactive login and local auth-session checks. `discovery.py` inventories installed providers; inventory is no longer treated as remote health. `resolver.py` decides capability provider order and records rejected candidates. `errors.py` defines shared versus provider-specific failure policy. `state.py` validates secret-free schema-3 state and writes it through fsync plus atomic replacement. `presentation.py` renders human and JSON status. `scripts/doctor.sh` invokes live read-only status for configured profiles, while lifecycle postflight sets `ANVIL_DOCTOR_LOCAL=1` to keep upgrades independent of Databricks. The Anvil skill's command examples are parser-tested.

Authentication, workspace, provider, and capability evidence remain separate. An Azure CLI session does not prove Databricks authentication; identity success does not prove every provider or capability works.

### 2.6.1 corrective audit

A reported setup run in a WSL environment successfully validated the Azure-backed Databricks identity and workspace, then timed out after 45 seconds on the CLI `clusters list` operation. The result correctly remained `NOT_READY` and left the existing profile unchanged. Its sanitized output could not establish whether the CLI wait came from Azure token refresh, a proxy/network path, or the workspace request itself, so the release does not claim or assume one of those causes.

The repository-level cause was confirmed offline: setup installed the SDK only when the CLI executable was missing, while the resolver only falls back to providers already discovered as installed. In the existing-profile setup path, a provider-specific CLI health failure therefore returned without trying to prepare the SDK. The presenter compounded this by saying the SDK fallback was “not needed” based on inventory, even when the CLI health probe had failed. A second clean-process test showed that discovery could load a recorded SDK executable, while the SDK adapter discarded that inventory and rediscovered only default paths.

Anvil 2.6.1 corrects those boundaries. During the explicit setup command only, a normalized provider-specific CLI failure may trigger isolated SDK installation and a full re-run through the shared resolver. The resolver passes its validated SDK executable to the adapter, and direct SDK calls consult the saved inventory. Shared authentication, workspace-network, permission, invalid-argument, and unknown failures do not trigger installation or provider roulette. Metadata-list operations use their own timeout class; its 45-second value is unchanged.

### 2.6.2 bootstrap diagnostics

Anvil 2.6.2 preserves the same readiness stages and schema-3 persistence rules. SDK setup now reports missing Python, venv, pip, or package-source prerequisites as structured provider state. The worker constructs an explicit SDK `Config` from the selected Anvil profile and owned config file; allowlisted failure phase and normalized status survive into the setup/doctor presenter without forwarding exception text or response bodies. A blocked SDK fallback does not invalidate a healthy CLI provider or promote an unverified provider to READY.

## One production path

`make databricks-setup` stages an Anvil-owned config, authenticates through the selected strategy, and validates `current-user me`, `clusters list`, and `warehouses list` through `json_from_cli` → the capability resolver → the same CLI/SDK adapters used by a later session. The profile, absolute CLI, sanitized child environment, timeout class, error mapping, and JSON validation are shared. A fresh process test reloads the persisted config and performs status and cluster discovery.

The staged config is promoted only after required readiness evidence exists. A failed first setup discards the candidate. A failed revalidation keeps an existing active config but records the current failure. Provider state uses schema 3, atomic replace plus parent-directory sync, and contains only non-secret validation metadata.

## Freshness and commands

`databricks.py status` and `make doctor` perform fresh, read-only identity and core-list checks when an Anvil profile exists. When no profile exists, doctor reports `NOT_CONFIGURED` without contacting Databricks. Runtime failures update saved capability evidence and invalidate readiness in the same domain evaluator.

`make capabilities` stays local. It reports `supported`, `available`, and `verified` separately. Cached verification is considered stale after 15 minutes; stale evidence is no longer reported as verified. `make databricks-setup` remains the only command that owns interactive authentication.

The stable resource grammar puts common flags after the resource arguments:

```text
clusters list --format json
clusters get CLUSTER_ID --format json
warehouses list --profile anvil-dev --format json --timeout 45
jobs list --format json
workspace list /Shared --format json
```

`--profile` always refers to an existing Anvil-owned profile. `--timeout` is an integer from 5 to 600 seconds. Invalid arguments return `CLI_ARGUMENT_ERROR`.

## Provider fallback

Fallback is allowed only when the failure is provider-specific and retrying the same read-only operation through another installed provider is useful. This includes a CLI process timeout, invalid CLI JSON, or an unavailable/blocked provider. The resolver records the selected provider, rejected providers, fallback reason, and blocking condition.

Normal runtime commands can fall back only to an already installed provider. The explicit `make databricks-setup` command may install the isolated SDK after a provider-specific CLI health failure, then repeat all required checks. CLI executable presence/version is local inventory, not provider health. A successful setup persists the selected SDK and validated absolute Python path; a clean session uses that same path. A blocked SDK installation leaves readiness unproven and reports the installation blocker.

`CLI_PROCESS_TIMEOUT` is provider-specific and may fall back; it includes operation, elapsed timeout, executable, and profile in the diagnostic. `WORKSPACE_NETWORK_TIMEOUT`, `WORKSPACE_UNREACHABLE`, `AUTH_REQUIRED`, and `AUTH_INVALID` are shared blockers and stop provider selection.

Authentication failures, shared workspace timeouts/unreachability, permission denials, invalid arguments, and unknown CLI execution failures stop immediately. CLI and SDK share the same workspace and credentials; trying both after a shared failure adds delay without a new chance of success. Permission failures remain attached to that capability. SQL and remote Python execution are not replayed after a request is dispatched because the completion state may be unknown.

## Timeout policy

Timeout budgets start before process creation and include startup plus credential resolution. Process output is drained from stdout and stderr together with a 4 MB total bound. POSIX provider commands run in a new process group; timeout or overflow sends SIGTERM, waits one second, then sends SIGKILL to the group.

Before 2.6, the Databricks CLI wrapper used a generic 20-second default for provider requests; setup identity checks used separate 15- and 20-second calls, and SQL had a 30-second default. 2.6 uses 5 seconds for local version/session checks and separate 45-second budgets for workspace identity, provider health, and metadata lists. These include process startup and credential resolution; 2.6.1 routes cluster and warehouse inventory through the metadata-list class without increasing its budget. Explicit authentication has a 90-second inactivity watchdog and 180-second hard cap; SQL and remote Python use 120 seconds; explicit long operations have a 600-second cap; workers have a 15-second teardown allowance. The regression suite injects short limits for hangs and uses bounded fixture delays for slow success, so no test burns the production timeout budget.

| Operation | Budget |
|---|---:|
| CLI version and local auth-session check | 5 s |
| Workspace identity request | 45 s |
| Provider health request | 45 s |
| Cluster or warehouse metadata list | 45 s |
| Explicit interactive authentication inactivity watchdog | 90 s |
| Explicit interactive authentication hard limit | 180 s |
| SQL statement and remote Python operation | 120 s each by default |
| Explicit long operation hard cap | 600 s |
| SDK/connector worker teardown allowance | 15 s beyond its request budget |
| Process-group termination grace | 1 s |

SDK HTTP calls use a per-request HTTP timeout capped at 60 seconds and a retry deadline bounded by the operation budget. SQL request/poll calls have smaller request timeouts inside the overall SQL deadline. These values live in `scripts/databricks_providers/timeouts.py` and are covered by local fixture tests; no live workspace latency is claimed.
