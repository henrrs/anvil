# Architecture

Anvil is a repository-managed OpenCode harness with a small set of runtime assets, local helpers, and explicit lifecycle commands.

## Module map

| Area | Responsibilities |
| --- | --- |
| `config/` | OpenCode 1 profile template, agent instructions, skills, slash commands, plugin, and managed artifact inventory |
| `scripts/lib/` | Shared shell paths, diagnostics, managed config application, backup, and transaction helpers |
| `scripts/lifecycle_*.py` | Read-only state projection, pure operation planning, plan validation, transaction journal, recovery, and postflight verification |
| `scripts/runtime*.py` | OpenCode 1 discovery, version validation, and recorded runtime provenance |
| `scripts/managed_config.py`, `configure.py` | Ownership audit, profile merge, artifact verification, and release staging |
| `scripts/databricks.py`, `scripts/databricks_providers/` | Optional CLI setup, provider discovery, local readiness checks, and bounded workspace operations |
| `scripts/memory.py`, `source_registry.py` | Explicit Markdown memory, provenance, search, and source tracking |
| `scripts/engineering/`, `engineering.py` | Progressive engineering task models, repository checks, and bounded recovery |
| `scripts/analysis/`, `analyze.py` | Local deterministic data profiling and analysis primitives |
| `scripts/communication/`, `artifacts.py` | Evidence-based communication planning and local artifact review |
| `evals/` | Optional deterministic evaluation fixtures and local OpenCode evaluation runners |
| `tests/` | Offline unit, command-contract, and isolated lifecycle checks |

## Runtime boundary

Anvil supports OpenCode 1.x only. The user's OpenCode process, selected model, provider, authentication, and session/data paths remain owned by OpenCode. Anvil does not create a shadow runtime profile or copy credentials during ordinary lifecycle operations.

The generated global profile is assembled from the OpenCode 1 template plus Anvil-managed instructions, commands, skills, and the memory-search plugin. The installer stages that profile before applying it. Release hashes in `config/managed-inventory.json` define which files Anvil owns.

## Lifecycle boundary

The shell commands are adapters around common state inspection, planning, backup, application, and verification helpers. Plans describe requested changes before mutations. Backup manifests record exact scope and content hashes. Rollback restores only paths captured by the selected verified snapshot and rechecks the restored installation.

Databricks and local analytical helpers are optional capabilities. They do not participate in OpenCode runtime selection. The standalone evaluation tools are development and certification utilities; normal agent tasks do not invoke them.
