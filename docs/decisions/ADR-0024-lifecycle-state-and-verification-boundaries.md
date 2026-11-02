# ADR-0024: Normalize lifecycle state and separate post-apply verification

**Status:** Accepted

**Date:** 2026-11-02

## Context

Several public commands read the same installation, runtime, Analytics and Databricks state independently. Scalar or malformed JSON could reach `.get()` calls in shell-embedded Python or nested readiness renderers. Product and runtime mutations used the human-oriented `doctor.sh` as their post-apply transaction gate, and recorded target metadata before that gate passed.

## Decision

Normalize persisted documents into explicit domain statuses before observation. Resolve local facts through one shared boundary for inspect, doctor, capabilities and pure planning. Keep remote provider health separate from local inventory. Use a structured verifier for required post-apply probes. Only write target installation metadata after those probes pass; keep the verified snapshot and journal until commit succeeds. Preserve shell adapters for apply and rollback while their operation contracts are extracted incrementally.

The product release and OpenCode runtime version remain independent. Reforge is scoped to the current installed product release; a release change uses upgrade. The managed manifest remains the ownership authority, so normalizing invalid state never grants permission to overwrite user-owned files.

## Consequences

- Legacy scalar, invalid, missing and newer schema values are distinguishable without raw observer tracebacks.
- Doctor output remains useful to humans but does not decide transaction success.
- Failed structured verification restores the exact pre-operation snapshot before target release metadata is committed.
- The remaining shell operation adapters and module-specific convergence code are explicit migration work, not silently treated as a centralized executor.
