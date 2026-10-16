# Anvil version capability matrix

Anvil's product version and OpenCode runtime generation are independent. Anvil 2.1 established OpenCode 1.x and 2.x adapters; Anvil 2.2 adds the same optional Databricks capability to both. See [runtime compatibility](../runtime-compatibility.md) for version floors and validation methods.

| Capability | Anvil V1 | Anvil 2.1 + OpenCode 1 | Anvil 2.1 + OpenCode 2 | Anvil 2.2 + OpenCode 1 | Anvil 2.2 + OpenCode 2 |
|---|---:|---:|---:|---:|---:|
| Single model-neutral Anvil agent | Yes | Yes | Yes | Yes | Yes |
| `/remember` and `/recall` | Yes | Yes | Yes | Yes | Yes |
| `/distill` and source registry | No | Yes | Yes | Yes | Yes |
| Markdown file memory and provenance | Basic | Yes | Yes | Yes | Yes |
| Source freshness and reconciliation | No | Yes | Yes | Yes | Yes |
| Memory search | File helper | Python file fallback | File fallback + native tool | Python file fallback | File fallback + native tool |
| Knowledge access | Manual | Direct file reads | Native Reference + files | Direct file reads | Native Reference + files |
| Native stats | No | Text report | Structured JSON | Text report | Structured JSON |
| Databricks CLI setup/profile status | No | No | No | Yes | Yes |
| Databricks remote Python | No | No | No | Yes | Yes |
| Databricks SQL warehouse execution | No | No | No | Yes | Yes |
| Databricks live system catalog and FinOps | No | No | No | Yes | Yes |
| Runtime-major migration command | No | Yes | Yes | Yes | Yes |
| Automatic major upgrade during `make upgrade` | No | No | No | No | No |
| Multi-agent orchestration | No | No | No | No | No |
| Model router | No | No | No | No | No |
| Vector database | No | No | No | No | No |

The Databricks rows use shared CLI/filesystem primitives and do not require OpenCode 2, MCP, or a model-specific feature. Databricks remains optional when its CLI or workspace is unavailable.

See [V1 history](v1.md), [V2 release](v2.md), [Anvil 2.1 release](v2.1.md), [Anvil 2.2 release](v2.2.md), [the changelog](../../CHANGELOG.md), and the [2.1-to-2.2 migration guide](../migrations/v2.1-to-v2.2.md).
