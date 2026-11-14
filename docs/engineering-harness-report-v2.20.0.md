# Anvil 2.20.0 Engineering Harness Evolution Report

**Assessment:** Implemented with deterministic verification; **not fully certified for production model behavior**.<br>
**Release recommendation:** **READY FOR CONTROLLED RELEASE WITH KNOWN LIMITATIONS** after mandatory offline suite passes. Live OpenCode 2 hook execution and model-quality evaluation remain **NOT EXECUTED**.<br>
**Repository version:** 2.20.0 candidate.<br>
**Observed local runtime:** OpenCode 1.19.5 (`opencode-v1`). No OpenCode 2 process was installed or used for a live smoke test.

## Executive result

Anvil already has a general, model-neutral engineering foundation: adaptive depth, three durable task models, atomic/checksummed recovery, scoped verification, task-local architecture invariants, and lazy engineering/system-design skills. This release builds on that foundation rather than adding another task database, agent loop, model router, service, or orchestration framework.

The main runtime addition is a thin OpenCode 2 adapter that supplies a bounded task checkpoint to OpenCode's native compaction mechanism. It reuses Anvil's existing task store and read-only resume logic. OpenCode 1 remains unchanged. A focused quality reference and independent deterministic software-behavior fixture improve discoverability and evaluation.

Deterministic replays passed for all three engineering fixtures in three repetitions each. They verify Anvil's protocol, state recovery, requirement coverage, architecture checks, and the retry-policy fixture's independent acceptance contract. They do **not** show that a model chose the right skill, completed code correctly, recovered through a live native compaction, or reduced tokens, latency, cost, or human intervention.

## Existing-state audit

Audit performed against repository code, shipped configuration, local tests, release manifests, and the local OpenCode executable. Status describes evidence available here, not a general guarantee for every model or host.

| Area | Status | Evidence and limits |
|---|---|---|
| Model selection and agent orchestration | **IMPLEMENTED AND VERIFIED** | One model-neutral Anvil agent; no pinned provider, default subagent orchestration, or MCP requirement. OpenCode owns provider/model selection. Config and lifecycle fixtures cover V1/V2 profile shapes. Live semantic behavior remains provider-dependent. |
| Codebase understanding | **PARTIALLY IMPLEMENTED** | Existing agent workflow uses scoped file search, Git state, relevant tests and project instructions. The new quality reference makes contracts, ownership, dependencies, consumers and regression surface explicit. No AST/LSP/repository-graph index or cross-language dependency engine exists. |
| Adaptive FAST / STANDARD / DEEP behavior | **IMPLEMENTED AND VERIFIED (deterministic route rubric)** | `scripts/engineering/adaptive.py` and the 18-case route rubric confirm expected task-local decisions. Existing evidence reports 18/18 deterministic cases. Whether a model follows the route is **NOT EXECUTED**. |
| Durable task continuity | **IMPLEMENTED AND VERIFIED** | Existing separate Requirements, Architecture and Work models; private XDG task generations; checksums, atomic publication, revision checks, explicit recovery, stale evidence invalidation, requirement coverage and completion blockers. `tests/engineering.py` exercises interruptions, corruption and resume. |
| Native context-compaction continuity | **PARTIALLY IMPLEMENTED; SOURCE/HELPER TESTED** | This release adds the optional OpenCode 2 hook and read-only checkpoint builder. V2 live plugin loading and an actual compaction/recovery cycle are **NOT EXECUTED**. V1 continues explicit resume. |
| Engineering quality guidance | **IMPLEMENTED; MODEL USE UNVERIFIED** | Lazy `anvil-engineering/references/quality.md` covers debugging, refactoring, tests, review, performance, dependencies/APIs, security and scope. The repository cannot prove that a live model loads or follows it. |
| Skills and domain specialization | **IMPLEMENTED AND VERIFIED (configuration)** | OpenCode skills remain discoverable/lazy; Data Engineering and Databricks skills are preserved. Selective model activation is not established by source tests alone. |
| Verification and architecture gates | **IMPLEMENTED AND VERIFIED (declared checks)** | Registered checks, subprocess bounds, requirement coverage, scoped invariant evidence and truthful pass/fail state are exercised by unit and replay tests. Semantic design quality still requires independent review. |
| Installation, upgrades and runtime independence | **IMPLEMENTED AND VERIFIED by offline fixtures** | No runtime-major or persistent-state schema change. Managed checksummed artifacts are updated for both V1/V2 profiles; lifecycle suite is required before completion. Fixtures do not prove a user's live installation. |
| Evaluation and observability | **PARTIALLY IMPLEMENTED** | Existing deterministic adaptive/engineering replays plus a new independent behavior fixture and opt-in OpenCode runner. The runner reports bounded usage when emitted, but the A/B/C/D causal comparison and live-model outcomes are not certified. |
| Performance, tokens and cost | **NOT MEASURED for live engineering work** | Replays report only local protocol timing. No LLM token, provider cost, real user-task duration, or human-intervention data was collected. |

