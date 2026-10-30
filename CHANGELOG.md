# Changelog

## [2.11.0] - 2026-10-30 (candidate; release gate pending)

- Extended renderer-independent artifact contracts with OBSERVED/CALCULATED/INFERRED and SCENARIO epistemic states, counter-evidence, alternatives, materiality, decision context, and selective appendix placement.
- Added financial, technical-leadership and engineering audience lenses while preserving executive, technical and mixed policies; numeric wording adapts to audience without changing stored values.
- Added semantic visual intent for relationship, form, evidence focus, prominence, color roles and information-bearing motion storyboards. Markdown preserves motion intent and reports its static fallback.
- Added an advisory editorial critic for generic assertions, repetitive/card-heavy composition, undifferentiated prominence, semantic-form mismatch, color competition, decorative motion, precision theater, exhaustive inputs, and generic corporate prose.
- Strengthened SVG QA to reject measurable off-viewBox geometry and out-of-canvas routes; existing node collision, containment and unrelated-node crossing checks remain.
- Added five offline evaluation fixtures spanning finance, architecture, Spark performance, process motion and unrelated business communication.
- No runtime, persistent user-data or external dependency migration is required. The Anvil presentation benchmark named in the implementation specification is not present in this repository; this candidate is **NOT RELEASE READY** until that comparison is completed.
- Extended source-profile migration support to five prior minor releases to keep 2.6.x installations upgradeable.

## [2.10.0] - 2026-10-27

- Added task-local adaptive engineering depth: request/project size no longer forces long-horizon state, and requirements, architecture, work, and domain knowledge activate only when the current risk or uncertainty warrants them.
- Reduced the always-loaded engineering kernel by 592 bytes and made escalation/de-escalation explicit without adding modes, agents, model routing, dependencies, or runtime requirements.
- Made invariant evidence invalidation path/pattern scoped and added milestone-scoped architecture checkpoints that reuse valid PASS evidence while preserving the full audit path.
- Preserved schema-1 task state, atomic recovery, stale detection, requirements coverage, architecture completion gates, interruption safety, OpenCode 1/2 support and lifecycle semantics.
- Added 18 paired activation cases and measured deterministic replay deltas: ingestion architecture evaluations 20→4 and scheduler 8→2, with required coverage/invariants intact. Live-model tool/context/latency/token behavior remains unmeasured.
- Extended the automatic source migration window to four prior minor releases to retain 2.6.x compatibility. No runtime or user-data migration is required.

## [2.9.0] - 2026-10-27

- Added progressively activated engineering continuity with separate requirements, architecture and work models, explicit provenance, dependency graphs and hierarchical completion gates.
- Added private checksummed atomic task state, revision/concurrency protection, bounded compaction recovery, stale-evidence invalidation, safe partial-work reconciliation and selective replanning.
- Added command-backed verification, explicit semantic judgments, scoped architecture invariants, required-scope authorization and failure-aware checks without automatic resume execution.
- Added lazy system-design guidance and focused references to the existing Spark skill, preserving small-task cost, one-agent/model/runtime independence, memory and existing integrations.
- Added offline ingestion/scheduler replays, crash/concurrency/compaction regressions, technical rubrics and optional model-evaluation profiles. Native OpenCode 1.19.3/2.0.31 candidate checks passed; real-model performance remains unmeasured.
- Extended supported source migration to three prior minors to retain the existing 2.6 upgrade path. No runtime or existing memory/state migration is required.

Release notes for user-visible Anvil changes. See [version history](docs/versions/README.md) and [release discipline](docs/RELEASING.md).

## [2.8.0] - 2026-10-25

### Added

- Added semantic lifecycle states for supported upgrades, required migration, unsupported downgrade/source windows, degraded installs, corruption, and interrupted-operation recovery.
- Added a checksummed managed-file manifest bound to installation metadata. Upgrades now show a source-to-target file plan, preserve user-owned global files, and stop before mutation when a user file collides with a newly managed path.
- Added atomic configuration staging and a durable transaction journal. A verified snapshot is restored automatically before a retry after a hard interruption; `inspect` remains read-only and reports `RECOVERY_REQUIRED`.
- Added source compatibility for the current and previous two Anvil minor releases, semver ordering, and downgrade protection in both upgrade and reforge. Runtime-only updates keep the installed Anvil release and its exact configuration; explicit runtime-major migration requires current Anvil.

