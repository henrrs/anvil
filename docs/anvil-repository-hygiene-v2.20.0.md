# Anvil 2.20.0 — Repository Hygiene & Architectural Simplification

Audit date: 2026-11-14
Repository version: `2.20.0`
Branch and starting revision: `master` at `a51bd3c`

## Executive Summary

The repository is organized around explicit runtime, lifecycle, Analytics,
Databricks, communication, and engineering boundaries. Reachability review did
not establish a high-confidence dead production component or dependency that
could be removed without risking dynamic loading or a supported compatibility
path. The historical Analytics screenshots and certification outputs are
referenced evidence and remain in place.

The audit found five duplicate document paths in the `required` dictionary in
`scripts/version_docs.py`. Python silently retained only the last value for
each repeated key, dropping earlier release and compatibility requirements
from the check. The requirements are now consolidated, and `tests/run.sh`
asserts that this dictionary has unique paths. No runtime, install, migration,
or persistence behavior was changed. No files were removed or moved, and no
dependencies were added or removed.

## Repository Inventory

### Protected Starting State

At audit start, the worktree was already on `master` at `a51bd3c`, with
`VERSION` set to `2.20.0`. It contained 23 modified tracked files and six
untracked groups from the preceding 2.20.0 engineering task. The existing diff
reported 302 insertions and 41 deletions across the modified tracked files.
Those changes were treated as protected input and were not reset or replaced.

The six pre-existing untracked groups were:

- `config/skills/anvil-engineering/references/quality.md`
- `docs/decisions/ADR-0024-engineering-compaction-and-evaluation.md`
- `docs/engineering-harness-report-v2.20.0.md`
- `docs/migrations/v2.19.0-to-v2.20.0.md`
- `docs/versions/v2.20.0.md`
- `evals/engineering/retry-policy/`

The 23 tracked paths already modified at the start were:

`CHANGELOG.md`, `Makefile`, `README.md`, `VERSION`,
`config/managed-inventory.json`, `config/plugins/anvil-core/index.ts`,
`config/skills/anvil-engineering/SKILL.md`, `docs/RELEASING.md`,
`docs/engineering-evaluation.md`, `docs/engineering.md`,
`docs/opencode-compatibility.md`, `docs/runtime-compatibility.md`,
`docs/system-map.md`, `docs/versions/README.md`, `evals/engineering/run.py`,
`scripts/capabilities.py`, `scripts/engineering/cli.py`,
`scripts/engineering/context.py`, `scripts/semver.py`,
`scripts/version_docs.py`, `tests/databricks.py`, `tests/engineering.py`, and
`tests/run.sh`.

The audit later made a narrow change to the two already-modified files
`scripts/version_docs.py` and `tests/run.sh`, and created this report. The
pre-existing 2.20.0 edits in those files remain part of the worktree.

### Counts at Baseline and After Audit

Counts below use `git ls-files` and source extensions, read from the worktree
at each point. The six pre-existing untracked groups and this report are not
included in tracked-file totals. Source line counts exclude Markdown, JSON,
images, caches, virtual environments, and vendored dependencies.

| Measure | Before | After | Notes |
| --- | ---: | ---: | --- |
| Tracked files | 700 | 700 | No tracked files added, removed, or moved |
| Files under `scripts/` | 134 | 134 | Entrypoints and imported modules retained |
| Production source lines | 40,306 | 40,300 | Six duplicate requirement-map lines consolidated |
| Test source lines | 11,952 | 11,966 | Added a 14-line duplicate-key regression check |
| Evaluation source lines | 4,702 | 4,702 | No evaluation fixture or gate removed |
| Tracked documentation lines | 7,231 | 7,231 | Historical version documents retained |
| Managed guidance lines | 785 | 785 | No agent or skill content removed |
| Configuration/data lines | 10,949 | 10,949 | Manifests and runtime policy retained |
| Git executable-mode files | 4 | 4 | The four executable files are CLI test fixtures |
| Direct pinned Python packages | 2 | 2 | DuckDB and PyArrow in the Analytics lock |
| Duplicate paths in release-doc requirements | 5 | 0 | 82 unique document paths remain |

Tracked files by top-level area: `artifacts/` 195, `config/` 58, `docs/` 129,
`evals/` 60, `scripts/` 134, `tests/` 102, `apps/` 9, `web/` 8, and five
root-level files.

Tracked file extensions: `.py` 193, `.md` 191, `.png` 191, `.json` 55,
`.sh` 17, `.csv` 13, `.js` 7, `.sql` 7, `.txt` 5, `.html` 3, `.css` 3,
`.jsonc` 3, `.ts` 2, `.mjs` 1, `.xml` 1, `.lock` 1, and seven files without
an extension.

