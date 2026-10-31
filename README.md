# Anvil

> **Anvil — A lean, model-agnostic OpenCode harness designed to maximize reliable task completion while minimizing unnecessary context and token usage.**
>
> **Better harness. Better execution.**

Anvil 2.15.0 hardens analytical semantics: it separates observations, entities, events, keys, dimensions and measures; supports bounded composite grain inference; and adds an adversarial semantic certification suite. Deterministic semantic certification is **READY_FOR_MODEL_EVALUATION**. Model-backed L3–L5 quality and release approval remain pending.

```bash
# First installation
make reforge
make doctor

# Upgrade Anvil only; preserve the exact installed OpenCode runtime
git pull
make test
make upgrade DRY_RUN=1
make upgrade

# Offline analytical evaluation; model-backed evaluation is optional
make eval-analytical
make eval-analytical-semantic
make eval-analytical-model MODEL=provider/model RUNS=3

# Configure Databricks; default output guides setup in plain language
make databricks-setup

# Preview local provider/auth strategy without changes or network access
make databricks-setup DRY_RUN=1

# Request machine-readable results or provider diagnostics
make databricks-setup OUTPUT=json
make databricks-setup VERBOSE=1

# Explicit same-major runtime update
make update-runtime DRY_RUN=1
make update-runtime

# Explicitly migrate runtime major when approved
make migrate-runtime OPENCODE_MAJOR=2 DRY_RUN=1
make migrate-runtime OPENCODE_MAJOR=2
```

Use `make inspect` to review the current setup before changing it. Use `make capabilities` to see local runtime features and Databricks Supported / Available / Verified status; it does not contact a workspace. `make doctor` revalidates a configured Databricks profile with read-only identity, cluster-list, and warehouse-list calls. With no Anvil profile, doctor remains local and reports Databricks as not configured. Use `make rollback` to restore the latest verified snapshot according to its recorded scope. `make upgrade` upgrades Anvil without changing the OpenCode executable/version. Use `make update-runtime` for an explicit same-major runtime update and `make migrate-runtime OPENCODE_MAJOR=N` for an explicit major change.

**Anvil — A lean, model-agnostic OpenCode harness designed to maximize reliable task completion while minimizing unnecessary context and token usage.**

For a shorter headline: **Anvil — Better harness. Better execution.**

Anvil is a lean, model-agnostic harness and lifecycle layer for OpenCode 1.x and 2.x. Anvil's release version is independent from the OpenCode major. OpenCode owns model/provider authentication, sessions, its native tools, and runtime state. Anvil supplies a focused behavioral environment: compact instructions, one primary agent, a small set of skills, explicit file memory, evidence-driven workflows, safe upgrade and recovery operations, optional Databricks integration, and communication/artifact intelligence.

## Why Anvil?

Anvil means a blacksmith's anvil: the stable base on which material is shaped, refined, and made useful. The anvil is not the material and does not supply all the energy; it provides a dependable surface for the work. **Forge better performance from every model.**

Anvil plays that role for language models. It does not create or route models. It gives the selected model disciplined context, useful skills and memory, clear execution rules, and verification. Models may change; the harness remains the foundation.

```text
Luna / Terra / Sol / Astra / Sonnet / other models
                         │
                         ▼
                   Anvil harness
       context · skills · memory · tools · rules
                         │
                         ▼
              reliable, verified execution
```

## Install and upgrade

Prerequisites: Linux or macOS, Bash, Python 3.11+, and `tar`. A fresh install may need access to the official OpenCode release source. Existing supported runtimes can be reused without downloading OpenCode. Windows users can run Anvil under WSL. Databricks is optional and does not affect the rest of Anvil.

`make inspect` reads local runtime and provider state without changing it, including whether Anvil is not installed, partially installed, ready, degraded, or corrupted. `make test` validates both runtime profiles, memory behavior, lifecycle, rollback, failure recovery, Databricks providers, the offline analytical evaluation harness, and fresh HOME/XDG command journeys with local fixtures. The suite isolates all user/XDG roots, constrains `PATH`, and blocks external network connections in lifecycle checks while allowing loopback for isolated runtime fixtures.