### Fixed

- A prior-release profile is now validated against its own managed inventory before target files are planned, so target-only additions no longer classify an otherwise valid source install as corrupted.
- Reforge preserves user CLI/TUI preferences and user-owned files while rebuilding Anvil-owned files; modified or missing managed files can be repaired through explicit reforge when the ownership manifest remains trustworthy.
- Rollback to a prior Anvil release is reported as migration-required when the checkout is newer, rather than as corruption.
- Upgrade preflight now detects a read-only configuration parent before stopping OpenCode or creating a snapshot/journal, so a blocked atomic swap leaves the installation untouched.
- Runtime discovery now preserves executable paths containing spaces during lifecycle output parsing; config rebuilds also retain disabled user-owned inline agents across OpenCode 1/2 transitions.

### Compatibility and validation

- Existing 2.6.x and 2.7.x profiles migrate with `make upgrade`; Anvil-only upgrades preserve the exact supported OpenCode executable, data, and state. OpenCode 1.x and 2.x remain supported.
- New managed manifests are stored in the OpenCode global config and their SHA-256 is recorded in installation metadata. No Databricks credentials, readiness state, or memory schema are migrated.
- `make test` covers version skew, extras/collisions, dry-run immutability, interrupted transactions, rollback, and runtime preservation using isolated HOME/XDG roots and offline fixtures.

## [2.7.1] - 2026-10-25

### Fixed

- Anvil 2.7.1 now accepts supported OpenCode 1 and 2 configs from Anvil 2.6.x during inspect, doctor, reforge, and upgrade, even when they do not yet grant the newly added communication skill.
- Kept strict skill-set validation for configs generated by the current release, while installed older profiles are audited for supported structure, safe permissions, and known skills before upgrade.
- Added end-to-end regressions for Anvil 2.6.1 to 2.7.1 upgrades on both OpenCode runtime generations, including first-use inspection and doctor status.

### Compatibility

- No data migration or OpenCode runtime change is required. `make upgrade` preserves the validated OpenCode executable and version.
- Existing 2.7.0 installations remain compatible; the patch repairs only lifecycle recognition of supported prior-release configs.

## [2.7.0] - 2026-10-25

### Added

- Added model-agnostic Communication & Artifact Intelligence: a lazy skill and `/review` command backed by bounded, runtime-independent evidence, quantitative, planning, rendering, and review contracts.
- Added deterministic Decimal analysis for absolute/relative changes, percentage points, zero/negative baselines, normalization, distributions, outliers, exclusions, and projections with explicit assumptions.
- Added provenance-checked Markdown reports and exact slide outlines, plus a renderer-independent architecture model with accessible SVG output and layout collision rejection.
- Added bounded local text/CSV/JSON/OOXML input extraction, optional `pdftotext` support, and communication capability reporting in `make capabilities`.
- Added offline regression coverage for arithmetic, evidence, audiences, constraints, local inputs, Markdown, SVG, and reviewer failure cases.

### Compatibility and scope

- OpenCode 1.x and 2.x compatibility remains unchanged. No OpenCode runtime upgrade, model pin, MCP server, Python dependency, persistent schema migration, automatic memory write, or default Databricks query was added.
- Markdown and SVG are the available artifact renderers. Binary PPTX/DOCX/PDF, quantitative charts, OCR, and animation remain unavailable.
- Semantic truth remains a model/human review responsibility; structural and mathematical checks are not reported as factual verification.

## [2.6.2] - 2026-10-25

### Fixed

