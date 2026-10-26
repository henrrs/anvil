# Anvil Full-System Quality Audit

**Audit release:** 2.8.0
**Execution environment:** Linux, Python 3.12, isolated test HOME/XDG
**Release mode:** offline fixtures; no user OpenCode, Databricks profile, model, or production state was used.

**Follow-up reassessment:** On 2026-10-25, a production-like 2.6.1 install exposed a false-corruption case that the original audit did not cover. The ownership/lifecycle fix and brownfield regressions now pass the full offline suite; the release recommendation below reflects this retest.

## 1. Executive summary

**Overall status: HEALTHY WITH RISKS.** The refreshed public lifecycle and integration contract suite passes from temporary HOME/XDG roots. State classification, Anvil-only upgrade boundaries, V1/V2 configuration, snapshot recovery, runtime preservation, ownership-aware symlink handling, brownfield migration, and Databricks provider contracts have local regression coverage. The original audit fixed two high-severity behavior defects and two medium-severity reliability/documentation defects; this follow-up reproduced and fixed a third high-severity lifecycle defect.

The initial audit conclusion was incomplete: its generated lifecycle fixture had no package-manager tree or npm-style symlinks beneath the OpenCode config root. This follow-up adds that state, validates both sides of the ownership boundary, and tests the full legacy-to-current lifecycle. It still does not establish live Databricks readiness, model reasoning quality, release artifact availability, macOS behavior, or aesthetic quality of generated diagrams.

## Follow-up reassessment — managed ownership and brownfield state

The escaped defect was reproducible before the product fix: a legacy Anvil 2.6.1 fixture with a valid internal npm `.bin` symlink was classified `CORRUPTED`, and the reported blocker was `symbolic link inside managed config needs manual review`. The old `_files()` helper recursively enumerated the entire OpenCode config root and rejected every symlink before `inspect_source()` consulted the managed manifest or the legacy release inventory.

The prior quality tests missed it for a concrete reason. `tests/lifecycle.py::fixture()` generated an Anvil profile with ordinary user-owned files, but no `node_modules`, package-manager links, or equivalent external runtime-generated tree. Existing symlink regressions covered explicit artifact/input and runtime boundaries, not a symlink inside the OpenCode config root. The source/target ownership tests proved regular-file preservation and collision handling, but never asserted that an unowned symlink was excluded from the Anvil integrity policy. The fixture was too clean for the filesystem shape of a long-lived install, and the missing invariant was “location does not imply ownership.”

The follow-up brownfield fixture now represents the old manifest-less release, a compatible OpenCode 1.19.3 runtime, existing memory, Anvil Databricks config/provider state, a verified rollback snapshot, and both valid and broken npm-style links. It runs inspect, doctor, upgrade dry-run with full zero-write snapshots, real upgrade, post-upgrade inspect/doctor, and reforge. Separate managed-link tests cover escaping skill/command symlinks and a broken managed symlink. A doctor-recommended reforge is executed and verified; an untrusted `opencode.jsonc` symlink receives manual-review guidance, and reforge refuses to read it.

The distinguishing assurance now asserts both directions: unowned symlinks survive literally and never enter the manifest, while symlinks at manifest-owned paths remain corruption. The new npm regression was observed failing against the previous blanket-rejection logic before the implementation changed. The security scenarios fail if managed-path symlink checks are removed.

## 2. Inventory and test baseline

The [system map](system-map.md) catalogs 71 executable source files (56 Python and 15 shell), all Make targets, 35 config assets, six skills, four slash commands, persistent-state roots, external dependencies and failure boundaries. Five test drivers compose the release gate: `tests/run.sh`, plus the lifecycle, Databricks, distill and communication Python drivers.

Before the audit regressions were added, the lifecycle driver had 20 named scenario routines and the existing full `make test` had passed after the lifecycle implementation. The original audit suite had 25 lifecycle scenario routines. The 2026-10-25 follow-up adds three, bringing the lifecycle driver to 28 routines; the four other drivers and the Make test harness remain. New assurance covers ownership migration, disabled custom agents, paths with spaces/Unicode and external cwd, concurrent lifecycle invocation, read-only configuration parent preflight, and brownfield package-manager/managed-symlink boundaries. Assertions within scenarios are not counted as separate tests.

Executed checks:

