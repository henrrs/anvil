# ADR-0014: Public command lifecycle and safe bootstrap

- **Status:** Accepted
- **Date:** 2026-10-25
- **Release:** Anvil 2.6.2

## Context

Fresh installations exposed different commands inferring installation state from config, runtime, metadata, and backup paths. That made partially installed environments look absent or corrupted without a common explanation. The Databricks SDK path also assumed pip existed and canonicalized venv Python symlinks, while SDK subprocess errors lost their failure phase before presentation. Finally, test behavior could depend on the caller's XDG state, PATH, Databricks profile, and Python user environment.

## Decision

1. Use one local lifecycle evaluator for Anvil-managed config, installation metadata, supported runtime, memory, and verified backup inventory.
2. Keep operation blockers separate from persistent lifecycle state. Inventory commands can report repository-only/partial state successfully; commands that require an installation or backup return non-zero with a next action.
3. Keep `make upgrade` Anvil-only and retain explicit runtime update/migration commands. Databricks readiness remains an independent optional integration state.
4. Treat the isolated Anvil SDK venv's invocation path as its identity. Check Python, venv, and pip before package installation; expose missing pip as structured provider data.
5. Construct the Databricks SDK from an explicit Anvil-owned `Config`, and propagate only allowlisted, normalized diagnostics from worker to presenter.
6. Run the test suite under temporary HOME/XDG roots and constrained PATH, with external network denied and unexpected network attempts treated as test failures.

## Consequences

- Fresh and partial installs have consistent command behavior and documented exit semantics.
- Existing Anvil config/runtime data and schema-3 Databricks readiness remain compatible; no migration is required.
- A healthy CLI remains usable when SDK setup is blocked. A blocked fallback cannot produce READY without successful production-path validation.
- Release validation now includes public pre/post-reforge matrices, partial/corrupt states, SDK installation blockers, venv path identity, and a real worker process boundary.

See [public command contracts](../command-contracts.md), the [2.6.2 release report](../versions/v2.6.2.md), and the [pre-implementation reliability audit](../reliability-audit-v2.6.1.md).
