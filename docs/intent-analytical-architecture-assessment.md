# Intent Compilation and Analytical Intelligence — Architecture Assessment

**Repository state assessed:** Anvil 2.12.0, source checkout on `master`.

This assessment was written against the current source before implementation. It is the architecture decision input for the incremental analytical-intelligence work; the repository source, tests, and configuration were checked rather than treating earlier architecture documents as current source of truth.

## Current responsibilities and seams

| Concern | Current owner | Existing seam and relevant limits |
|---|---|---|
| Runtime, model/provider selection, authentication, session and tool execution | OpenCode | Anvil has no model binding and supports both configured runtime generations. The feature must remain a lazy skill and local helper, not a runtime hook or second agent. |
| Primary instructions and task lifecycle | `config/AGENTS.md`, managed OpenCode agent profile | Direct work is the normal path. `anvil-engineering` provides optional stateful engineering requirements/architecture/work models for long engineering tasks; it is not a generic analytical workflow engine. |
| Lazy domain guidance | `config/skills/*/SKILL.md` and managed skill allowlist | `anvil-communication` already owns analytical/editorial reasoning for evidence-backed reports and presentations. Its profile permission is lazy; extending it does not add default prompt text or a new runtime dependency. |
| Local source inventory and extraction | `scripts/communication/inputs.py` | Named paths, bounded discovery/extraction, provenance hashes, and no implicit crawl. CSV/TSV are currently exposed as text extraction, not row-wise deterministic profiling. |
| Quantitative calculations | `scripts/communication/quantitative.py` | Deterministic decimal arithmetic for already-structured metric comparisons, distributions, normalization, and presentation. It does not load and profile general tabular datasets or construct a bounded execution plan. |
| Evidence, findings, narrative and artifact plans | `scripts/communication/contracts.py`, `planning.py` | A validated artifact contract already separates evidence/findings/quantitative insights from Markdown/SVG materialization. Its finding fields are artifact-oriented and should not become the sole analysis result contract. |
| Artifact materialization and review | `scripts/communication/materialize.py`, `diagrams.py`, `review.py`; `scripts/artifacts.py` | Markdown and accessible SVG outputs consume structured plans. Renderers should remain downstream of analytical results and must not acquire analytical responsibility. |
| Databricks access | `scripts/databricks_providers/*`, Databricks skill | Optional provider adapters make bounded read-only requests under existing authorization. Core profiling and analysis cannot depend on Databricks, network, or workspace readiness. |
| Memory and durable state | `scripts/memory.py`, explicit memory commands, engineering XDG state | One-off datasets, task briefs, evidence, and findings must not be written to durable memory or create a parallel resume/state system. |
| Lifecycle and ownership | `scripts/managed_config.py`, `configure.py`, lifecycle scripts, `config/managed-inventory.json` | Runtime-independent scripts and skills are shipped through manifest-managed paths. Existing local/external config preservation is a release invariant. A new package needs explicit package ownership; no runtime profile change is needed if the current lazy skill is extended. |
| Verification | `tests/run.sh`, focused `tests/*.py`, lifecycle matrix | Offline Python-standard-library tests are the established pattern. Lifecycle tests already cover both runtime generations and managed ownership. |

## Identified gap

The repository has useful evidence extraction, quantitative contracts, editorial selection, and artifact validation, but no general deterministic row-profile/execution layer. There is also no compact contract that preserves an original natural-language request while validating explicit versus derived execution requirements. Current communication plans cannot safely substitute for an artifact-independent analytical result because their lifecycle is tied to artifact constraints and materialization.

## Decision

Add a small, stateless, standard-library `scripts/analysis` package with independently testable contracts, profiling, bounded generic operations, findings, materiality, and a communication adapter. Expose it through a local `scripts/analyze.py` CLI for deterministic profile/plan execution/contract validation. Extend the existing lazy `anvil-communication` skill to direct analytical tasks as well as artifact tasks; do not add a new skill, agent, Make target, durable state store, model call, or external service.

The original request remains authoritative. A brief validator checks the request, provenance labels, non-goals, scope limits, and success criteria; semantic compilation itself remains model reasoning instructed by the skill. Profiling and approved plan operations remain deterministic. The CLI does not infer business semantics, generate questions, rank materiality using an opaque score, or write artifacts. The skill composes those model judgments and can pass selected evidence/findings to existing artifact plans through a narrow adapter.

The analysis package reads only explicitly named local inputs, has explicit byte/row/column/group/operation bounds, emits source hash and truncation/unknown status, does not log data, and does not persist results. Databricks remains an optional evidence provider outside this local core. Analysis contracts are kept separate from artifact contracts; the adapter maps supported fields and preserves evidence IDs and epistemic labels.

## Trade-offs and rejected alternatives

- **Extend `communication.quantitative.py` directly:** rejected because it compares already-structured artifact metrics and has presentation-oriented helpers. General row profiling would conflate responsibilities and risk changing existing artifact behavior.
- **Add an analytical skill or a second agent:** rejected because the current communication skill is already loaded lazily for data-backed communication, and model judgment belongs to the existing single agent. One skill can provide the analytical reasoning instructions without duplicating the prompt path.
- **Use the engineering Work Model for analytical tasks:** rejected because it creates unnecessary durable project state and is designed for long-horizon software changes.
- **Build a database, dataframe dependency, Databricks requirement, or workflow engine:** rejected because none is needed for bounded local table profiling and deterministic primitives, and each would harm offline/runtime independence.
- **Make the renderer the analysis owner:** rejected because chat responses and future artifact formats need the same findings, and format decisions must follow the evidence and narrative.

## Compatibility and verification implications

No OpenCode profile generation or runtime capability is required. Existing `/review`, `artifacts.py`, Markdown/SVG rendering, quantitative contracts, Databricks behavior, memory behavior, runtime adapters, and lifecycle ownership must remain unchanged. New files must be installed and upgraded as Anvil-owned scripts through the existing manifest path. Tests will be offline and deterministic, include a trivial-task routing regression, synthetic independent datasets, profiling/operation bounds, provenance, composition and like-for-like cases, distribution and volume/performance separation, trend minimum evidence, materiality explanation, artifact adapter validation, and lifecycle/profile preservation. Model quality, provider latency/tokens, and real-world business correctness cannot be measured by this offline suite and must be reported as unverified rather than inferred from fixture results.