The repository declares no Node package manifest or Node dependency lockfile.
The only direct pinned Python packages are `duckdb==1.5.5` and
`pyarrow==26.0.0` in `config/analytics-requirements.lock`; the Analytics
installer prepares its own Anvil-managed environment. These packages are not
installed in the system Python used for this audit. The existing `.gitignore`
excludes `__pycache__/` and `*.py[cod]`; no Python bytecode is tracked.

### Repository Areas and Classification

| Area | Classification | Evidence and decision |
| --- | --- | --- |
| Make targets and `scripts/*.sh` lifecycle commands | ACTIVE | Public targets in `Makefile`; the full lifecycle suite invokes inspect, reforge, Anvil upgrade, runtime update/migration, and rollback paths. |
| `scripts/lifecycle_*.py`, `managed_config.py`, `installation.py`, and runtime state helpers | ACTIVE | Shared planning, manifest, transaction, recovery, verification, and runtime code is reached by lifecycle entrypoints and fault-injection tests. Retained. |
| OpenCode V1 profile, plugin, and migration adapters | LEGACY REQUIRED | V1 is the default runtime policy and remains an explicitly supported major; offline profile fixtures and migration/rollback tests exercise it. |
| OpenCode V2 profile and core plugin | ACTIVE | V2 profile fixture, capability checks, plugin contract checks, and engineering compaction tests exercise the path. Live V2 loading was not performed. |
| `scripts/analytics/`, Analytics service and UI | ACTIVE / DORMANT INTENTIONAL | Local service and UI are explicit Make targets; tests cover startup, data handling, transfer, provider behavior, and recovery. Browser-based geometry checks are separate. |
| `scripts/databricks.py` and `scripts/databricks_providers/` | ACTIVE / DORMANT INTENTIONAL | The provider is optional and selected by explicit setup/status/execution paths; offline fake-provider tests cover it. No live workspace was contacted. |
| `scripts/communication/` and `scripts/analysis/` | ACTIVE | Public Make targets, commands, capability output, and offline contracts/evaluators consume these modules. |
| `scripts/engineering/`, engineering skills and replay/model evaluations | ACTIVE / DORMANT INTENTIONAL | Deterministic replay is used by offline tests; live model evaluation requires explicit model/runtime arguments and was not run. |
| `artifacts/analytics-*/` | GENERATED, retained evidence | The 195 tracked files total 34.54 MiB. The 191 PNGs record baseline/final responsive and tab geometry; reports link to them, and `scripts/analytics_ui_visual_check.py` writes new captures to a documented final directory. The four certification files are documented outputs. None was treated as disposable. |
| `tests/fixtures/` and offline CLI/provider fakes | ACTIVE test fixtures | The contract suite invokes these paths to validate offline and failure behavior; retained. |
| Local ignored `__pycache__` output | GENERATED, untracked | Present in the working tree but excluded by `.gitignore` and absent from `git ls-files`; not repository content and not deleted. |
| Candidate code with no static import edge | UNKNOWN until entrypoint checks | Static import search produced apparent misses that are direct scripts, `python -m` targets, test-discovery cases, or dynamic/plugin-loaded modules. Cross-checking Make targets, shell invocations, tests, and docs did not establish safe dead-code removals. |
| Confirmed dead production code/dependencies | None found at high confidence | No removal was justified by combined static, dynamic, lifecycle, fixture, and documentation evidence. |

The source-level Python dependency scan found DuckDB and PyArrow as the only
non-standard-library packages used by the Analytics path. The environment
check found neither in system Python. `shellcheck`, `ruff`, and `pytest` are
not installed; no package installation was attempted.

### Artifact and Documentation Checks

The 191 PNGs are grouped under the Analytics tab-indicator, local-reliability,
responsive, responsive-polish, UI-refinement, and production-hardening
histories. Reports link to representative baseline and final screenshots.
Removing them would discard visual regression evidence rather than eliminate
an unused cache.

A read-only scan checked 350 local Markdown links. One relative image target
is intentionally absent:
`tests/fixtures/distill/case-g/unavailable-diagram.md` refers to
`images/pipeline-topology.png`. `tests/distill.py` asserts that the image is
not available and expects `image-not-inspected`, so this is an intentional
fixture, not a broken user-facing document link.

The release documentation check validates the current release document,
version history, capability references, migration/release requirements, and
managed inventory file sets/introductions. It passes after the duplicate-key
repair. No manifest, checksum, generated runtime profile, or persisted user
state was changed by the audit.

## Dead Code Analysis

