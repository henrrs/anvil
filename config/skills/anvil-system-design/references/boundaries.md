# Boundaries and evolution

Start with the change pressure: a second provider, uncertain state transition, public compatibility promise, shared retry policy or independently evolving contract. Identify which existing owner can absorb it before adding a component. Ask what information crosses the boundary and whether that knowledge belongs on both sides.

A generic contract represents intent and invariants. Policy/planning chooses a physical strategy using explicit capabilities. Execution carries out that choice. Progress state records durable facts, not a second copy of planning policy. These roles are examples to test against the actual project, not a mandatory four-layer framework. Runtime-specific options belong in an adapter or execution configuration unless the public intent truly requires them.

For multiple real providers, keep the interface limited to behavior shared by callers; avoid an interface per implementation detail. Define unsupported capabilities and failure shapes explicitly. Keep provider selection in one owner. For one stable implementation, direct construction and a function seam may be sufficient. Compare the cost of another abstraction with evidence that it prevents real coupling or duplicated policy.

For durable state, identify writer/reader ownership, schema version, atomicity boundary, interruption point, recovery source and compatibility behavior. New states and migrations need failure tests, including interruption between external effect and recorded progress. Public API/schema changes require callers, default semantics, rollout, rollback and coexistence evidence. An immutable architecture document is not proof that the current dependency graph conforms: inspect imports/callers and meaningful failure/retry paths.

Checkpoint after a new subsystem, public contract, durable state or runtime seam. Report deterministic dependency findings separately from semantic responsibility judgments. If evidence contradicts an ADR, keep/amend/supersede it with consequences and affected requirements; a local fix must not silently override the system decision.
