# ADR-0021: Intent Compilation and Analytical Intelligence

**Status:** Accepted

**Date:** 2026-10-30

## Context

Anvil has a lazy communication skill, bounded evidence extraction, quantitative comparisons, artifact contracts, renderers, and model/runtime-independent Databricks adapters. It does not yet have a general tabular profile/execution contract or an artifact-independent analysis result. Reusing the stateful engineering models would persist unrelated analytical work; embedding row-level analysis into the artifact renderer would couple chat analysis to a presentation format.

The source assessment is recorded in [Intent Compilation and Analytical Intelligence — Architecture Assessment](../intent-analytical-architecture-assessment.md).

## Decision

- Add a stateless standard-library `scripts/analysis` package for scope-preserving task briefs, deterministic bounded table profiling and primitives, typed evidence/findings, transparent materiality tiers, and a narrow communication adapter.
- Expose local profile, plan execution, and contract checks through `scripts/analyze.py`. No network, model, service, implicit source discovery, durable state, or filesystem writes are part of the core.
- Extend the current lazy `anvil-communication` skill with analysis-first instructions. The existing single agent remains responsible for semantic discovery, question generation, hypotheses, materiality judgment, and narrative; deterministic code remains responsible for calculations and validation.
- Keep analysis contracts artifact-independent. The adapter maps evidence and finding metadata into existing communication contracts and does not select layout or render output.
- Keep FAST/STANDARD/DEEP budgets explicit and bounded; simple work stays on the current direct path.
- Ship the helper through existing managed-config ownership and lifecycle transactions. Do not change runtime profiles, persistent memory, engineering task state, Databricks behavior, or public Make targets.

## Consequences

The new deterministic functions can be tested offline and reused by chat, artifacts, or later providers. Model semantic quality and real-world task performance remain outside deterministic contract tests. Bounded local input support favors safety and predictable resource use over arbitrary large data processing; users can explicitly select a subset or a suitable analytical provider for larger sources.

## Verification

Offline tests cover request provenance, scope constraints, profile correctness/limits, numeric and categorical operations, temporal evidence thresholds, cohorts/composition, materiality dominance, evidence traceability, adapter validation, and simple-task routing. The full existing lifecycle suite checks both OpenCode profiles and local config preservation. Release reporting separates those results from unavailable live-model, latency/token, and real artifact evaluation.
