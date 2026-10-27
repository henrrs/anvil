# Anvil 2.9.0 engineering handoff

## Architecture assessment

The baseline was Anvil 2.8.0 at `bd8b21e`: one native model-neutral agent, two OpenCode adapters, lazy Markdown skills/commands, stdlib domain cores, explicit Markdown memory/source registry and safe manifest-owned lifecycle operations. There was no separate engineering execution-state core. This release extends those points rather than replacing the agent, runtime, memory, provider or artifact architecture. The pre-change mandatory suite passed in 336.71 seconds.

## Implementation and long-horizon architecture

The optional engineering CLI/package maintains separate Requirements, Architecture and Work contracts in a single atomic task generation. Requirements retain source provenance and linked verification; architecture retains boundaries, invariants, decisions and unknowns; work retains milestones, dependencies and progress. Native tools perform implementation. The core performs validation, registered checks, dependency/coverage calculations, mechanical invariants, drift/invalidation and completion gates. Semantic extraction/decomposition/design/review remain agent judgments with explicit confidence.

Small requests retain the direct path and do not create a store. Complex tasks can escalate without restarting. Resume reconstructs a bounded current-unit packet, executes no work and requires inspection of uncertain partial actions. Stale branch/HEAD, named files or specification evidence prevents completion; selective revalidation/replanning preserves unaffected work. Required scope cannot disappear silently. Atomic writes, checksums, previous generations, revision checks and lock-spanning verification protect interruption/concurrency.

## Backward compatibility

Existing Make targets, agent/plugin policy, model/runtime independence, memory commands, Databricks and communication artifacts remain intact. Both native runtime generations discover the new lazy skills. No package, MCP, runtime upgrade or old-memory migration is introduced. Task state is optional and separate under the Anvil XDG state root; lifecycle snapshots/rollback leave it intact. The supported migration window extends to three previous minors to retain the existing 2.6 source line. A prior 2.8 manifest upgrades without target-only corruption and rollback restores that config while preserving task state/runtime.

## System design and Spark

The new system-design skill routes to compact ownership/boundary, distributed-failure and data-system references only when relevant. It ties patterns to observed design pressure, keeps retry/state ownership explicit and prefers the smallest coherent seam. The existing Spark skill is deepened rather than duplicated: 13 focused references follow physical execution/evidence through plans, AQE, stages/tasks, source reads, Python/Arrow/JVM, shuffle/skew/spill, connectors, Photon, Delta and streaming. Missing evidence stays UNKNOWN; settings or proprietary behavior are not treated as measurements.

## Evaluation

`evals/engineering/baseline.json` records baseline availability and the original suite result. `results.json` records three deterministic candidate replays for ingestion and three for an unrelated local scheduler, including partial milestone interruption and loss of in-memory history. Ingestion reaches 12/12 required requirements and four invariants; scheduler reaches 7/7 and two invariants. Injected boundary leaks are detected individually. Structured continuation recovers objective, architecture, relevant requirements/decisions, progress, blockers, evidence and next action.

Replay uses explicit reference implementations and is not autonomous LLM coding. Eight system-design and 13 Spark cases have substantive rubrics and separate attributed semantic adjudication. The optional live OpenCode harness supports repeated baseline/candidate and component/skill protocol profiles without retaining private reasoning. Real-model success, token savings, exploration, semantic design quality and real Spark speedups remain unmeasured; no improvement percentage is claimed.

The permanent kernel grows from 3,724 to 3,930 bytes (+206), within the existing 4,200-byte gate. New discovery metadata also consumes context; exact provider token/latency overhead is unmeasured. Task state/reference bodies are not loaded on ordinary startup.

## Verification and release gates

The mandatory `make test` includes existing OC1/OC2, memory, Databricks, artifacts and lifecycle regressions plus 24 engineering unit/fault/recovery/concurrency/compaction checks and two-domain replays. Separate official digest-verified OpenCode 1.19.3 and 2.0.31 candidate checks validate native config/agent/command/skill discovery and V2 plugin/knowledge Reference behavior. `version_docs.py`, skill validation and diff hygiene are release gates. Final execution results are recorded in `evals/engineering/release-evidence.json`.

Historical release documents were preserved. The current-profile V1 fixture gained the newly shipped skills; a harness-budget test now reads the active release instead of comparing the current kernel to the frozen 2.6 record. Its historical measurement remains asserted separately.

## Specification coverage

| Specification areas | Implementation/evidence |
| --- | --- |
| 1–7: preserve Anvil, progressive scope and short tasks | Existing architecture/ADRs, `specification.py`, direct-path regressions and native allowlists |
| 8–24: normalization, separate models, traceability, DoD, execution/replan, failure/context/compaction | Contracts/engine/store/context, semantic engineering protocol, interruption and selective-invalidation tests |
| 25–31: design/ownership/pattern/distributed/data reasoning | Lazy system-design entrypoint, three references, eight semantic cases |
| 32–45: Spark mechanism/evidence/source/exploration/verification discipline | Existing Spark skill plus focused references and 13 semantic cases; honest confidence/UNKNOWN handling |
| 46–52: interaction, progress, local state and safe resume | Human/JSON CLI, private XDG state, drift/reconciliation, no automatic executor/scheduler |
| 53–65: ingestion/transfer evals, baseline, metrics, profiles, offline/model/runtime independence | Two fixture suites, replay/live harness, telemetry contracts, native runtime checks, optional model results explicit |
| 66–78: small kernel, progressive skills, semantic tests, decisions and scope changes | 206-byte routing addition, lazy references, explicit reviews, decision invalidation, scope-authorization and replan tests |
| 79–89: errors, atomicity, security, boundaries, Git, docs/version/migration | Typed error UX, state storage tests, named hashes/anchors, ADR-0017, 2.9 release/migration documents |
| 90–112: pyramid, interruption/compaction/staleness, two-domain acceptance, observability and failure regressions | Mandatory offline unit/integration/replay tests, native smoke layer, explicit optional LLM rubrics and measured/null telemetry |
| 113–118: blockers, staged implementation, DoD and handoff | Existing suite preservation, release evidence, this report and explicit limitations/recommendation |

This maps meaningful requirement groups without pretending every prose sentence is an independently verified model capability. All 32 definition-of-done implementation areas have corresponding code/instructions, tests or explicit semantic evaluation contracts. Optional external model/workload effectiveness remains a separate unperformed validation class.

## Documentation and limitations

Updated README, architecture/system map, testing/quality audit, memory/operations, runtime/OpenCode compatibility, releasing policy, capability matrix and changelog. Added engineering usage, core contracts, evaluation methodology, ADR-0017, 2.9 release/migration notes, benchmark evidence and this report. Existing historical release documentation remains unchanged.

Limits: no automatic semantic spec extraction, universal truth/secret detector, external-effect idempotency guarantee, distributed state engine, real-model performance proof or live Spark/Databricks benchmark. Semantic conformance is explicitly attributed. Native runtime smoke proves integration/discovery, not agent reasoning. Source and state paths must be local supported Bash/Python/WSL paths; older helpers must not downgrade a newer state schema.

Release recommendation: **READY WITH KNOWN LIMITATIONS**. The final mandatory suite passed (exit 0, 367.06 seconds), alongside all 24 engineering unit checks, both-domain replays, native runtime checks and documentation/skill/hygiene gates. The limitations concern unmeasured optional semantic/workload effectiveness; deterministic correctness and existing behavior remain release blockers.
