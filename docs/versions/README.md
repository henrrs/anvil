# Anvil version capability matrix

Anvil's product version and OpenCode runtime generation are independent. Anvil 2.1 established OpenCode 1.x and 2.x adapters; Anvil 2.2 added optional Databricks execution to both; Anvil 2.3 adds provider independence without changing runtime requirements. Anvil 2.3.1 corrects lifecycle coupling; 2.4.0 adds safe runtime quiescing and topology-aware setup; 2.5.0 introduces Anvil-owned Databricks configuration and authentication; 2.6.0 adds validated readiness and provider reliability; 2.6.1 fixes provider-specific fallback setup and cross-session SDK path reuse; 2.6.2 hardens first-use lifecycle and SDK bootstrap; 2.7.0 adds evidence-backed communication and artifact capabilities on both runtime adapters; 2.7.1 restores backward-compatible recognition of 2.6.x managed profiles during upgrade; 2.8.0 adds semantic lifecycle states, ownership-aware config migration, and interruption recovery; 2.9.0 adds long-horizon engineering continuity; 2.10.0 adds adaptive, task-local activation. See [runtime compatibility](../runtime-compatibility.md) for version floors and validation methods.

Anvil 2.10 adds task-local adaptive depth and milestone-scoped architecture evidence on both supported OpenCode generations; the existing Requirements, Architecture and Work models and resume guarantees remain available.
| Capability | Anvil V1 | Anvil 2.1 + OpenCode 1 | Anvil 2.1 + OpenCode 2 | Anvil 2.2 + OpenCode 1 | Anvil 2.2 + OpenCode 2 | Anvil 2.3 + OpenCode 1 | Anvil 2.3 + OpenCode 2 | Anvil 2.4 + OpenCode 1 | Anvil 2.4 + OpenCode 2 | Anvil 2.5 + OpenCode 1 | Anvil 2.5 + OpenCode 2 | Anvil 2.6 + OpenCode 1 | Anvil 2.6 + OpenCode 2 | Anvil 2.7 + OpenCode 1 | Anvil 2.7 + OpenCode 2 | Anvil 2.9 + OpenCode 1 | Anvil 2.9 + OpenCode 2 | Anvil 2.10 + OpenCode 1 | Anvil 2.10 + OpenCode 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Single model-neutral Anvil agent | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| `/remember` and `/recall` | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| `/distill` and source registry | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Markdown file memory and provenance | Basic | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Source freshness and reconciliation | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Memory search | File helper | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool |
| Knowledge access | Manual | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files |
| Native stats | No | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON |
| Databricks provider setup and resolution | No | No | No | CLI | CLI | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback |
| Databricks readiness integrity and provider health | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Anvil-owned Databricks config/profile | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Databricks remote Python | No | No | No | Yes | Yes | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK |
| Databricks SQL warehouse execution | No | No | No | Yes | Yes | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) |
| Databricks live system catalog and FinOps | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Topology-aware Databricks auth setup | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Human command presenters and JSON modes | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Runtime quiescing during Anvil upgrade | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Databricks VS Code assisted status | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Runtime-major migration command | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Automatic major upgrade during `make upgrade` | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No |
| Multi-agent orchestration | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No |
| Model router | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No |
| Vector database | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No |
| Communication & artifact intelligence | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes |
| Evidence provenance and quantitative integrity contracts | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes |
| Markdown report and slide-outline materialization | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes |
| Semantic architecture model and accessible SVG | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes |
| Deterministic artifact review | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes |
| Binary PPTX/DOCX/PDF rendering | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No |
| Progressive engineering / separate Requirements, Architecture and Work models | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes |
| Adaptive task-local activation and progressive engineering depth | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes |
| Milestone-scoped architecture checks and selective evidence invalidation | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes |
| Atomic task state / stale-aware compaction resume | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes |
| Scoped architecture invariants and requirement coverage | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes |
| Lazy system design and deep Spark references | No | No | No | No | No | No | No | No | No | No | No | No | No | No | No | Yes | Yes | Yes | Yes |

The Databricks rows use shared provider/filesystem primitives and do not require OpenCode 2, MCP, or a model-specific feature. Databricks remains optional when providers or workspace access are unavailable. CLI setup is explicit; a blocked CLI can use SDK fallback where supported.