| Candidate | Classification | Confidence | Evidence and decision |
| --- | --- | --- | --- |
| Repeated keys in `scripts/version_docs.py` | DUPLICATED | HIGH | Five repeated literal paths caused Python to discard earlier phrase lists. Consolidated all requirements per path and added a regression assertion. |
| V1 runtime/profile files | LEGACY REQUIRED | HIGH | Supported-major policy, V1 configuration/profile fixtures, and compatibility/migration tests. Preserve. |
| Offline V1/V2 and Databricks executables | ACTIVE test fixtures | HIGH | Explicitly passed to `tests/run.sh`; test scripts invoke them as contract providers. Preserve. |
| Analytics screenshot/certification artifacts | GENERATED, retained evidence | HIGH | Referenced by reports and UI validation instructions; preserve baselines and final captures. |
| Model evaluation entrypoints | DORMANT INTENTIONAL | HIGH | Explicit opt-in Make targets with provider/model arguments; no live provider used by the default suite. Preserve. |
| Modules lacking an import-graph edge | UNKNOWN | LOW | Several are CLI entrypoints, direct test modules, shell-loaded code, or dynamic/runtime capabilities. Static absence is insufficient evidence. Preserve. |
| Other dead functions, classes, helpers, or dependencies | No high-confidence candidate | — | No safe removal established by the available call/import, shell, Make, fixture, and documentation cross-checks. |

Test organization was reviewed through `scripts/test.sh`, `tests/run.sh`,
`tests/lifecycle.py`, Analytics unittest discovery, and the direct engineering,
communication, analytical, and Databricks runners. The suites cover distinct
public contracts, failure recovery, runtime profiles, and user-data
preservation. No test group was removed or weakened.

## Architectural Findings

The lifecycle path has explicit shared planning, serialized change-plan
validation, operation execution, transaction state, recovery, and verification
modules. Shell commands coordinate those shared boundaries rather than
independently reimplementing the full lifecycle. Existing tests exercise
dry-run, idempotence, interruption, managed-file repair, active runtime
quiescing, migration, rollback scope, and injected failures. This is a
critical safety boundary; broad restructuring is not justified by the audit.

Analytics is split into service, API/server, catalog, context store, transfer,
materialization, query, scheduling, runtime, and provider modules. Databricks
provider-specific auth, discovery, health, process, topology, and configuration
code is separated into `scripts/databricks_providers/`. Communication and
analytical workflows also have dedicated packages and deterministic offline
tests. These are meaningful boundaries and were retained.

Several modules and functions are large enough to merit future, separately
tested refactoring. An AST inventory found the following spans; the branch
column counts local `if`, loop, `try`, `with`, and `match` nodes, excluding
nested functions. It is a rough comparison aid, not formal McCabe complexity.

| Function | Lines | Branch-node proxy |
| --- | ---: | ---: |
| `scripts/analysis/semantic.py:infer_semantic_context` | 642 | 128 |
| `scripts/analysis/primitives.py:_records_for_operation` | 324 | 42 |
| `scripts/communication/contracts.py:validate_artifact` | 275 | 82 |
| `scripts/databricks.py:setup` | 270 | 40 |
| `scripts/lifecycle_state.py:evaluate` | 245 | 43 |

These are not proof of poor design or dead code. They handle complex contracts
and failure cases, and this maintenance task did not establish small,
behavior-preserving seams with equivalent tests. Splitting them now would add
risk without verified simplification. Record them as focused future review
areas instead of making cosmetic edits.

No dependency duplication or unused direct package was confirmed. The pinned
Analytics packages are imported by the optional Analytics path, and
`scripts/analytics_dependencies.py` installs them into an isolated managed
environment. No dependency changes were made.

## Changes Implemented

1. Consolidated the five repeated document-path keys in
   `scripts/version_docs.py`. All prior phrases, including the 2.20.0
   compaction and engineering-evaluation requirements, are present in the
   surviving lists. This removes six net source lines and restores checks
   previously overwritten by Python dictionary semantics.
2. Added a 14-line AST assertion in `tests/run.sh` to fail if the
   `required` dictionary contains duplicate string paths again.
3. Added this audit report. No files were removed or moved; no managed
   manifest, compatibility profile, dependency, or persisted data changed.

## Before vs After

| Area | Before | After |
| --- | --- | --- |
| Tracked source tree | 700 files; 134 under `scripts/` | Same structure and counts |
| Production source | 40,306 lines | 40,300 lines; only duplicated check-map entries consolidated |
| Test source | 11,952 lines | 11,966 lines; one static regression guard added |
| Code removals | Not yet measured | 0 production modules/functions removed |
| Duplicate document targets | 87 literal entries, only 82 effective keys | 82 unique keys; each target retains all requirements |
| Dependencies | Two direct pinned Analytics packages | Unchanged |
| Historical evidence | 191 PNGs and four certification artifacts | Unchanged and retained |
| Compatibility paths | OpenCode V1/V2, lifecycle and optional integrations | Unchanged; offline suite passed both fixture profiles |
| Regressions found | Duplicate-key bug in release-doc gate | Corrected and guarded by test |

