---
name: anvil-system-design
description: Use when engineering decisions change responsibility, dependency direction, durable state, public contracts, failure/retry ownership, provider boundaries or distributed/data-system behavior. Do not use for ordinary local edits without design pressure.
---

# Responsibility before mechanism

Locate the project's current boundaries, contracts, tests and decisions before proposing structure. For a meaningful component identify its responsibility and owner, required information and forbidden knowledge, dependencies/dependents, owned state, failure behavior, retry owner and evolution pressure. Domain expertise explains a mechanism; it does not assign generic responsibilities to the current runtime.

State the required property, alternatives at a high level, decision, evidence, trade-off and verification. A pattern is justified by observed pressure at acceptable complexity cost. Two real backends may justify a small strategy/adapter seam; a single stable implementation without extension pressure usually needs direct code. Do not add a factory, registry, repository, builder, event bus or injection framework merely to name a pattern.

Load [boundaries.md](references/boundaries.md) for contract/policy/execution/state separation, evolution and conformance. Load [distributed.md](references/distributed.md) only for concurrency, distributed failure, ordering, consistency or recovery. Load [data-systems.md](references/data-systems.md) for ingestion/streaming/data-contract decisions. Use only relevant dimensions; do not run every checklist for a local change.

Prefer observed runtime evidence, active source, tests/configuration and project decisions over generic prior knowledge; current authoritative documentation resolves version-sensitive behavior. Record assumptions and confidence. Use the existing ADR convention for consequential decisions. For long work link decisions/invariants to `anvil-engineering` requirements and units; amend or supersede invalid decisions explicitly. Check architecture at meaningful boundaries, focusing on ownership, coupling, failure and evolution rather than style. Keep one Anvil agent, the project's runtime choices and the user's authorization boundaries.