- Added a shared Anvil lifecycle evaluator for repository-only, partial, installed, ready, degraded, and corrupted managed state. Inspect and doctor report that state; upgrade, runtime update/migration, and rollback use shared lifecycle preconditions.
- Fresh rollback now explains when no verified snapshot exists and how to create one. Doctor no longer marks an unconfigured Databricks integration stale, and it preserves status-probe diagnostics.
- `make test` now isolates HOME, all XDG roots, PATH, Python user-site behavior, and Databricks selectors; external network attempts fail the offline suite.
- Databricks SDK setup now distinguishes a missing pip from Python/venv/download blockers, preserves the venv Python invocation path through discovery and persistence, and shows the actual SDK blocker in human output.
- SDK worker calls now construct an explicit Config with the selected Anvil profile, owned config file and bounded timeouts. Safe allowlisted phase diagnostics survive the worker, adapter, readiness result and presenter.
- Unexpected Python command failures now receive a sanitized human-facing error boundary, with stack frames available through `DEBUG=1`.

### Documentation and validation

- Added the public Make command contract matrix, lifecycle definitions, fresh-install journey, and root-cause audit.
- No Databricks readiness state or persisted provider schema changed; OpenCode 1.x and 2.x runtime support and Anvil-only upgrade independence remain intact.
- The offline release suite covers pre/post-reforge public command matrices, partial/corrupt states, missing pip, venv symlink identity, SDK worker diagnostics, and rollback. It uses local fixtures and does not require Databricks, Azure, or external network access.

### Release choice

PATCH: this release corrects command and bootstrap reliability without adding product capabilities or changing the persisted Databricks state schema.

## [2.6.1] - 2026-10-16

### Fixed

- Explicit setup now prepares the isolated SDK after a provider-specific Databricks CLI health failure, then reruns identity and core capability probes through the production resolver. Shared authentication, workspace-network, permission, argument, and unknown failures still stop without provider roulette.
- SDK operations now execute through the same validated absolute Python path discovered from persisted Anvil provider state, including in a clean new process.
- Cluster and warehouse probes now use the dedicated metadata-list timeout class; the current 45-second budget is unchanged.
- Setup output no longer says the SDK fallback is “not needed” when it is absent or blocked.

### Release choice and validation

This is a PATCH release. It corrects fallback provisioning and provider-path reuse without changing the command surface or persisted schema-3 readiness contract. Offline regressions reproduce the installed-CLI timeout, exercise successful and blocked SDK fallback, preserve shared-failure stopping, verify clean-process SDK use, and check metadata timeout routing. No live Databricks, Azure, or network smoke test was run.

## [2.6.0] - 2026-10-16

### Added

- One Databricks readiness state machine for setup, status, and doctor, with explicit configuration, authentication, workspace, provider, and core-capability evidence.
- Cross-session production-path validation for the current-user, cluster-list, and warehouse-list operations before a new profile can become active and READY.
- Provider error scopes and deterministic CLI-to-SDK fallback only for provider-specific failures; shared authentication, network, and permission failures retain their root cause.
- Operation-specific timeout policies, bounded subprocess output, process-group cleanup, fresh readiness timestamps, and a 15-minute local readiness freshness window.
- A stable JSON command grammar documented by the Databricks skill and parser contract tests.

### Changed

- Databricks provider state moves to schema 3 and validates that READY includes fresh identity/provider evidence and verified clusters/warehouses checks; legacy state migrates lazily without rewriting credentials.
- `make doctor` performs the same read-only Databricks readiness probe as `databricks.py status` when an Anvil profile exists. With no profile, it remains local and reports NOT_CONFIGURED.
- `make capabilities` keeps local-only behavior and distinguishes Supported, Available, and Verified, marking cached evidence stale after its freshness window.
- Provider status and operation failures now retain capability-specific blockers instead of converting every failure into an authentication or network diagnosis.

### Fixed

- Setup can no longer report READY from profile existence, auth strategy, or current-user identity alone when a fresh session cannot list the mandatory core resources.
- A timed-out provider process and its child processes are terminated, and failed candidate configuration is not promoted.
- Empty cluster and warehouse lists count as verified successful results; a permission failure on one list does not invalidate authentication or another working capability.
- SDK calls explicitly load the Anvil-owned config file and profile, so ambient Databricks config selectors cannot hijack a clean session.