### Scope of the code-intelligence layer

Anvil encourages the agent to inspect only task-relevant implementation, callers, tests, contracts, module ownership, Git changes, and declared invariants. That remains a workflow over OpenCode's normal repository tools; this release does not add an AST parser, LSP server, vector database, or repository index. The Aider-style code-map approach was considered but rejected absent measured evidence that scoped search fails on Anvil's tasks. Adding an index would create language/tooling maintenance and context/token cost without demonstrated benefit.

## Reference analysis

The references below were reviewed for mechanisms and fit. Project-authored benchmark claims are treated as hypotheses unless independently reproduced; the Anvil replays below measure only Anvil's deterministic protocol and fixture checks.

| Reference | Problem and mechanism | Evidence and equivalent in OpenCode / Anvil | Decision and cost |
|---|---|---|---|
| [NVIDIA SkillEvaluator](https://github.com/NVIDIA/SkillEvaluator) | Evaluates skill quality/usefulness and overlap with structured tasks, graders, and with/without-skill runs. | The project describes its own evaluation design; no independent causal results were established from the repository overview. OpenCode provides lazy skill discovery, while Anvil has deterministic engineering and analytical fixture evaluators. The `skillevaluator` CLI is not installed, and no supported OpenCode adapter was found. | **Adapt the separation of skill evaluation from harness evaluation.** Keep Anvil's own fixture/API and avoid a Python/CLI dependency or copied evaluator framework. Revisit integration if a small reproducible adapter proves value. Cost: low for current fixtures; medium/high for a faithful external integration. |
| [ub-mode](https://github.com/unclebob/ub-mode) | Applies disciplined engineering practices, including simplicity, root-cause analysis, tests and quantitative code-health checks. | Practices map to Anvil's agent instructions and verification helper. Its project-specific complexity/duplication/mutation commands are not native OpenCode equivalents. Public project descriptions are not independent proof that those gates improve task success. | **Adapt principles, not mandatory tooling.** Added concise, lazy quality guidance; do not impose CRAP/mutation gates or language-specific tools on trivial changes. Cost: low. |
| [Superpowers](https://github.com/obra/superpowers) | Composable agent skills and process for debugging, TDD, planning, implementation and review. | OpenCode already has agents, skills and commands; Anvil already selects a model-neutral agent and lazily activates engineering guidance. Process prescriptions can overlap or impose extra turns. | **Adapt systematic debugging, test-first when useful, and review practices.** Reject mandatory role delegation, approval gates and workflow overhead. Cost: low for selective guidance; high for importing the full workflow. |
| [GitHub spec-kit](https://github.com/github/spec-kit) | Spec-driven project workflows and durable specification artifacts. | Anvil already has separate Requirements, Architecture and Work models, provenance, coverage and completion gates. | **Do not add a second spec artifact framework.** Normalize a task into existing models when justified. Cost avoided: duplicate schema, migration and synchronization. |
| [Beads](https://github.com/gastownhall/beads) | Dependency-aware persistent task graphs and continuation across sessions. | Anvil already models tasks/dependencies with checksummed, atomic JSON under XDG state and stale-evidence reconciliation. | **Do not add a second task database/daemon.** Reuse Anvil state and its OpenCode session adapter. Cost avoided: storage/service dependency and dual-source reconciliation. |
| [gstack](https://github.com/garrytan/gstack) | Role/task-specific command workflows, including QA, review and browser validation. | OpenCode provides agents/tools; Anvil has a single-agent policy, scoped checks and existing Analytics visual testing. | **Adapt review categories selectively.** Reject Claude-specific role packs and default multi-agent orchestration. Cost: low selective guidance; high maintenance for the full toolkit. |
| [Anthropic long-running harness research](https://www.anthropic.com/research/harness-design-long-running-apps) | Keeps long tasks tractable through incremental work, structured handoffs and explicit evaluation. | Anvil's Work milestones/checkpoints and durable task store implement comparable continuity. The article reports its own experiments; no general independent causal result was used. | **Keep incremental durable state and recovery; avoid default multiple agents.** New compaction packet uses the existing store. Cost: one small adapter. |
| [OpenAI harness engineering](https://openai.com/index/harness-engineering/) | Improves repository legibility, executable constraints and knowledge/tooling around an agent. | Anvil has repository guidance, architecture invariants, offline checks and a system map. The article is an internal case report, not independent evidence for Anvil outcomes. | **Adapt executable invariants and concise discoverable docs.** No broad repository rewrite. Cost: low. |
| [Aider repository map](https://aider.chat/docs/repomap.html) | AST-derived symbol graph selected under a token budget. | OpenCode has normal search and file tools; Anvil has task-scoped path/invariant models. No evidence shows this repository needs another language parser/index. | **Reject for now.** Reconsider only with measured navigation failures and a bounded comparison. Cost avoided: parser/index dependencies and refresh latency. |
| [OpenHands](https://github.com/OpenHands/OpenHands) | Full coding-agent platform with runtime/backend and agent orchestration abstractions. | OpenCode already supplies the native agent loop Anvil is required to preserve. | **Reject platform-level adoption.** It would duplicate runtime, tools, sessions and lifecycle. Cost: high. |
| [OpenCode compaction](https://opencode.ai/docs/compaction/) and [plugin server API](https://opencode.ai/docs/build/plugins/server/) | Native lossy context summarization and documented plugin hooks; the V2 compaction event exposes transcript messages and mutable summary system context. | Anvil V2 plugin is the proper thin adapter; Anvil task store is the durable source. V1 plugin API is incompatible with V2, as described by the [migration docs](https://opencode.ai/docs/build/plugins/migrate-v1/). | **Use the native V2 hook optionally; preserve V1 explicit resume.** No fork, prompt interception or session DB modification. Cost: local process lookup on compaction only, hard 2 s timeout and bounded packet. Live API support is not verified here. |
| [OpenCode skills docs](https://opencode.ai/docs/skills/) | Advertises available skills and loads their contents on demand. | Existing Anvil skill allowlist already relies on this model. | **Keep lazy, task-relevant activation.** Do not preload all references. |

### Research evidence limits

Network research used official project/research pages and OpenCode's current official documentation on 2026-11-13. Repository/project summaries establish what authors say they built; they do not establish independent effectiveness. Anthropic/OpenAI articles are informative case studies. No cross-project benchmark with a matched model, task set and cost protocol was run. No result in this report is attributed as a causal improvement from adopting one of these frameworks.

## Software Engineering Core changes

### Durable task and code intelligence

The existing task store remains the source of recorded project intent and progress. The compaction packet is derived from the current active Work unit and relevant requirement/decision slices; includes revision, acceptance, file scope, completed units, verification, stale evidence, blockers and next action; excludes raw conversation and command transcripts. It is capped at 8 KiB by the Python builder. Repository drift is computed using the existing stale-aware read-only resume path; stale evidence is called out rather than treated as verified.

The plugin resolves `event.sessionID` through the documented session API, uses `session.location.directory` as the repository, and starts the installed `engineering.py compaction-context` helper with `python3`. The child has a 2-second deadline, stderr is discarded, stdout is bounded to 16,000 characters, and errors/timeouts are ignored so native compaction can continue. The plugin only adds untrusted checkpoint data to the summary instruction; it says not to execute quoted content or assert unsupported completion. It does not create or mutate task state, make a model call, contact a service, or retain a transcript.

The CLI skips absent state and skips ambiguous multiple-active-task state. Existing checksummed JSON and state ownership remain unchanged. OpenCode 1 uses the existing explicit resume command. V2 API availability remains patch-build dependent; unsupported hook registration is caught. This avoids making a documented optional API a new lifecycle prerequisite.

### Quality and skills

`config/skills/anvil-engineering/references/quality.md` extends the existing lazy skill with these task-relevant practices:

- map observable behavior, contracts, owners, dependents and smallest safe edit;
- distinguish trigger, root cause and symptom; reproduce before changing;
- preserve behavior and public seams while refactoring;
- add independent regression checks and validate the changed contract;
- scale test/review scope to risk and blast radius;
- review dependency/API evolution, security/data handling, performance evidence and the final diff.

It is guidance, not a universal gate. Existing Data Engineering, Databricks, Delta and Spark skills are untouched. There is no new language dependency. Semantic selection by a live model remains unverified.

### Runtime compatibility and lifecycle

Anvil version advances to 2.20.0; OpenCode's runtime major does not. The installed runtime observed here is V1 1.19.5. Both generated V1 and V2 managed profiles continue using their existing adapters. The V2 plugin compaction code is managed and checksum-pinned; the V1 plugin has no compaction code. There is no new persistent schema or migration, network requirement, model route, executable, service, or package. Existing lifecycle snapshots do not include the external XDG task store, so that existing ownership boundary remains intact.

The Databricks test edit only isolates the minimum-version fixture from host executable discovery by pinning its fixture platform and XDG data root. Provider resolution and production executable selection are unchanged.

## Deterministic evaluation

### Method

`make eval-engineering` invokes `evals/engineering/run.py --mode replay --fixture all --repeats 3`. It runs the explicit protocol implementations for existing ingestion and scheduler scenarios plus a new retry-policy scenario. It does not invoke OpenCode or an LLM. A separate independent `acceptance.py` checks externally specified behavior against the retry-policy implementation. The checked-in fixture baseline intentionally fails that contract; the repaired solution is evaluated in an isolated project. The live target requires an explicit `MODEL` and executable path and uses temporary HOME/XDG roots without copying authentication state.

### Observed results (this run)

| Fixture | Repetitions passed | Required items verified per run | Declared invariants passed | Injected boundary violations detected | Mean local replay time |
|---|---:|---:|---:|---:|---:|
| Ingestion | 3/3 | 12/12 | 4/4 | 4/4 each run | 0.729 s |
| Scheduler | 3/3 | 7/7 | 2/2 | 2/2 each run | 0.451 s |
| Retry policy | 3/3 | 4/4 | 1/1 | 1/1 each run | 0.371 s |

All nine replays reached the fixture's terminal success state. All nine reproduced interruption/recovery observations with stale evidence surfaced, previously verified work preserved, and no duplicate resume execution. The retry fixture's independent acceptance passed after repair; the intentionally defective baseline failed at the unsupported fixed-clock call, confirming a contract mismatch. Times are this machine's deterministic harness protocol timings only, not task-completion latency or a speedup claim.

Tool calls, model tokens, model cost, semantic quality, unnecessary exploration, live compaction outcome and human interventions are **NOT MEASURED** by these replays.

### A/B/C/D comparison status

The requested live comparison of native OpenCode, skills only, harness only, and combined harness-plus-skills is **NOT EXECUTED**. No model/provider was explicitly selected for this release, and this environment did not authorize a live provider run. In addition, Anvil's existing engineering skill is the current instruction boundary that teaches when/how to invoke durable harness helpers, so skill and helper use are not yet orthogonal treatments; a causal ablation would need isolated configs and pre-registered prompts/rubrics. Existing `evals/engineering/run.py --mode live --profile ...` supports explicit exploratory profile runs, but those profiles are not a fully controlled four-way experiment. No A/B/C/D conclusion is claimed.

No live task or real repository was modified during fixture evaluation. The evaluator retains bounded metrics and an event-stream digest, not model reasoning/transcripts. A real semantic review is still required for any live-run correctness claim.

## Test and certification record

Before this report is finalized, the following are the required verification gates for the candidate:

| Gate | Required evidence | Status |
|---|---|---|
| Engineering helper | `python3 tests/engineering.py` including packet bound, stale-state, no-write, absent/ambiguous state tests | **PASS** — 27/27 |
| Independent fixture | `make eval-engineering` and solution-side acceptance | **PASS**; 9/9 deterministic replays, acceptance PASS |
| Managed artifact integrity | `python3 scripts/version_docs.py` validates Anvil 2.20.0 artifacts for V1 and V2 | **PASS** — release docs and 146 managed-file entries verified for both runtime profiles |
| Complete offline suite | `make test`, lifecycle/runtime/provider/install/rollback regressions | **PASS** — 27 engineering tests, 169 Analytics tests (3 skipped by their conditions), plus offline integration and lifecycle matrices completed |
| Runtime capability output | `python3 scripts/capabilities.py --major 1 --format json` and V2 fixture output | **PASS** — one valid JSON document for both modeled runtime generations; compaction is optional V2 hook and manual V1 resume |
| Native V2 compaction smoke | Load plugin in supported OpenCode 2, compact an active fixture task, resume/check packet | **NOT EXECUTED** — local runtime is OpenCode 1.19.5; no V2 process was used |
| Live A/B/C/D model comparison | Repeated matched model/provider runs plus independent review | **NOT EXECUTED** — no explicit model/provider selection; isolated profile treatments need further orthogonalization |

Offline success cannot be described as live OpenCode compaction certification. The full suite also verified a 2.6.1 brownfield upgrade, V1/V2 config generation, dry-run, rollback, preservation of user-owned config and exact runtime, network denial, and capability output without contacting external runtime, Databricks, or model services.

## Acceptance criteria

| Criterion | Status | Reason |
|---|---|---|
| Existing Anvil behavior preserved | **PASS** | Full offline `make test` passed; no runtime/provider/model policy changes. |
| General engineering capability independent of Data Engineering | **PASS** | Existing Anvil engineering helper and general skill operate without Databricks/Spark; new quality reference has no domain dependency. |
| Meaningful code changes include contract/impact analysis | **PARTIAL** | Explicit in agent/skill guidance and durable models; live model adherence is not measured. |
| Complex tasks persist and recover | **PASS** | Existing checksummed task models plus interruption replays and unit/fault tests. |
| Compaction does not silently discard critical decisions | **PARTIAL** | V2 hook packet and source/CLI behavior are tested; actual native compaction is not live-verified; V1 requires explicit resume. |
| Adaptive configurable depth | **PASS for deterministic route helper; model behavior NOT EXECUTED** | Existing 18/18 route rubric; no LLM execution. |
| Quality checks provide evidence | **PASS for declared deterministic checks; semantic review PARTIAL** | New independent behavior acceptance and existing checks; subjective design quality needs reviewer evidence. |
| Skills selectively discoverable | **PASS for config; runtime selection unverified** | OpenCode lazy skill convention and existing shipped-set checks remain. |
| Documented native integration | **PARTIAL** | Official API used; actual OpenCode 2 loading/compaction not verified. |
| Simple tasks avoid orchestration overhead | **PASS by design, live overhead NOT MEASURED** | No default multi-agent, state creation only when justified, helper runs only at compaction; real latency unmeasured. |
| New critical behavior has automated tests | **PASS** | Packet bound/read-only/stale selection and V1/V2 source contract tests. |
| Evaluation reproducible and honest | **PASS for deterministic protocol; live A/B/C/D NOT EXECUTED** | Three fixtures, three repetitions, explicit output; limitations are reported. |
| Install, upgrade, diagnostics and rollback remain functional | **PASS** | Full lifecycle integration suite passed, including 2.6.1 upgrade and failure recovery. |
| Documentation reflects code | **PASS** | Release-doc/inventory verifier passed; versioned release, migration, architecture decision, compatibility and report included. |
| Dependencies/components justified | **PASS** | No new runtime/service/package/schema; small V2 adapter and fixture reuse existing components. |

## Deliberately not implemented

- No default subagents, role orchestration, MCP servers, external task DB, persistent service, model router, vector store, AST index, or OpenCode fork: each duplicates native/existing capabilities or adds cost without measured need.
- No SkillEvaluator dependency: its availability/integration with this OpenCode harness is not established, and Anvil already has independent deterministic fixture runners. The missing CLI was not installed.
- No mandatory mutation testing, whole-repository scan, language-specific linter or exhaustive review for local changes. Anvil keeps quality checks risk-based and adapter-friendly.
- No automatic task-state creation at every prompt and no transcript persistence. Durable models remain explicit and proportional to task risk.
- No claim that source-checked V2 hooks work on every V2 patch. Unsupported APIs fail soft.
- No live model run, causal skill ablation or token/cost claim without a selected model/provider and isolated treatment design.

## Risks and follow-up

1. Run a live OpenCode 2 plugin smoke on a supported build: one active task, one compaction, then verify ID/revision/criteria/decisions/stale state and resume without duplicate execution.
2. Design and pre-register orthogonal A/B/C/D profiles. Keep the model, provider, prompt, fixture, timeout and environment identical; record independent acceptance, architecture checks, actual skill activation, usage tokens/cost, elapsed time, retries and human intervention. Repeat enough times for variance; review failures blind where feasible.
3. Add real multifile bug/refactor/interruption cases to the live evaluation only after its semantic rubric and treatment isolation are stable. Existing deterministic fixtures cover protocol contracts, not agent coding competence.
4. Measure compaction subprocess latency on representative small/large task states and verify behavior when the helper is missing or times out. The hard bound is 2 seconds; current source tests do not establish a P95.
5. Revisit AST/LSP/repository-map support only if measured search/navigation failures justify the maintenance and context cost.

## Production-readiness recommendation

**NOT FULLY CERTIFIED.** The implementation is a backward-compatible candidate with passing deterministic engineering evidence, provided the final unit, managed-inventory, documentation, and full offline suite gates all pass. A controlled release may proceed with the documented known limitation that native OpenCode 2 compaction and live model performance are unverified. Do not make model-quality, latency, token-efficiency, cost, or A/B/C/D superiority claims until those exact evaluations run and are independently reviewed.