The gain is correctness and maintainability of the release documentation gate,
not a reduction in product architecture or production behavior. No removals
were forced to meet a numeric target.

## Compatibility Assessment

- **OpenCode V1:** the 1.18.18 offline profile fixture passed, including the
  compatibility-floor invocation; V1 policy and config checks passed.
- **OpenCode V2:** the 2.0.0 offline profile fixture passed, and capability
  and plugin contract checks passed. This does not establish live V2 CLI or
  plugin loading.
- **Lifecycle:** offline tests passed the first-install, inspect, doctor,
  capabilities, reforge, upgrade, runtime-update/migration, dry-run, recovery,
  fault-injection, and rollback contracts using temporary HOME/XDG roots.
- **Managed artifacts:** release checker and fixture-based lifecycle checks
  validate shipped inventory and managed-file recovery. No inventory was
  edited by this audit.
- **Analytics and Databricks:** deterministic offline tests passed. No live
  workspace, model, credential, or network provider was contacted.
- **Persistent state and memory:** lifecycle fixtures assert preservation and
  recovery; the audit made no changes to external Anvil state.
- **Physical Parquet certification:** three Analytics tests were skipped
  because system Python lacks the pinned DuckDB and PyArrow packages. They
  require the documented Anvil-managed Analytics environment and were not
  installed for this audit.
- **Browser visual checks:** not executed; no UI or screenshot code was
  changed. Existing screenshot evidence was retained.

## Test Results

| Check | Result | Evidence |
| --- | --- | --- |
| Baseline `make test` before audit changes | PASS | Complete offline suite, including lifecycle and Analytics; 169 Analytics tests with 3 optional physical-dependency skips; 631.95 seconds. |
| Post-change `make test` | PASS | Complete offline suite after the duplicate-key repair and regression guard; 169 Analytics tests with 3 optional physical-dependency skips; 626.12 seconds. |
| `python3 scripts/version_docs.py` | PASS | Reports matching Anvil 2.20.0 release docs and capability/migration references. |
| Duplicate-path AST check | PASS | 82 paths, 82 unique keys; regression guard also runs in `make test`. |
| V1/V2 profile fixture checks | PASS | V1 1.18.18 and V2 2.0.0 offline fixtures. |
| Managed inventory and lifecycle fixture checks | PASS | Covered by release-doc validation and `make test` lifecycle cases. |
| Local Markdown link scan | PASS | 350 links checked; the one intentionally missing image belongs to the `image-not-inspected` fixture. |
| `git diff --check` | PASS | No whitespace errors. |
| Live OpenCode / Databricks / model validation | NOT EXECUTED | Offline audit; no live providers or credentials used. |
| Physical DuckDB/PyArrow certification | NOT EXECUTED | Three tests skipped because pinned packages are absent from system Python. |
| `ruff`, `shellcheck`, `pytest` standalone tools | NOT EXECUTED | Tools are not installed; no dependencies were installed. |

## Remaining Technical Debt

- `scripts/analysis/semantic.py` and the listed high-branch functions are
  sizeable. Refactor only with explicit behavior characterization and focused
  equivalence tests.
- Static reachability cannot fully resolve runtime plugin loading, shell
  sourcing, CLI entrypoints, or user-invoked commands. Modules in those areas
  remain UNKNOWN unless direct consumers or safe removal evidence are found.
- Three physical Parquet/type tests require the pinned dependency environment;
  this audit confirms their skip behavior but not their execution here.
- Live OpenCode V2 plugin loading and live Databricks authentication/workspace
  access remain outside this offline result.
- The Markdown link scan depends on fixture semantics to identify the single
  intentionally absent diagram; it is not a general external-link validator.

## Final Verdict

The Anvil repository is maintainable enough to keep its current modular
boundaries and compatibility paths. No high-confidence dead production code,
unused direct dependency, stale managed artifact, or disposable historical
evidence was found. The safe cleanup was intentionally small: restore five
overwritten release-document requirement lists and guard against their
recurrence. The complete offline suite passed before and after the change,
while live providers and the optional physical Analytics environment remain
explicitly unverified.

## File Change Inventory

| Path | Audit action | Technical reason |
| --- | --- | --- |
| `scripts/version_docs.py` | Modified (already dirty at audit start) | Merge five duplicate keys so earlier release requirements are not silently discarded. |
| `tests/run.sh` | Modified (already dirty at audit start) | Add an AST regression guard for duplicate requirement paths. |
| `docs/anvil-repository-hygiene-v2.20.0.md` | Added | Record baseline, reachability decisions, cleanup, compatibility assessment, metrics, and evidence. |
| Files removed | None | No high-confidence dead component or disposable tracked artifact was confirmed. |
| Files moved | None | Existing boundaries and public paths remain valid. |
