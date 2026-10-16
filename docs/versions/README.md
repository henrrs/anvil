# Anvil version capability matrix

Anvil's product version and OpenCode runtime generation are independent. Anvil 2.1 established OpenCode 1.x and 2.x adapters; Anvil 2.2 added optional Databricks execution to both; Anvil 2.3 adds provider independence without changing runtime requirements. Anvil 2.3.1 corrects lifecycle coupling while keeping the same runtime matrix. Anvil 2.4.0 adds safe runtime quiescing, human-first output, and topology-aware Databricks setup for both supported runtime profiles. See [runtime compatibility](../runtime-compatibility.md) for version floors and validation methods.

| Capability | Anvil V1 | Anvil 2.1 + OpenCode 1 | Anvil 2.1 + OpenCode 2 | Anvil 2.2 + OpenCode 1 | Anvil 2.2 + OpenCode 2 | Anvil 2.3 + OpenCode 1 | Anvil 2.3 + OpenCode 2 | Anvil 2.4 + OpenCode 1 | Anvil 2.4 + OpenCode 2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Single model-neutral Anvil agent | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| `/remember` and `/recall` | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| `/distill` and source registry | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Markdown file memory and provenance | Basic | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Source freshness and reconciliation | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Memory search | File helper | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool |
| Knowledge access | Manual | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files |
| Native stats | No | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON | Text report | Structured JSON |
| Databricks provider setup and resolution | No | No | No | CLI | CLI | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback | CLI + SDK fallback |
| Databricks remote Python | No | No | No | Yes | Yes | CLI or SDK | CLI or SDK | CLI or SDK | CLI or SDK |
| Databricks SQL warehouse execution | No | No | No | Yes | Yes | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) | CLI or SDK (SQL Connector specialized) |
| Databricks live system catalog and FinOps | No | No | No | Yes | Yes | Yes | Yes | Yes | Yes |
| Topology-aware Databricks auth setup | No | No | No | No | No | No | No | Yes | Yes |
| Human command presenters and JSON modes | No | No | No | No | No | No | No | Yes | Yes |
| Runtime quiescing during Anvil upgrade | No | No | No | No | No | No | No | Yes | Yes |
| Databricks VS Code assisted status | No | No | No | No | No | Yes | Yes | Yes | Yes |
| Runtime-major migration command | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Automatic major upgrade during `make upgrade` | No | No | No | No | No | No | No | No | No |
| Multi-agent orchestration | No | No | No | No | No | No | No | No | No |
| Model router | No | No | No | No | No | No | No | No | No |
| Vector database | No | No | No | No | No | No | No | No | No |

The Databricks rows use shared provider/filesystem primitives and do not require OpenCode 2, MCP, or a model-specific feature. Databricks remains optional when providers or workspace access are unavailable. CLI setup is explicit; a blocked CLI can use SDK fallback where supported.

See [V1 history](v1.md), [V2 release](v2.md), [Anvil 2.1 release](v2.1.md), [Anvil 2.2 release](v2.2.md), [Anvil 2.3 release](v2.3.md), [Anvil 2.4.0 release](v2.4.0.md), [the changelog](../../CHANGELOG.md), [the 2.1-to-2.2 migration guide](../migrations/v2.1-to-v2.2.md), and [the 2.2-to-2.3 migration guide](../migrations/v2.2-to-v2.3.md).

Anvil 2.3.1 keeps the capability matrix unchanged and separates Anvil upgrades from OpenCode runtime updates. See [Anvil 2.3.1 release notes](v2.3.1.md).

Anvil 2.4.0 retains both OpenCode runtime profiles while adding safe upgrade quiescing and human-centered Databricks setup. See [Anvil 2.4.0 release notes](v2.4.0.md) and [the migration guide](../migrations/v2.3.1-to-v2.4.0.md).
