# Adaptive engineering evaluation and evidence

## Method

The structured baseline is Anvil 2.9.0 at commit `6b6401d`. The adaptive candidate is the current 2.10.0 source. The baseline protocol was replayed from a clean source archive; the candidate uses the same ingestion and unrelated scheduler fixtures, explicit models, injected boundary violations, interrupted milestone and recovery sequence. Each side ran three times. Raw protocol evidence is in [`adaptive-baseline.json`](../evals/engineering/adaptive-baseline.json) and [`results.json`](../evals/engineering/results.json).

The paired activation rubric has 18 task cases across the complex ingestion project, an unrelated utility service, Spark, and System Design. It covers local bug/validation/field changes, contracts, architecture ownership, state/migration, a new runtime, resume, Spark diagnosis and explicit deep review. Each case includes the expected evidence branches, including when those branches should stay dormant. [`adaptive.py`](../evals/engineering/adaptive.py) compares its deterministic route helper with the prior 2.9 activation rule and confirms the rubric. It does not run an LLM or establish that a model follows the branch rubric.

## Paired results

| Fixture | Baseline quality | Adaptive quality | Architecture checks per replay | State writes per replay | Verification commands per replay | Mean replay time |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Ingestion | 3/3 complete; 12/12 required; 4/4 invariants PASS | 3/3 complete; 12/12 required; 4/4 invariants PASS | 20 → 4 (**−80%**) | 7 → 7 | 4 → 4 | 0.714 s → 0.751 s |
| Scheduler | 3/3 complete; 7/7 required; 2/2 invariants PASS | 3/3 complete; 7/7 required; 2/2 invariants PASS | 8 → 2 (**−75%**) | 6 → 6 | 3 → 3 | 0.456 s → 0.489 s |

The architecture-check reduction comes from evidence scope and milestone gating: an unrelated or unchanged invariant retains its valid PASS, while a changed invariant is reevaluated at the relevant completed milestone. All final required coverage and invariants still pass. State-write counts are actual `store.save/update` calls made by this deterministic replay protocol; they are not an estimate of how many helper commands or writes a live agent session would issue. The helper's atomic generation, locking, revision, and recovery semantics are unchanged.

The replay times are subsecond harness timings and show no reliable latency improvement. They should not be interpreted as model/user task speedups.

The 2.9 release had separate official OpenCode 1.19.3 and 2.0.31 profile checks. Anvil 2.10 makes no runtime/config adapter change; this release's mandatory suite validates generated V1/V2 profiles with local runtime fixtures. No new official binary smoke check was run for 2.10.

## Task-local activation results

| Metric | Structured 2.9 rule | Adaptive 2.10 helper/rubric | Result |
| --- | ---: | ---: | --- |
| Paired task cases | — | 18 | All 18 routes matched authored expectations |
| Low-risk cases falsely routed to long-horizon | 8 | 0 | Project counts and long context no longer force expansion |
| Cases needing expansion but missed | 8 | 0 | Explicit contract/state/boundary/resume/domain-risk signals are recognized |
| Always-loaded kernel | 3,930 bytes | 3,338 bytes | −592 bytes (−15.1% by source size) |

The 18/18 result validates only the deterministic helper route against the case rubric. Deeper branch selection remains semantic model judgment. The byte delta is a source-size comparison, not a provider token or latency measurement.

## Metrics not measured

No OpenCode executable or configured live model runner is available in this environment. Therefore the following remain **NOT MEASURED**:

- Autonomous success and semantic quality on the adaptive task prompts.
- Tool calls, files read, test commands selected by a model, persistent writes in a live session, and user-task elapsed time.
- Provider-reported context/tokens and real-world task completion latency.
- Live Spark/Databricks workload performance or production ingestion-engine behavior.

The deterministic long-horizon protocol tests preserve coverage, architecture evidence, interruption/resume behavior and state-write counts; they cannot substitute for those model measurements. The case rubrics are ready for future paired live evaluation under the same OpenCode binary, model, provider budget and isolated fixture. No performance claim is made from hidden reasoning, printed steps, or protocol timings.

## Reproduction

```bash
python3 tests/engineering.py
python3 evals/engineering/run.py --mode replay --repeats 3 --output /tmp/anvil-adaptive-replay.json
python3 evals/engineering/adaptive.py --output /tmp/anvil-adaptive-routes.json
```

The optional OpenCode harness remains available for the explicit long-horizon ingestion/scheduler fixture:

```bash
python3 evals/engineering/run.py --mode live --fixture ingestion --repeats 3 \
  --opencode /absolute/path/to/opencode --model PROVIDER/MODEL --major 1 \
  --profile full --output /tmp/anvil-live-eval.json
```

It uses temporary HOME/XDG roots and does not copy auth state. Provider authentication must be supplied through supported environment configuration. It records only bounded tool-call counts, numeric token usage when the event schema exposes it, output digest and acceptance results; private reasoning and transcripts are not retained. Current live task behavior was not run here.

## Ablation and assurance

The offline comparison ablates the previous repository-count activation rule and the previous all-invariants-at-each-checkpoint behavior against task-local signals and scoped milestone checks. Progressive requirements/Work loading and semantic domain-skill selection need model execution for a causal ablation, so they were not scored. Existing requirement models, architecture invariants, Work state, stale detection, crash-safe writes, completion gates, System Design and Spark references remain available; new negative cases require them to stay dormant for local work.

Mandatory release validation is the offline `make test` suite, including existing lifecycle/runtime fixtures and long-horizon quality/resume regressions. The 2.9 suite record remains in [`release-evidence.json`](../evals/engineering/release-evidence.json); this release's result is recorded in [`adaptive-release-evidence.json`](../evals/engineering/adaptive-release-evidence.json). OpenCode 1/2 runtime policy and generated profile structure are unchanged; this release requires no runtime migration.