- `make test` — **PASS** after the 2026-10-25 ownership/lifecycle fix and regression additions. Output: “All Anvil offline checks passed.” This includes the 2.6.1→2.8.0 brownfield migration, valid/broken external npm links, recovery and managed-link security cases.
- `python3 scripts/version_docs.py` — **PASS** for 2.8.0 release/version/inventory documentation.
- `python3 -m py_compile scripts/managed_config.py scripts/lifecycle_state.py scripts/inspect_data.py tests/lifecycle.py` — **PASS**.
- `bash -n scripts/lib/install.sh scripts/reforge.sh scripts/doctor.sh` — **PASS**; the full suite also reports shell/Python syntax **PASS**.
- `git diff --check` — **PASS**.
- `shellcheck`, `ruff`, `mypy`, `pylint`, and coverage/mutation tools — **unavailable**; these were not represented as passing.

Before the fix, the exact regression returned `CORRUPTED` with the blanket symlink blocker. After the fix, the focused brownfield, managed-link recovery, and unsafe-profile recommendation tests passed, followed by a complete `make test` pass. The brownfield dry-run compares full filesystem snapshots across config, Anvil state, memory, runtime and provider files to prove zero writes.

## 3. Functional capability and confidence matrix

Confidence describes executed contract coverage, not production traffic or model quality.

| Capability / entrypoint | Valid flow and state change | Invalid/offline/partial behavior and recovery | Evidence | Confidence |
|---|---|---|---|---|
| First use: `make reforge` | Isolated clean HOME installs fixture runtime/profile and reaches READY; repeat reforge works | Missing release/network is covered as an offline blocker; existing supported runtime is reused | `fresh_machine_command_contract_test`, `reforge_test`, `reforge_preserves_v2_test` | High (fixture) |
| `inspect`, `doctor` | Shared evaluator reports ready/migration/degraded and diagnostic output | Repository-only, missing config/runtime, malformed config/version, unsupported future version and interrupted transaction are distinct | `fresh_machine_command_contract_test`, `partial_lifecycle_matrix_test`, `lifecycle_version_order_test`, recovery tests | High (local) |
| `capabilities`, `stats` | Text/JSON capabilities and structured native stats formatting | Missing runtime is informational; no invented native stats; formatter uses fixture JSON | `tests/run.sh`, fresh command matrix, stats formatter case | High (contracts) |
| Anvil `upgrade` | 2.6/2.7 source profiles advance without runtime/data/state change | Unsupported source/downgrade, collision, read-only parent, active/self OpenCode, user cancellation, offline 403, failed candidate/rehearsal/backup all block safely | V1/V2 upgrade tests, ownership/path/read-only/process/failure-injection scenarios | High (offline) |
| Dry-run | Performs source audit, target generation/rehearsal and process inventory | Filesystem snapshots prove no writes; pending transaction is refused without recovery writes | `dry_run_test`, `filesystem_and_working_directory_test`, interrupted transaction scenario | High (local) |
| `rollback` | Restores scope-consistent snapshot and preserves memory | Missing/invalid snapshot gives blocker; injected post-apply failures roll back; journal recovery validates snapshot | fresh command matrix, runtime migration/rollback, post-config and doctor failure cases | High for fixtures; medium for real archives |
| OpenCode runtime | V1/V2 adapters, policy, PATH-hidden absolute runtime and generation matching | Missing, unsupported, incompatible, active, unrelated-XDG and malformed candidates are handled locally | runtime fixture tests and lifecycle process cases | Medium-high (fixtures only) |
| Config, agents, skills, commands | Generated V1/V2 profiles satisfy current policy; release-owned inventory reconciles migration | User extras/preferences survive; disabled custom agents survive; source-owned removals disappear; path collision blocks | config audit, ownership and agent transition tests, version docs gate | High for known transitions |
| Memory `/remember`, `/recall` | Markdown memory is explicitly written/read; bounded lexical retrieval and V1 entry compatibility | No `rg` fallback tested, malformed entries and missing memory are surfaced; search remains read-only | `tests/distill.py`, memory assertions in run/lifecycle, migration/rollback tests | Medium-high (no model UI) |
| `/distill` and source registry | Named-source provenance, duplicate and drift handling, bounded recall | Changed/missing source is marked for review; repeated unchanged source is idempotent | `tests/distill.py` fixtures: code/docs/tests, conflict/history/drift/unavailable image | Medium (semantic judgment not deterministic) |
| Databricks setup/readiness | Anvil-owned profile, topology/auth strategy, readiness and provider resolution | Missing CLI/pip, auth timeout/cancel, provider timeout, permissions, invalid JSON, no profiles and external-profile isolation use fakes | `tests/databricks.py` and `tests/run.sh` Databricks contracts | Medium (no live workspace) |
| Databricks analytics/FinOps | Bounded query and normalized usage evidence are tested against schema fixtures | Empty/partial/permission/failure tables and estimate provenance are represented by fixture scenarios | FinOps/system-table tests and query recipes | Medium (schemas can evolve) |
| Communication/artifacts | Named local input → evidence/quantitative plan → Markdown/SVG → deterministic review | Type/size/symlink/unsupported optional PDF and no-overwrite boundaries; arithmetic claims recomputed | `tests/communication.py` and `tests/distill.py` fixtures | Medium (narrative truth remains human/model-reviewed) |
| Release/docs consistency | Shipped skills/commands and introduction inventory match release; README/changelog/migration text validated | Malformed/stale documentation fails the release check | `scripts/version_docs.py`, `make test` | High (checked phrases, not prose truth) |
| Isolation/portability | HOME/XDG, missing `rg`, Unicode/spaced paths and `make -C` external cwd | Network is denied; user profiles and production roots are outside test tree | test harness plus new filesystem cases | Medium-high on tested Linux; other OS unverified |