See [V1 history](v1.md), [V2 release](v2.md), [Anvil 2.1 release](v2.1.md), [Anvil 2.2 release](v2.2.md), [Anvil 2.3 release](v2.3.md), [Anvil 2.4.0 release](v2.4.0.md), [Anvil 2.5.0 release](v2.5.0.md), [Anvil 2.6.0 release](v2.6.0.md), [Anvil 2.6.1 release](v2.6.1.md), [Anvil 2.6.2 release](v2.6.2.md), [Anvil 2.7.0 release](v2.7.0.md), [Anvil 2.7.1 release](v2.7.1.md), [Anvil 2.8.0 release](v2.8.0.md), [the changelog](../../CHANGELOG.md), and the migration guides linked below.

Anvil 2.3.1 keeps the capability matrix unchanged and separates Anvil upgrades from OpenCode runtime updates. See [Anvil 2.3.1 release notes](v2.3.1.md).

Anvil 2.4.0 retains both OpenCode runtime profiles while adding safe upgrade quiescing and human-centered Databricks setup. See [Anvil 2.4.0 release notes](v2.4.0.md) and [the migration guide](../migrations/v2.3.1-to-v2.4.0.md).

Anvil 2.5.0 keeps both OpenCode runtime profiles and moves Databricks setup to an Anvil-owned profile and isolated config. See [Anvil 2.5.0 release notes](v2.5.0.md) and [the 2.4.0-to-2.5.0 migration guide](../migrations/v2.4.0-to-v2.5.0.md).

Anvil 2.6.0 makes setup, status, and doctor use a shared readiness contract, with a validated provider and core capability evidence required for READY. See [Anvil 2.6.0 release notes](v2.6.0.md), the [readiness contract](../databricks/readiness.md), and the [2.5.0-to-2.6.0 migration guide](../migrations/v2.5.0-to-v2.6.0.md).

Anvil 2.6.1 prepares the isolated SDK only after an explicit setup discovers a provider-specific CLI health failure, and preserves the validated SDK executable across clean processes. The patch leaves readiness and state-schema semantics unchanged; no migration is required. See [Anvil 2.6.1 release notes](v2.6.1.md).

Anvil 2.6.2 adds shared lifecycle reporting, an isolated fresh-machine command matrix, explicit pip/venv checks, preserved SDK invocation paths, and phase-aware safe diagnostics. It leaves runtime compatibility and Databricks readiness persistence unchanged. See [Anvil 2.6.2 release notes](v2.6.2.md) and the [public command contracts](../command-contracts.md).

Anvil 2.7.0 adds local evidence and quantitative contracts, audience and constraint planning, Markdown reports and slide outlines, semantic architecture SVG, and deterministic artifact review. It adds no OpenCode major requirement, persistent data migration, or required external dependency. Binary PPTX/DOCX/PDF rendering remains unavailable. See [Anvil 2.7.0 release notes](v2.7.0.md), the [communication architecture](../communication-artifact-intelligence.md), and [ADR-0015](../decisions/ADR-0015-communication-artifact-intelligence.md).

Anvil 2.7.1 restores backward-compatible auditing for supported 2.6.x managed profiles during lifecycle inspection, doctor, reforge, and upgrade. Newly generated 2.7.1 profiles remain strictly audited. No OpenCode runtime change is required. See [Anvil 2.7.1 release notes](v2.7.1.md).

Anvil 2.8.0 separates installed source state from checkout target state, records managed-file ownership, preserves user extras, blocks downgrades, and recovers interrupted changes from verified snapshots. See [Anvil 2.8.0 release notes](v2.8.0.md), the [2.7.1-to-2.8.0 migration guide](../migrations/v2.7.1-to-v2.8.0.md), and [ADR-0016](../decisions/ADR-0016-lifecycle-state-and-managed-file-migration.md).

Anvil 2.9.0 adds progressive engineering continuity, local task state, requirements coverage, architecture conformance, system design and deep Spark references on both runtime adapters. Tiny tasks retain the direct path. No runtime upgrade or memory migration is required. See [release notes](v2.9.0.md), [migration](../migrations/v2.8.0-to-v2.9.0.md), and [engineering evidence](../engineering-evaluation.md).

Anvil 2.10.0 makes engineering depth task-local while retaining 2.9 requirements/architecture/work state, safe resume and completion gates. Scoped milestone checkpoints reuse valid invariant evidence. It requires no runtime migration and retains the previously supported 2.6.x source line. See [release notes](v2.10.0.md), [migration](../migrations/v2.9.0-to-v2.10.0.md), and [adaptive engineering evidence](../engineering-evaluation.md).
