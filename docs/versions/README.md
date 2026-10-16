# Anvil version capability matrix

Anvil's product version and OpenCode runtime generation are independent. Anvil 2.1 supports the OpenCode 1.x and 2.x adapters listed in [runtime compatibility](../runtime-compatibility.md). The matrix describes features provided by each Anvil/runtime combination.

| Capability | Anvil V1 | Anvil 2.x + OpenCode 1 | Anvil 2.x + OpenCode 2 |
|---|---:|---:|---:|
| Single model-neutral Anvil agent | Yes | Yes | Yes |
| `/remember` | Yes | Yes | Yes |
| `/recall` | Yes | Yes | Yes |
| `/distill` | No | Yes | Yes |
| Markdown file memory | Yes | Yes | Yes |
| Provenance, status and confidence | Basic | Yes | Yes |
| Multilingual aliases | No | Yes | Yes |
| Source registry and idempotency | No | Yes | Yes |
| Changed-source freshness warnings | No | Yes | Yes |
| Cross-source reconciliation workflow | No | Yes | Yes |
| Memory search backend | File helper | Python file fallback | Python file fallback + native tool |
| Knowledge access | Manual file reads | Direct file reads | Native Reference + direct file reads |
| Native stats | No | Text report | Structured JSON report |
| Runtime-major migration command | No | Yes | Yes |
| Automatic major upgrade during `make upgrade` | No | No | No |
| Multi-agent orchestration | No | No | No |
| Model router | No | No | No |
| Vector database | No | No | No |

Anvil 2.0 was OpenCode 2-specific. Anvil 2.1 keeps that adapter and adds an OpenCode 1 adapter so the product can receive Anvil updates without requiring a runtime-major migration.

See [V1 history](v1.md), [V2 release](v2.md), [Anvil 2.1 release](v2.1.md), [the changelog](../../CHANGELOG.md), and [the 2.0-to-2.1 migration guide](../migrations/v2-to-v2.1.md).