`make eval-analytical` runs versioned synthetic fixtures, deterministic L1/L2 scoring, communication trap tests, FAST/STANDARD/DEEP performance measurements, and an isolated 2.13 comparison when available. `make eval-analytical-semantic` adds the 24-case adversarial semantic certification and compares candidate performance with the immutable 2.14 baseline. `make eval-analytical-model MODEL=provider/model RUNS=3` uses the installed Anvil agent through OpenCode for blind repeated runs; it may use a configured model provider. Artifacts are stored privately under `${XDG_STATE_HOME:-~/.local/state}/anvil/evaluations/`. Read the [analytical evaluation guide](docs/analytical-intelligence-evaluation.md) for human review, baseline freezing and private-case support.

For a first installation, run `make inspect` to review the environment, then `make reforge` and `make doctor`. Before reforge, inventory commands remain useful; commands that require an installed Anvil report that prerequisite and point to reforge. Rollback reports when no verified snapshot exists. If a healthy supported OpenCode runtime is already installed, reforge rebuilds Anvil around that exact executable without contacting a release service. If no runtime exists, reforge provisions the version selected by `config/runtime-policy.json` and may need network access.

`make upgrade` upgrades Anvil only. It uses the local validated OpenCode executable for rehearsal and preserves its exact path, bytes, and version. `make upgrade DRY_RUN=1` works offline, reports active OpenCode processes, and does not signal them or change live state. A real upgrade checks the backup destination first, warns before stopping only the exact runtime processes using the configured data paths, prefers graceful shutdown, and uses SIGKILL only after the bounded wait. Start OpenCode normally when the upgrade finishes. Use `make update-runtime` for an explicit same-major OpenCode update. Use `make migrate-runtime OPENCODE_MAJOR=N` for an explicit major migration.

Use `make migrate-runtime OPENCODE_MAJOR=2` only when a move to OpenCode 2 is explicitly approved. The command requires the requested major, rehearses against copied user state, backs up the current runtime/config/data/state, and rolls back on a post-mutation failure. `make migrate-runtime OPENCODE_MAJOR=1` provides the reverse migration path when OpenCode 1 is approved and supported.

`make reforge` rebuilds Anvil config with an existing healthy supported runtime without resolving or replacing OpenCode. If no OpenCode runtime exists, reforge may access the official release source to provision the policy-selected first runtime. An existing unhealthy or unsupported runtime is reported for explicit repair/update rather than silently replaced.

## Databricks

Databricks is optional. Normal `make reforge` and `make upgrade` do not install Databricks tools or contact a workspace. Run `make databricks-setup` when you explicitly want Anvil to configure Databricks. Anvil creates its own profile, such as `anvil-dev`, in `${XDG_CONFIG_HOME:-~/.config}/anvil/databricks/databrickscfg`. Existing user profiles are left untouched and are not adopted. The CLI is installed under Anvil's user-local data directory with SHA-256 verification; an isolated Python SDK fallback is prepared when needed.

Use `make databricks-setup DRY_RUN=1` to inspect the proposed actions and local auth/provider discovery without network access or state changes. Setup asks for a workspace URL and environment label, then selects authentication from workspace cloud and terminal topology. It reuses a valid Azure CLI session, supports Azure device-code login remotely and Azure interactive login locally, and uses Databricks OAuth U2M where appropriate. The CLI and SDK use the same Anvil-owned config. External `DATABRICKS_*` overrides are removed from Anvil child processes; Anvil reports variable names without revealing their values. Use `make databricks-setup RESET=1` to replace only Anvil-owned config after validation; a private backup is retained. Doctor reports external profiles separately and never uses them. The optional SQL Connector and Databricks Connect remain specialized providers; VS Code is assisted only, never automated through private IDE APIs.