## 4. Quality scorecard

| Area | Status | Confidence | Main remaining boundary |
|---|---|---|---|
| Fresh install and first-use guidance | PASS | High | Actual official release download not exercised |
| Lifecycle state and version skew | PASS | High | Source compatibility window is deliberately bounded |
| Anvil upgrade and dry-run | PASS | High | Tested against local fixtures, not installed OpenCode binaries |
| Reforge and idempotency | PASS | High | First provisioning needs live release source |
| Transaction recovery and rollback | PASS | High for injected paths | No power-loss/disk-full physical test |
| OpenCode V1/V2 integration | PASS (contract) | Medium-high | Fixture versions 1.18.18/2.0.0, no live binary matrix |
| Runtime release update/migration | PASS (offline contract) | Medium | Release API/download availability is external |
| Config and ownership | PASS after follow-up | High (brownfield and adversarial fixtures) | Future new config shapes still need inventory/schema update; no live enterprise install was inspected |
| Memory and source registry | PASS | Medium-high | No large-scale retrieval or semantic model benchmark |
| Databricks provider/auth | PASS (offline contract) | Medium | No real auth, permissions, workspace, CLI or SQL run |
| Databricks FinOps | PASS (fixture) | Medium | Live schema/retention/large result variation unverified |
| Communication/materialization | PASS (deterministic core) | Medium | Model-assisted factual correctness and aesthetics are unverified |
| Diagnostics/exit semantics | PASS | High | Some OS-specific process errors remain environment-dependent |
| Filesystem/XDG isolation | PASS | Medium-high | Linux tested; macOS and constrained enterprise images unverified |
| Documentation/release inventory | PASS | High for checked contracts | Human review remains necessary for nuanced prose |

## 5. Findings and disposition

### P0 — Critical

None found.

### P1 — High, fixed

1. **Paths containing spaces were split while parsing runtime discovery.** Shell `read` used default IFS on tab-delimited output, which also treats spaces as separators. Lifecycle commands could fail to rediscover a valid runtime when HOME/XDG included spaces. Fixed by setting tab-only IFS in `scripts/anvil_upgrade.sh`, `scripts/upgrade.sh`, and `scripts/reforge.sh`. Regression: `filesystem_and_working_directory_test` uses spaced/Unicode HOME and XDG, an external cwd, `make -C`, dry-run, real upgrade, reforge, and same-major runtime update; it verifies Anvil-only commands preserve the runtime and runtime update preserves Anvil config/release.
2. **Disabled custom inline agents were silently lost during profile rebuild.** The generator retained enabled extras but dropped disabled V1/V2 agent definitions, and strict V2 audits rejected additional enabled agents without ownership context. Fixed by preserving disabled user agents, translating V1 `disable` and V2 `disabled`, and using the installed manifest's `managed_agents` list to distinguish Anvil-owned agents. Regression: `custom_agent_transition_test` covers V1→V1, V1→V2, V2→V1, V2→V2 and Anvil-owned removals.
3. **External npm symlinks falsely marked legacy installs corrupted and blocked upgrade.** `_files()` rejected every symlink beneath the OpenCode config root before checking Anvil ownership; the same helper blocked target preparation, while generic corruption text could recommend reforge without evidence that it could run. Fixed by enumerating nodes without following symlinks, applying integrity checks only to manifest/source-inventory paths, preserving unowned links without resolving them, blocking managed links, and deriving lifecycle recovery guidance from known preconditions. Reforge refuses a symlinked source profile. Regression: the 2.6.1 brownfield journey and managed/untrusted symlink cases described above.

