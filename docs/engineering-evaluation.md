# Engineering evaluation and evidence

Baseline: `bd8b21e`, Anvil 2.8.0. Its mandatory offline suite passed in 336.71 seconds before activation changes. The baseline has no structured engineering-state helper. `evals/engineering/baseline.json` records that observation; it does not claim that a model failed a coding task.

The candidate has two independent offline fixtures. The ingestion slice exercises generic contracts, environment input, source profiles, two local source types, two runtime capability labels, physical planning, sink/progress ordering, append-only history, stable-key output, duplicate recovery and architecture boundaries. The local scheduler exercises job intent, deterministic bounded selection, two injected handlers, retry ownership and acknowledgement/replay without data-system assumptions. Each fixture has a specification, explicit normalized models, a clean starter, behavior acceptance and reference implementation used only for protocol replay.

Three candidate replays per fixture completed successfully. Ingestion verified 12/12 required requirements and four individually reported invariants; scheduler verified 7/7 and two invariants. Each discards in-memory history during partial milestone 2, reconstructs state, inspects/reconciles partial effects and continues. Injected dependency leaks are detected. These are deterministic harness continuity/conformance results, not evidence that an LLM autonomously extracted or implemented those requirements.

| Observation | Baseline | Candidate |
| --- | --- | --- |
| Structured operational continuity after conversation loss | No native store | Objective, architecture, requirements, progress, blockers, evidence and next action reconstructed |
| Required-coverage completion gate | Agent judgment | Deterministic linked-evidence gate |
| Mechanical boundary checks | Project-dependent | Explicit scoped AST/text/file checks |
| Ingestion protocol replay | Unavailable | 3/3 successful; 12 required verified |
| Unrelated scheduler protocol replay | Unavailable | 3/3 successful; 7 required verified |
| Always-loaded AGENTS.md | 3,724 bytes | 3,930 bytes (+206, within the existing 4,200-byte gate) |
| Tiny-task state writes | None expected | None in direct-path regressions |
| Real-model success, tokens, exploration, latency, design quality | Not measured | Not measured |

The added permanent instruction addresses the demonstrated long-spec/compaction continuity failure and routes to lazy capability details. New skill discovery metadata also consumes context; exact provider token counts and real-model selection overhead were not measured. Reference bodies and state operations are not loaded/executed on startup. Deterministic task assessment uses already supplied scope signals and never scans a repository. No claim of reduced model tokens or improved autonomous completion follows from byte counts or replay timings.

Run mandatory regressions with `make test`. Run repeatable reports separately:

```bash
python3 tests/engineering.py
python3 evals/engineering/run.py --mode replay --repeats 3 --output /tmp/anvil-engineering-eval.json
```

The optional live harness starts clean fixture projects with a specified OpenCode binary/model and generated isolated config; it never changes the installed runtime or copies auth state. Supported provider environment authentication must be supplied by the caller. It checks implementation acceptance and boundary invariants, collects bounded numeric usage/tool telemetry where the event schema provides it, and discards transcript content. No private reasoning is logged. Unmeasured metrics remain null.

```bash
python3 evals/engineering/run.py --mode live --fixture ingestion --repeats 3 \
  --opencode /absolute/path/to/opencode --model PROVIDER/MODEL --major 1 \
  --profile full --output /tmp/candidate-model-eval.json
```

For a baseline use `--profile-root /path/to/baseline-checkout --profile base`. Other protocol profiles are `work`, `work-architecture`, `full-no-system-design`, and `full-no-deep-spark`. These are requested ablations, not proof that a model obeyed them; inspect observed behavior before causal attribution. The separate schemas/modules and domain references permit component comparisons without a production multi-agent/model-routing system. Repeat across models under comparable budgets where available.

`system-design-cases.json` supplies eight responsibility/pattern/failure/evolution cases, including justified and speculative abstraction. `spark-cases.json` supplies 13 evidence/mechanism cases covering JDBC, mapInArrow, Python/JVM, Arrow types, spill, shuffle, skew, source ranges, AQE, DataSource V2, Photon, Delta and missing evidence. Their rubrics require explicit semantic review; static wording tests do not prove depth. `review_cases.py` validates bounded response/adjudication contracts separately from substantive judgment.

Official OpenCode 1.19.3 and 2.0.31 artifacts were digest-verified and validated using generated candidate profiles in temporary HOME/XDG roots. Native config/agent/command/skill discovery passed; the V2 plugin and knowledge Reference passed. No external model, real Spark workload or Databricks workspace was exercised. Remaining external evaluation is explicit, optional, and not part of mandatory offline correctness. Release recommendation: READY WITH KNOWN LIMITATIONS. The final complete offline/lifecycle suite passed in 367.06 seconds; evidence is recorded in `evals/engineering/release-evidence.json`.