### Release choice and validation

This is a MINOR release because Databricks readiness semantics and persisted state schema are made explicit while existing commands remain compatible and legacy metadata is migrated lazily. Offline regression coverage includes clean-process revalidation, false-READY prevention, process cleanup, empty results, shared-failure propagation, selective fallback, permission-scoped partial readiness, and the documented command grammar. No live Databricks workspace or cloud login was used.

## [2.5.0] - 2026-10-16

### Added

- Anvil-owned Databricks config at `${XDG_CONFIG_HOME:-$HOME/.config}/anvil/databricks/databrickscfg` with predictable `anvil-dev`, `anvil-staging`, and `anvil-prod` profiles.
- Clean-slate workspace onboarding, cloud/topology-based authentication selection, Azure CLI session reuse, Azure local interactive login, and remote Azure device-code authentication.
- Atomic config activation, restrictive permissions, a validated `RESET=1` flow with a private rollback copy, and profile ownership metadata without credential values.
- Isolation of inherited `DATABRICKS_*` overrides from Anvil CLI/SDK child processes and separate doctor reporting for external profiles.

### Changed

- Databricks setup no longer adopts or repairs arbitrary user profiles. Old selected external profiles are ignored; their saved workspace host may be offered for explicit confirmation when creating an Anvil profile.
- Authentication selection happens only after workspace, cloud, topology and Anvil profile preparation. The same Anvil config/profile is used by the CLI and SDK.
- Doctor and capabilities identify Anvil configuration separately from external profiles; external profiles are counted for diagnostics but are never used.

### Fixed

- An expired external U2M profile no longer forces Anvil into repeated browser reauthentication.
- Remote/hybrid Azure sessions no longer default to Databricks loopback OAuth when Azure CLI device code is available.
- External token/host/profile environment variables cannot silently override Anvil child operations or appear in diagnostics.

### Preserved

- CLI/SDK capability routing and specialized SQL Connector, Databricks Connect, and VS Code-assisted paths.
- OpenCode 1 and 2 compatibility, safe runtime upgrade behavior, offline tests, no MCP requirement, and secret-free Anvil state.

### Release choice and validation

This is a MINOR release: it changes Databricks onboarding compatibly while preserving the command surface and provider state format. Mandatory tests use local CLI, Azure CLI, SDK, and runtime fakes; no live Databricks workspace or cloud login was used.

## [2.4.0] - 2026-10-16

### Added

- Safe OpenCode quiescing for `make upgrade`: read-only active-process reporting in dry-run, backup preflight, ancestry protection, a cancellable countdown, SIGTERM-first shutdown, bounded SIGKILL fallback, and a final quiescence check before backup.
- Human-first Databricks setup, doctor, and capability presenters with explicit JSON and verbose diagnostics modes.
- Local, VS Code Remote, SSH, container, WSL, and headless topology detection with centralized Databricks authentication strategy selection.
- Official Databricks CLI OAuth U2M orchestration on local interactive terminals, and Azure CLI device-code authentication through the Python SDK for Azure workspaces in supported remote environments.
- Bounded authentication watchdogs that stream official CLI progress and classify timeout and cancellation outcomes.

### Changed

- `make upgrade DRY_RUN=1` reports active OpenCode processes without stopping them or changing live state.
- A real Anvil upgrade validates backup readiness first, stops only the exact validated runtime using the configured OpenCode data paths, then creates a consistent snapshot. OpenCode is left stopped for the user to start normally.
- `make databricks-setup` owns supported installation, authentication, workspace identity validation, and safe provider-state updates; users no longer need an Anvil-internal CLI path.
- Public Databricks command output now emphasizes readiness, warnings, and next actions. `OUTPUT=json` and `VERBOSE=1` remain available.

### Preserved

- OpenCode 1.x and 2.x compatibility, runtime independence, per-capability Databricks provider fallback, no-secret Anvil state, no IDE credential scraping, and the no-silent-remote-mutation boundary.

### Release choice

This is a MINOR release because it adds backward-compatible user-facing setup, authentication selection, and command-presentation capabilities while retaining the existing command surface and persisted metadata compatibility.