Human-readable output is the default for setup, doctor, and capabilities. Use `make databricks-setup OUTPUT=json` for the full structured result or `VERBOSE=1` for local provider diagnostics. Provider installation and workspace authentication happen only after explicitly running `make databricks-setup`.

Anvil discovers a previously verified CLI by its absolute path even if a later shell has a different `PATH`. `make doctor` reports live provider health and its last validation; `make capabilities` reports local inventory and cached capability evidence, which becomes stale after 15 minutes. Databricks setup reaches READY only after a production-path current-user check and verified cluster and warehouse list calls. Empty lists are valid; setup does not need running compute or SQL access. The wrapper keeps bounded Python/SQL results, system-table read-only behavior, and no-silent-mutation rules. See [Databricks setup, readiness, and provider docs](docs/databricks/README.md).

If the installed CLI times out on a provider-specific read-only health check, explicit `make databricks-setup` can prepare Anvil's isolated SDK fallback and repeat validation. Shared authentication, workspace-network, permission, and argument failures do not trigger provider cycling. The 45-second metadata-list timeout is unchanged; see the [provider fallback and timeout policy](docs/databricks/readiness.md).

Backups live under `$XDG_DATA_HOME/anvil/backups/` (default `~/.local/share/anvil/backups/`). Each snapshot records its scope. An Anvil-only backup restores config and Anvil metadata while preserving OpenCode executable/data/state; a runtime backup also includes OpenCode config, executable, data, and state. Runtime archives may contain sensitive session or authentication state.

## Memory and knowledge

Anvil keeps Markdown memory under `$XDG_DATA_HOME/anvil/memory/`. Existing V1 entries remain readable without rewriting. Search is lexical, accent-insensitive, bounded, and can use aliases for multilingual retrieval. Memory is not a database, vector index, or automatic transcript store.

- `/remember` saves a specific fact or decision the user explicitly wants retained.
- `/recall` searches existing entries and returns a small relevant set.
- `/distill` turns explicitly named documents, pasted content, or evidence into a small set of reusable memories with provenance. It checks duplicates, preserves historical or conflicting claims, and detects unchanged sources so they are not reprocessed unnecessarily.

Persistent writes require explicit `/remember`, `/distill`, or direct user intent. Knowledge documents remain the source material; memory contains compact derived claims. The `anvil-knowledge` OpenCode Reference points to the separate `$XDG_DATA_HOME/anvil/knowledge/` directory.

On OpenCode 2, Anvil's local `anvil-core` plugin exposes one bounded, read-only `anvil_memory_search` tool. OpenCode 1 uses the same Python lexical search helper through the `/recall` and memory skill workflow. Neither adapter rewrites prompts, routes models, or writes memories implicitly. Native `anvil-knowledge` References are available on OpenCode 2; OpenCode 1 accesses explicitly named knowledge files through normal file reads.

## Models, agents, and skills

Anvil configures one model-neutral `anvil` primary agent. No model is pinned; select models through OpenCode as usual. The four built-in user-facing agents are disabled, subagents are denied, and no MCP servers are enabled by default. Allowlisted skills cover memory, Spark performance, Delta Lake, Databricks, data ingestion, communication artifacts, engineering continuity and system design.

## Adaptive engineering depth

Anvil judges the requested change, not the size or complexity of its repository. A local fix stays in the direct loop even when a long project is active; unrelated Work Model state remains dormant. Anvil expands into the relevant requirement, architecture, state, or domain evidence when uncertainty or meaningful risk changes the next safe action, then narrows again when that decision is resolved. No `/fast`, `/deep`, or other user mode is required.

For genuine multi-milestone work, `anvil-engineering` retains separate Requirements, Architecture, and Work models, crash-safe resume, and completion gates. Architecture checks reuse valid evidence and run only for the affected boundary at a completed milestone. `anvil-system-design` and Spark internals remain lazy. See [adaptive engineering](docs/adaptive-engineering.md), [the engineering guide](docs/engineering.md), and [evaluation evidence and limitations](docs/engineering-evaluation.md).

