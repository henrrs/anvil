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

`CLI_PROCESS_TIMEOUT` is provider-specific and may fall back; it includes operation, elapsed timeout, executable, and profile in the diagnostic. `WORKSPACE_NETWORK_TIMEOUT`, `WORKSPACE_UNREACHABLE`, `AUTH_REQUIRED`, and `AUTH_INVALID` are shared blockers and stop provider selection.

Authentication failures, shared workspace timeouts/unreachability, permission denials, invalid arguments, and unknown CLI execution failures stop immediately. CLI and SDK share the same workspace and credentials; trying both after a shared failure adds delay without a new chance of success. Permission failures remain attached to that capability. SQL and remote Python execution are not replayed after a request is dispatched because the completion state may be unknown.

## Timeout policy

Timeout budgets start before process creation and include startup plus credential resolution. Process output is drained from stdout and stderr together with a 4 MB total bound. POSIX provider commands run in a new process group; timeout or overflow sends SIGTERM, waits one second, then sends SIGKILL to the group.

Before 2.6, the Databricks CLI wrapper used a generic 20-second default for provider requests; setup identity checks used separate 15- and 20-second calls, and SQL had a 30-second default. 2.6 uses 5 seconds for local version/session checks, 45 seconds each for identity/provider health/metadata lists, 90 seconds of interactive-auth inactivity with a 180-second hard cap, 120 seconds for SQL and remote Python, 600 seconds as the explicit long-operation cap, and 15 seconds of worker teardown allowance. The regression suite injects short limits for hangs and uses bounded fixture delays for slow success, so no test burns the production timeout budget.

| Operation | Budget |
|---|---:|
| CLI version and local auth-session check | 5 s |
| Workspace identity, provider health, and metadata list request | 45 s each |
| Explicit interactive authentication inactivity watchdog | 90 s |
| Explicit interactive authentication hard limit | 180 s |
| SQL statement and remote Python operation | 120 s each by default |
| Explicit long operation hard cap | 600 s |
| SDK/connector worker teardown allowance | 15 s beyond its request budget |
| Process-group termination grace | 1 s |

SDK HTTP calls use a per-request HTTP timeout capped at 60 seconds and a retry deadline bounded by the operation budget. SQL request/poll calls have smaller request timeouts inside the overall SQL deadline. These values live in `scripts/databricks_providers/timeouts.py` and are covered by local fixture tests; no live workspace latency is claimed.
