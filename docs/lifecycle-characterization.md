# Lifecycle characterization and certification matrix

The architecture refactor starts from observable behavior rather than individual implementation branches. The baseline is `make test` on Anvil 2.17.0 before lifecycle code changes. The baseline exercises temporary HOME/XDG roots and fake OpenCode/Databricks services; no production installation is changed.

| Scenario | Pre-refactor evidence | Contract to retain or strengthen |
| --- | --- | --- |
| Fresh install, no OpenCode | `fresh_machine_command_contract_test`, `partial_lifecycle_matrix_test` | Inventory works, reforge installs the policy default, upgrade/rollback explain prerequisites. |
| Healthy existing V1/V2 | `local_inventory_and_external_runtime_test`, `reforge_preserves_v2_test`, `upgrade_preserves_v1_test`, `upgrade_preserves_v2_test` | Runtime generation and Anvil release stay separate. |
| Prior supported release | `observation_characterization_test`, `config_ownership_transition_test`, `engineering_manifest_upgrade_test` | Inspect and doctor identify migration; capabilities use local facts. |
| Legacy unversioned and package-manager runtime | `brownfield_legacy_npm_symlink_test` | Recognize supported legacy sources and preserve external runtime links. |
| Managed drift, missing file, unsafe link | `managed_file_repair_test`, `managed_symlink_recovery_test`, `managed_profile_symlink_recovery_test` | Repair only verified owned regular files; unsafe state blocks. |
| New target path occupied by user file | `verified_target_path_match_test`, `config_ownership_transition_test` | Preserve exact matching external file and reject differing content. |
| Analytics absent, installed, dependency missing | `tests/analytics_lifecycle.py`, `tests/analytics/test_runtime.py`, `tests/analytics/test_dependencies.py` | Distinguish installation, dependency, service, runtime and canonical session. |
| Analytics service inactive/active/broken unit | `tests/analytics/test_service_management.py`, `tests/analytics_lifecycle.py` | Status is read-only; start converges only the managed service. |
| Databricks configured/unconfigured, local/live | `tests/databricks.py` | Local inventory does not require a remote login or mutate credentials. |
| Snapshot available/unavailable, failure/rollback | `fresh_machine_command_contract_test`, `anvil_upgrade_rollback_test`, `upgrade_test`, `interrupted_transaction_recovery_test` | Snapshot precedes mutation; failed apply restores exact scoped state. |
| Same-major runtime update / explicit major migration | `update_runtime_test`, `upgrade_test`, `dry_run_test` | Product release is unchanged by runtime commands; major transition remains explicit. |
| Concurrent operation and cancellation | `concurrent_lifecycle_test`, `runtime_quiesce_test` | A second writer blocks; cancellation leaves live state intact. |
| Malformed or legacy scalar persisted state | `malformed_observation_characterization_test` | Public observe commands report domain diagnostics without raw exceptions or mutations. This is a known failing edge before normalization. |

The test cases above are named functions or isolated test files in the repository. New architecture tests should assert normalized states, plan order, dry-run purity, structured verification and observe-command consistency. They should not merely compare implementation-specific helper output.

## Certification questions

| Command family | Healthy | Previous/legacy | Drift or malformed | Idempotency | Failure and rollback |
| --- | --- | --- | --- | --- | --- |
| Observe (`inspect`, `doctor`, `capabilities`, `stats`, `analytics-status`) | Facts and feature availability agree | Migration/legacy state is explicit | No traceback; no installed-state writes | Repeat returns equivalent facts | n.a. |
| Product (`upgrade`, `reforge`, `rollback`) | Converges intended product scope | Supported migration or explicit block | Repairable versus unsafe is explicit | Second plan is empty or justified | Snapshot and restore verified |
| Runtime (`update-runtime`, `migrate-runtime`) | Keeps product release stable | Supported adapter transition | Invalid candidate blocks before apply | Current candidate causes no unrelated change | Runtime-scope snapshot verified |
| Modules (`analytics`, `databricks-setup`) | Makes configured integration usable | Preserves supported state | Degraded service/provider remains distinguishable | Repeat does not create duplicate state | Staged changes fail safely |
| Validate and development | Isolated fixtures or foreground development process | Previous snapshot fixture | Reports failures | Repeated fixtures are independent | No production installation writes |

The final pass should rerun the same inventory, full offline suite and the new normalizer/planner/operation tests. Optional live provider checks remain separate because offline certification cannot prove remote service permissions or network reachability.