All three P1 findings have automated regression coverage and pass in the refreshed full suite. The first two were fixed in the original audit; the ownership/lifecycle finding is fixed and revalidated by this follow-up.

### P2 — Medium, fixed or bounded

1. **Read-only config parent could fail after transaction start.** Reproduction: `make upgrade` with a readable but non-writable config parent created a snapshot/journal, then failed activation; automatic rollback also could not stage into that parent, leaving `RECOVERY_REQUIRED`. Fixed in `scripts/backup_preflight.py` to require writable/searchable config parent before process quiescing and backup. Regression: `readonly_config_parent_preflight_test` checks dry-run and real invocation, unchanged config/data, active runtime preserved, no backup/journal. The command is retryable after permissions are restored.
2. **README release identity lagged behind the repository.** README said 2.7.0 while `VERSION` was 2.8.0 and linked older release notes. Corrected to 2.8.0 links and added README version validation to `scripts/version_docs.py`.
3. **Concurrent loser can leave one unused verified snapshot.** Two concurrent upgrades leave a READY installation, no pending journal, unchanged runtime, and valid snapshots; one process can lose the journal lock after both already created snapshots. No corruption observed; unused verified snapshot is a small disk-space cost. Locking before snapshot creation would remove it, but is deferred because it requires a broader lifecycle lock protocol.

### P3 — Low

No actionable P3 code defect was retained. Static analysis tool gaps are recorded under limits rather than called defects.

## 6. Lifecycle and state assessment

State classification distinguishes `REPOSITORY_ONLY`, `PARTIALLY_INSTALLED`, `READY`, `STALE`, `MIGRATION_REQUIRED`, `DEGRADED`, `UNSUPPORTED`, `CORRUPTED`, `TRANSITION_IN_PROGRESS`, and `RECOVERY_REQUIRED`. Runtime-major support is evaluated separately from Anvil version. A future installed Anvil release blocks both upgrade and reforge before backup; a compatible prior release is checked against its own source inventory, not the target's shipped set.

The lifecycle order is: inspect/source audit → stage target → runtime/config rehearsal → backup readiness → inspect process scope → approval/countdown → quiesce → verified snapshot → durable journal → config activation → metadata update → local doctor → journal clear. Failure injection covers candidate validation, rehearsal, backup creation, after config rename (hard kill), post-config failure, failure before metadata, and postflight doctor failure. Recovery verifies the recorded snapshot before restore and retry. Read-only preflight now checks the config swap parent as well as backup destination.

Evidence: `tests/lifecycle.py` reports successful config-only/runtime-only/corrupt states, semantic source window/downgrade rejection, interrupted activation recovery, rollback scope checks, Anvil 2.6.1→2.8 and both runtime generations, runtime identity unchanged for Anvil-only upgrade, cancellation, SIGTERM/SIGKILL order, and verified concurrent state.

## 7. Integration-focused assessment

### OpenCode

The adapter boundary supports OpenCode 1 and 2. Anvil-only upgrade and healthy-runtime reforge preserve the exact validated executable. `update-runtime` is same-major; `migrate-runtime` is explicit major transition. Runtime absence, usability, support, active process and PATH visibility are distinct. Tests use wrappers at supported compatibility versions and cannot establish behavior of actual released binaries or native UI invocation.

### Databricks

Databricks failure is isolated from Anvil lifecycle health. Setup uses an Anvil-owned staged profile, topology-aware auth strategy, sanitized child environment, bounded provider calls, shared readiness evaluation and provider-specific fallback. Tests include auth cancellation/timeouts and fake CLI/SDK worker boundaries. No credentials or live profile were read during this audit. Real workspace, token refresh, access grants, API version drift and large result performance remain unverified.

### Memory and source provenance

Markdown is the source of truth under XDG data; upgrade/reforge/runtime rollback tests preserve it. Search without `rg`, provenance, duplicates, source changes, multilingual aliases, invalid entries and no-write recall are tested. Cross-repository behavior is represented through explicit repository/source metadata, not a real multi-user store. Large unbounded corpus latency and concurrent writers are not measured.

### Communication and materialization

Pure-Python checks cover bounded input extraction, evidence IDs, arithmetic and missing-value semantics, audience/constraint plans, exact slide structure, recomputed derived values, safe Markdown writes, SVG geometry/accessibility and review findings. They do not evaluate an LLM's factual synthesis, design taste, PowerPoint/PDF rendering, OCR, embedded media, or charts; unavailable formats are explicitly reported.

## 8. Remaining risks and unverified conditions