### Validation scope

- Mandatory checks use local process, CLI, SDK, and Azure CLI fakes; no real Databricks workspace, cloud login, browser, VS Code marketplace, or external LLM is contacted.

## [2.3.1] - 2026-10-16

### Fixed

- Decoupled `make upgrade` from OpenCode release discovery and installation. Anvil can now be upgraded offline while preserving the exact validated OpenCode executable and version.
- Added `make update-runtime` for explicit same-major OpenCode updates; `make migrate-runtime OPENCODE_MAJOR=N` remains the explicit major migration path.
- Made `make reforge` reuse an existing healthy supported runtime, while clean first-use provisioning remains an explicit network-capable path.
- Made inspect, doctor, and capabilities report local Databricks provider state without querying workspace identity, compute, warehouses, or system tables.
- Added runtime discovery state with validation, PATH visibility reporting, scope-aware backups/rollback, offline lifecycle guards, and a repository hygiene check for the retired standalone identifier.

### Release choice

This is a patch release because it corrects lifecycle coupling and local status behavior without changing Anvil's supported feature set or persistent user-data formats.

## [2.3.0] - 2026-10-16

### Added

- Capability-based Databricks provider resolution with the official CLI, isolated Python SDK, optional SQL Connector, Databricks Connect detection, and VS Code assisted status.
- Explicit `make databricks-setup` CLI installation attempt from official GitHub releases with SHA-256 verification and a user-local, no-elevation install path.
- Anvil-owned isolated SDK environment and Unified Authentication profile reuse when CLI setup is blocked or unavailable.
- PATH-resilient CLI discovery, atomic schema-versioned provider metadata, provider-aware doctor/capabilities, and `make databricks-setup DRY_RUN=1`.
- Offline provider tests for install outcomes, PATH changes, SDK routing, VS Code detection, state security, setup idempotency, and dry-run behavior.

### Changed

- Databricks capability is no longer hard-coupled to the CLI; the CLI remains preferred when healthy, with per-capability SDK fallback.
- `make reforge` and `make upgrade` no longer prompt to configure Databricks or perform Databricks network/install work.
- CLI or SDK installation blockage is reported independently from the Anvil lifecycle and other available Databricks providers.

### Preserved

- OpenCode 1.x and 2.x compatibility, existing Anvil 2.2 execution bounds, profile non-switching, secret-free Anvil state, and the no-silent-remote-mutation guardrails.
- One model-neutral Anvil agent, no mandatory MCP, and no model routing.

### Limitations

- The mandatory test suite uses local doubles and does not contact a Databricks workspace or install real providers.
- CLI and SDK installation require access to official GitHub/PyPI sources when `make databricks-setup` is explicitly run. VS Code is assisted; Anvil does not automate the IDE.

## [2.2.0] - 2026-10-16

### Added

- Optional, runtime-independent Databricks capability through the official CLI and REST APIs, including cross-session profile selection, Python Command Execution, bounded SQL Statement Execution, live system-catalog discovery, and setup/doctor/capabilities integration.
- Dated system-table catalog snapshot, focused references, seven aggregate query recipes, and deterministic FinOps analysis with an Evidence Confidence Score.
- Offline Databricks CLI and OpenCode runtime fixtures. `make test` no longer resolves or downloads external runtime candidates.

### Changed

- Condensed the global harness and clarified execution evidence, recovery, validation, scope, Databricks mutation, secret, and FinOps guardrails.
- Skill descriptions now explain when each skill should and should not be used.
- `make capabilities` reports runtime and live Databricks state in one text or JSON document.

### Preserved

- One model-neutral primary agent, explicit-only durable memory, no default MCP requirement, and support for OpenCode 1.x and 2.x without implicit major migration.
- Databricks credentials remain under CLI-managed authentication; Anvil stores only the selected profile and workspace host.

### Limitations

- Mandatory validation is fully offline and does not claim a live Databricks or OpenCode service connection was tested.
- Databricks requires CLI 1.0.0 or newer, valid workspace permissions, a running classic all-purpose cluster for remote Python, and a running SQL warehouse for SQL execution.

