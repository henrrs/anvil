# ADR-0022: Reusable Analytical Intelligence Boundary and Semantic Evidence

**Status:** Accepted

**Date:** 2026-10-31

## Context

Anvil 2.13 already had bounded local profiling, deterministic operations, evidence/findings, and an artifact-independent result contract. The analysis adapter nevertheless depended on communication contracts, distribution/change calculations were duplicated, and raw observation count could be confused with an entity count. Replacing the capability wholesale would duplicate working code and increase lifecycle risk.

## Decision

- Keep the standard-library `scripts/analysis` package as the owner of bounded profile, candidate semantic context, deterministic statistics/operations, provenance and validation.
- Move only the artifact/communication adapter to `scripts/communication/analysis_adapter.py`. Dependency direction is analysis → no renderer; communication/artifact consumers → analysis result.
- Represent grain and entity meaning as bounded candidates with cardinality/repetition evidence and explicit uncertainty. Distinguish observation count from single/composite distinct-key count.
- Aggregate repeated observations within entity-period before cohort comparison; expose retained/added/removed populations. Limit contribution calculations to additive sum/count and expose net and absolute shares without causal language.
- Share deterministic distribution and change arithmetic between analysis and communication. Keep audience framing, unit policy, editorial judgment and rendering in communication.
- Reuse the existing managed package installation and lifecycle transaction. Do not add dependencies, persistent semantic state, another agent, general BI layer, runtime config, or external service.
- No runtime upgrade or OpenCode profile change is part of this decision.
- Keep live semantic truth, general prose correctness, causal inference, exact composition decomposition, anomaly detection and narrative synthesis explicitly outside deterministic guarantees.

## Consequences

Terminal analysis and artifact workflows can consume the same source-bound calculations and evidence. Candidate semantics can improve question selection while retaining `UNKNOWN` when fields are ambiguous. The new work adds local computation and carries a measurable synthetic profiling overhead; it does not prove model-level task quality. Composition decomposition, anomaly/change algorithms and live task evaluation remain follow-up work.

## Verification

Offline tests cover repeated/composite grain, observation/entity distinction, changing populations, repeated entity-period aggregation, broad versus concentrated additive contributions, stable-mean distribution shifts, changing coverage, trend evidence and false/unsupported claims. Communication tests verify use of shared statistics. Lifecycle tests exercise installed helper packaging and existing ownership-preservation behavior. Full `make test`, documentation/version checks and final working-tree review are required before the candidate result is reported.