- Concurrent lifecycle attempts can leave an extra valid snapshot, as above.
- No live OpenCode binary release, network/proxy behavior, installer checksum fetch, or official artifact smoke test was run; lifecycle tests deliberately deny external network.
- The brownfield package-manager tree is intentionally small and models ownership/link semantics rather than production scale. Very large `node_modules` trees will increase config staging and snapshot time/space; backup preflight checks available space, but large-tree performance was not benchmarked.
- No real Databricks/Azure/SQL workspace or credential session was used. Databricks results are contract-level confidence only.
- No model was invoked. `/distill` and communication skill reasoning remain dependent on model/user judgment; deterministic helper success is not semantic truth verification.
- macOS, Windows outside WSL, alternate Bash/Make/tar implementations, low-disk conditions, ACL-only permission changes, and actual power loss are not verified.
- `shellcheck`, `ruff`, `mypy`, `pylint`, coverage and mutation testing tools were unavailable. Python and shell syntax checks passed; static source review and the project regression suite are the available evidence.
- No performance baseline was collected for very large memories, artifact inputs, or Databricks result sets. Configured bounds and fixture limits are tested, but production latency is not.

## 9. Documentation consistency and recommended priorities

The release gate now checks that `VERSION`, changelog, README, release/migration notes, shipped skills/commands and managed introduction inventory agree. The full [system map](system-map.md), [public command contract](command-contracts.md), [testing guide](testing.md) and migration notes describe current behavior. Documentation checks verify required phrases and sets; they do not replace human editorial review.

Recommended next engineering priorities:

1. Add Linux CI jobs for at least two supported Python versions and a second distribution image; run shellcheck/ruff/mypy when available.
2. Run a controlled smoke matrix against real supported OpenCode binaries and one non-production Databricks workspace in an environment with approved network access.
3. Consider acquiring a lifecycle lock before snapshot creation to prevent the concurrent unused-snapshot residue.
4. Add corpus/performance and property-based mutation checks when project dependencies and CI budget are agreed.

## 10. Final adversarial answers

| Question | Evidence-backed answer |
|---|---|
| Can a new user install without undocumented recovery knowledge? | The documented first-use path is `make reforge`; isolated first-use tests reach READY and check all public commands before/after. Real runtime download still needs the official release service. |
| Can the previous supported release upgrade safely? | Yes for tested 2.6.1 profiles on OpenCode 1 and 2; source-owned inventory, user extras, runtime identity, data and state are checked. |
| Can a halfway operation fail safely and retry? | Injected hard interruption yields `RECOVERY_REQUIRED`; a later retry restores a verified snapshot and finishes READY. |
| Can rollback return a coherent state? | Runtime-scope tests restore executable/config/data/state; Anvil-scope tests preserve runtime/data/state; memory remains in place. |
| Does Anvil upgrade unnecessarily change OpenCode? | No in tested 1/2 fixture cases; exact binary hash and data/state hashes remain unchanged. |
| Are stale, migration, unsupported, corrupt and recovery states distinct? | Yes in the lifecycle state matrix and version-order fixtures. |
| Are user-owned files protected? | Tested extras/preferences and disabled custom agents survive; collision blocks before mutation. A concurrent unused snapshot is the known residue. |
| Do non-default HOME/XDG paths work? | Tested across isolated roots, spaces, Unicode and external cwd; read-only config parent blocks before mutation. Other OSes remain unverified. |
| Do provider outages corrupt core Anvil state? | Databricks contract tests show setup/provider status is separate from core lifecycle; no live workspace outage test was run. |
| Does memory survive lifecycle operations? | Tests verify memory remains through Anvil/runtime rollback and is outside snapshots; large-scale or multi-user semantics are not established. |
| Will every future skill/command/agent/config change migrate automatically? | Skills/commands have an introduction-version inventory; inline agents have managed ownership metadata. New config fields still require explicit migration/audit design and regression tests. |
| Would the original quality audit have caught the observed npm-symlink regression? | No. Its fixtures omitted package-manager trees beneath the global config and its symlink assertions did not exercise managed-config discovery. The follow-up brownfield regression now fails on the old blanket-rejection behavior and covers valid, broken, unowned, and managed symlinks. |

## 11. Release recommendation

**SAFE WITH CONDITIONS.** The tested offline/core lifecycle release has no open P0/P1 findings, the new P1 regressions are covered, and `make test` passes. Treat real release download, live OpenCode UI behavior, and live Databricks auth/workspace readiness as separate environment-specific smoke checks; do not infer those from the offline suite.