## [2.1.0] - 2026-10-16

### Added

- OpenCode 1 and 2 runtime adapters with a checked-in runtime policy and machine-readable capabilities.
- `make capabilities`, `make migrate-runtime OPENCODE_MAJOR=N`, and rehearsed `DRY_RUN=1` support for product upgrades and explicit runtime migration.
- OpenCode 1 config generation, stable release resolution, SHA-256 artifact verification, native text stats, and file-based search/knowledge fallbacks.
- Recall freshness warnings for memories linked to changed or missing registered sources.

### Changed

- `make upgrade` now upgrades Anvil while preserving the installed OpenCode major. `make reforge` follows the approved policy on first install and preserves an existing runtime major when rebuilding.
- Runtime profile rendering, compatibility checks, capabilities, stats, and doctor behavior now use the central runtime adapter.

### Fixed

- Anvil's product release is no longer coupled to OpenCode 2. The complete Anvil 2.1 command, skill, Markdown memory, `/distill`, and source-registry workflow is available on supported OpenCode 1.x and 2.x runtimes, with native-only features gated by capability.
- `make stats` uses OpenCode 1's native text report and continues to return a non-error notice when stats cannot be obtained.
- OpenCode major migration can no longer occur implicitly during `make upgrade`.

### Preserved

- One model-agnostic primary agent, no model pinning, no default MCP servers, Markdown memory, and explicit-only persistent memory writes.
- OpenCode data and state remain opaque files in rehearsal, backup, and rollback.

## [0.1.0] - 2026-10-12 (V1 repository baseline; no release tag recorded)

This entry records the implemented V1 repository baseline from the initial Anvil history, not a separately verified public release.

### Added

- One model-neutral Anvil primary agent with compact global instructions, default-deny tool permissions, and five allowlisted skills.
- Explicit `/remember` and `/recall` commands backed by human-readable Markdown memory.
- Read-only `make inspect`, isolated `make test`, clean `make reforge`, `make doctor`, and config/installer `make rollback` workflows.
- Checksummed backups of the managed global config and OpenCode installer directory.

### Preserved limitations

- V1 did not provide a V1-to-V2 migration rehearsal or snapshot OpenCode data/state for a runtime-generation rollback.
- V1 had no `/distill`, source registry, Knowledge Reference, OpenCode 2 plugin, native stats target, model router, vector index, or automatic memory extraction.

## [2.0.0] - 2026-10-13

### Added

- Native OpenCode 2 configuration with a model-neutral Anvil primary agent, explicit permission rules, and the existing five skills.
- Safe `make upgrade` with exact stable candidate resolution, isolated V1 migration rehearsal, complete config/runtime/data/state backup, postflight doctor, and automatic rollback.
- Minimal local `anvil-core` plugin exposing bounded, read-only `anvil_memory_search`.
- `/distill`, a source-driven knowledge workflow with explicit provenance, source hash registry, drift checks, reconciliation guidance, and unchanged-source idempotency.
- Native `anvil-knowledge` Reference, `make stats`, expanded V2 doctor, and formal version/migration documentation.
- Backward-compatible memory metadata for aliases, status, evidence, source hashes, sections, and line ranges.

### Changed

- OpenCode V2 uses its native plural `agents` and `plugins` config keys, ordered permissions, references, and compaction settings.
- `make rollback` restores the full saved OpenCode config, installer runtime, data, and state while retaining and separately archiving current Anvil memory.
- `make reforge` remains a clean rebuild path; `make upgrade` is the normal forward migration/update path.

### Preserved

- One model-neutral Anvil primary agent, no model routing, subagents denied, and zero MCP servers by default.
- `/remember`, `/recall`, explicit-only persistent memory writes, V1 Markdown compatibility, and the five V1 skills.

### Compatibility

- V1 Markdown memory remains readable without rewriting entries.
- Provider definitions and CLI/TUI settings are staged through the V1-to-V2 migration path.
- OpenCode databases are copied and restored as opaque files; Anvil does not edit their schema.