## Communication and artifacts

Use natural language with the Anvil agent, for example: “Analyze these named files and prepare an executive report,” “Prepare exactly five slides from this evidence,” or “Review this Markdown artifact against its plan.” The `anvil-communication` skill guides source inventory, targeted extraction, evidence provenance, quantitative interpretation, six audience lenses, editorial selection, semantic visual intent, and review. `/review PATH` is the generic command for reviewing an explicitly named artifact.

The local core is also available at `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/artifacts.py` after installation. It provides bounded `discover` and `extract`, deterministic `quantify`, hard-constraint checks, `critique PLAN.json`, Markdown report/slide-outline materialization, semantic architecture-to-SVG rendering, and deterministic review. `make capabilities` lists its supported inputs and renderers.

Supported source extraction includes Markdown/text, CSV/TSV, JSON/JSONC text, common source/config files, and text/value extraction from DOCX/PPTX/XLSX. PDF text extraction is optional and requires `pdftotext`. Embedded images, charts, speaker notes, scanned pages, workbook formulas, and media are not interpreted. Available artifact outputs are Markdown and accessible architecture SVG; binary PPTX/DOCX/PDF, quantitative chart rendering, OCR, and animation are not available in this release.

Numerical values remain tied to evidence IDs. The deterministic core separates absolute change, relative change, and percentage-point change; preserves missing values and zero/negative baseline limitations; supports measured normalization and distribution summaries; and keeps estimates, scenarios, and annualized projections labeled. It recalculates derived values before materialization. Executive, financial, technical-leadership, engineering, technical, and mixed audiences receive different emphasis and presentation detail without altering the underlying measurements. Structural and arithmetic PASS results do not prove that a narrative claim is true; semantic review remains required.

## Recovery and status

`make rollback` restores the latest verified snapshot by scope. An Anvil-only snapshot restores Anvil config/metadata and preserves the OpenCode executable/data/state; a runtime snapshot restores those runtime files as well. Current Anvil Markdown memory is archived separately before rollback and remains portable.

`make doctor` checks the shared lifecycle state as well as the selected config adapter and agent policy, commands and skills, runtime support, memory, knowledge access, source registry, migration metadata, and visible workspace overrides. It reports `HEALTHY`, `WARNING`, `PARTIALLY INSTALLED`, `BROKEN`, or `NOT INSTALLED`; exit codes are `0` for a completed healthy/informational check, `2` for warnings or partial installs, and `1` for corrupted state or failed checks. A supported installation on an older Anvil release is reported as `UPGRADE AVAILABLE` with exit code `0`. `make stats` uses OpenCode 2's structured JSON report or OpenCode 1's native text report; unavailable metrics are reported without invented values.

## Version history

See the [Anvil 2.15.0 candidate notes](docs/versions/v2.15.0.md), [2.14-to-2.15 migration guide](docs/migrations/v2.14.0-to-v2.15.0.md), [Anvil 2.14.0 candidate notes](docs/versions/v2.14.0.md), [2.13-to-2.14 migration guide](docs/migrations/v2.13.0-to-v2.14.0.md), [analytical intelligence guide](docs/analytical-intelligence.md), [analytical evaluation guide](docs/analytical-intelligence-evaluation.md), [architecture realignment assessment](docs/analytical-intelligence-realignment-v2.14.0.md), [engineering report](docs/analytical-intelligence-report-v2.14.0.md), [system map](docs/system-map.md), [full-system quality audit](docs/quality-audit.md), [communication and artifact architecture](docs/communication-artifact-intelligence.md), [public command contracts](docs/command-contracts.md), [runtime capability matrix](docs/versions/README.md), [Databricks readiness contract](docs/databricks/readiness.md), [runtime compatibility](docs/runtime-compatibility.md), and the [changelog](CHANGELOG.md).
