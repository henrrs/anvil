# Execute, verify, replan

Use `start --id TASK --revision N --task T1` only when dependencies are verified. Inspect the current task, relevant requirements, architecture decisions and named sources. Stop exploration once evidence is sufficient for a safe decision and proportional verification; unrelated source availability is not a reason to keep reading.

Make the authorized changes using native tools. `implement --task T1 --files src/file.py ...` records existing files from that unit's declared paths and yields IMPLEMENTED. Changes outside the unit, branch/HEAD changes, or specification drift require explicit revalidation/replanning. Paths describe relevant implementation and test evidence, not a repository-wide inventory.

`check --task T1 --check C1` runs only the registered argv array, with bounded duration/output and no shell interpolation. It stores result, command-definition hash, relevant file hashes, output digest and timing; no raw output is retained. Choose checks that test the requested behavior and failure semantics. A successful process is evidence for that check's scope, not proof of every requirement. Inspect any failed command through normal tools as necessary; do not weaken an assertion before classifying implementation bug, bad test, mistaken requirement, architectural violation, stale assumption or environment failure.

`review --target C2 --result PASS|FAIL|UNKNOWN --observer model|human --summary 'evidence and concise judgment'` records a declared semantic check or semantic invariant. It cannot impersonate an executed test. Preserve OBSERVED/SUPPORTED/INFERRED/UNKNOWN distinctions. Missing evidence is UNKNOWN; the label is preferable to a fabricated metric or guarantee.

At a new subsystem, public contract, durable-state boundary, dependency-direction change or completed milestone, run `checkpoint`. Review responsibility movement, runtime leakage, state ownership, coupling and earlier decisions. Deterministic import/text/file invariants report individually. Semantic invariants require explicit review and remain UNKNOWN until that happens. Formatting/naming preference is not architecture conformance.

After a meaningful failure, classify it and identify discriminating evidence. Equivalent failed checks are rejected unless implementation evidence or the stated `--hypothesis` changes. A changed hypothesis must explain new evidence/conditions; merely renaming it is not a justified retry. Generalizable failures should become a regression test/eval. Do not blindly retry source mutations; ownership, idempotency and uncertain partial outcomes must be explicit.

Use `replan --models MODELS.json --spec SPEC --reason 'changed evidence and decision'` when evidence changes feasibility, scope, ordering, architecture or requirement interpretation. It preserves unaffected work and invalidates affected checks/dependents. Amend/supersede invalid decisions with traceability. A single transient command failure does not justify rebuilding the plan. `complete` checks task/milestone/project definitions of done, required coverage, architecture and unresolved unknowns. Report incomplete work honestly; passing tests alone cannot waive missing scope.

Expose current unit/milestone, completed work, blockers, coverage, verification, conformance and next action in concise progress updates. Expose decision, evidence, high-level alternatives, trade-off and uncertainty; never private reasoning traces.

Reducing required scope through replan requires `--scope-authorization` with a reference to actual user authorization. If complexity disappears, record why, archive the unnecessary execution state and finish through the direct workflow with proportional verification.
