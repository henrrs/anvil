# Anvil Live Software Engineering Evaluation

- **Evaluation:** `anvil-engineering-live-2026-11-14`
- **Status:** **BLOCKED — NOT CERTIFIED**
- **Date:** 2026-11-14
**Baseline release/commit:** Anvil 2.20.0 / `b09d9651952aef9f6a296b559cf38c08c320ca74`

## 1. Executive summary

The evaluation infrastructure, frozen fixtures, runtime selection, isolation preflight and offline validation completed. The live coding comparison did not: both OpenCode Native and Anvil 2.20.0 returned a terminal OpenCode `error` event before issuing a tool call or reporting token usage. Each call ended with exit code 1 after approximately 65 seconds.

The safe traces intentionally did not retain provider error messages. As a result, the shared failure can be identified only as an **unclassified OpenCode runtime/provider error**. The OpenAI credential was visible to both isolated CLIs, but `auth list` does not validate that a model request can complete. A prior model-selection smoke call succeeded; it does not establish that the later coding calls were healthy.

No model-quality diagnosis, Anvil-specific improvement, retest, holdout score, or causal comparison is justified by these observations. Further model calls were stopped. The results are **not evidence that Luna failed the tasks or that Anvil helped or hurt**.

## 2. Environment

| Item | Observed |
|---|---|
| OpenCode | 1.19.5; two installed executable paths reported the same version |
| OpenCode 2 | Not available; runtime compaction experiment not executed |
| Model | `openai/gpt-6-luna` |
| Variant / reasoning | `high` / `high`, resolved by each live preflight |
| Context / output cap | 32,768 / 2,048 tokens |
| Agent steps | 12 per invocation |
| Provider credential | OpenAI credential listed by both isolated CLIs; credential contents were not read or printed |
| Proxy environment | No HTTP(S)/ALL proxy variables were present in the host environment |
| Active Anvil installation | None. `make inspect` reported `Anvil installed: not recorded` and no managed OpenCode profile |
| Evaluated Anvil profile | Generated from the preserved 2.20.0 worktree into a temporary XDG profile; V1 core plugin loaded and model/permissions resolved |

The baseline is an exact detached worktree at `<temporary-evaluation-root>/baseline`. Its manifest is `<temporary-evaluation-root>/baseline-files.sha256`, with manifest digest `591f414649029e6e219b4c2d5c3ae0b0926badaeddb76f526b5f5e4f295bf266`. All manifest checks passed from the baseline worktree after validation. The development changes and reports remain in the main working tree; no reset, commit or push was performed.

The managed V1 plugin dependency was preseeded from a local read-only cache to prevent network package installation during trials: `@opencode-ai/plugin` 1.19.5, cache SHA-256 `d472d4801e68cdec500dc7e6ca9987b859ef4715303ae1ee626eaa78a22c30e2`. The live preflight confirmed that Anvil’s plugin loaded, Analytics tools were denied, MCP was empty, and external-directory access was denied.

## 3. Anvil baseline capabilities verified

Source and offline validation confirmed the 2.20.0 repository contains persistent Requirements, Architecture and Work state; FAST/STANDARD/DEEP workflows; scoped engineering skills; deterministic verification and recovery; and the optional V2 compaction adapter. The V1 runtime configuration and plugin were inspected and resolved in the isolated OpenCode 1.19.5 preflight.

The host itself has no Anvil installation to assess. Runtime behavior of the V2 compaction adapter remains unverified because no OpenCode 2 executable was found.

## 4. Benchmark design

The seven frozen primary/control scenarios are retry-policy root-cause debugging, behavior-preserving refactoring, multi-module ingestion, repository-contract/queue preview, long-horizon engineering, controlled interruption and recovery, and a FAST control. Two candidate-only holdouts cover atomic config recovery and API compatibility.

Visible fixture SHA-256 values and private grader SHA-256 values are frozen in `benchmarks.json` (manifest digest `d63043f942b1e9d224c83a2c8b9d73a61ba830d0d9aa615b1b591f06b224aee9`). The model receives only the visible fixture. Preparation asserts that private graders and private data are not copied into the model workspace. Grading runs outside the sandbox.

The sandbox combines bubblewrap, a Landlock shell wrapper, seccomp network denial for model shell commands, isolated HOME/XDG paths, read-only runtime/config inputs, and workspace-scoped writes. The OpenCode process retains provider access. Safe traces contain event types, identifiers, counters, token fields when emitted, and digests; they omit message text, reasoning and tool arguments/results.

## 5. Native OpenCode vs Anvil baseline

| Scenario | Native OpenCode | Anvil 2.20.0 | Candidate |
|---|---|---|---|
| retry-policy | **BLOCKED** | **BLOCKED** | NOT EXECUTED |
| refactor | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| ingestion | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| queue-preview | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| long-horizon | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| context-recovery | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| fast-control | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| holdout-atomic-recovery | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| holdout-api-compat | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |

Both attempted calls resolved the same model, high reasoning, context/output limits, and runtime. Native OpenCode emitted one error event and exited 1 after 64.744 seconds. Anvil emitted one error event and exited 1 after 64.687 seconds. Neither emitted a tool call, assistant text, token usage or cost telemetry. The fixture remained at its starter state; its mechanical grader returned FAIL, which is recorded but **is not a model-quality score** because execution never began.

Evidence: `native-baseline.json`, `anvil-baseline.json`, and their referenced `trace-metadata.jsonl` files. The exact provider/runtime error cause cannot be recovered from the retained metadata.

Because the same terminal error occurred under both treatments, further live calls were stopped rather than consuming more budget without a classifiable runtime. The remaining rows are not scored.

## 6. Failure analysis

| Finding | Evidence | Interpretation | Priority |
|---|---|---|---|
| Live request terminates before coding | One `error` event, no tool/text/token event, exit 1 in each treatment | Shared runtime/provider path is implicated; exact root cause is unavailable | P0 unblock live evaluation |
| Authentication is configured but not validated | `opencode auth list` exits 0 and lists OpenAI in both profiles | This proves local credential discovery only, not successful API access | P0 diagnostic |
| Error trace lacked a safe category | Original error message was not retained; historical result has no provider details | The initial trace preserved privacy but prevented diagnosis | P1 observability |
| No active host Anvil profile | `make inspect` reports no recorded Anvil install/profile | The evaluation correctly used the frozen repository-generated profile; it cannot claim to characterize the user's installed profile | P1 scope |
| No OpenCode 2 runtime | Discovery found only 1.19.5 executables | V2 native-compaction validation is unavailable | P2 follow-up |

The evaluation runner was updated to classify known HTTP/auth/quota/model/network failures without persisting their messages and to label an otherwise unknown terminal error. Synthetic stream checks confirmed that a secret marker in an error message is not written to the safe trace. The two historical events are therefore recorded as `UNCLASSIFIED_OPENCODE_ERROR`; no new model call was made to exercise the updated classifier.

## 7. Implemented evaluation improvements

The working tree contains the live evaluation controller and budget accounting, reproducible fixtures, isolated model workspace preparation, private-grader separation, bounded traces, secure plugin dependency seeding, controlled context-recovery interruption/resume tracking, and a safe error classifier. These are evaluation-lab changes. **No production Anvil component was changed**, because there is no completed model baseline from which to derive a targeted product improvement.

## 8. Before vs after

No valid before/after model comparison exists. The candidate treatment, all six remaining primary scenarios, the FAST control, and both holdouts were not executed. The observed terminal errors do not identify a defect in Anvil or in Luna’s coding ability.

## 9. Long-horizon assessment

**NOT EXECUTED.** No model task reached planning or implementation. The offline replays exercise state continuity and recovery deterministically; they are not live evidence of long-horizon model coding.

## 10. Context recovery

**Live interruption/resumption: NOT EXECUTED.** The runtime was OpenCode 1.19.5, and the controlled-recovery fixture was not reached. The offline suite passed its state, stale-evidence and compaction-packet tests. Those tests do not certify a live recovery or native OpenCode 2 compaction hook.

## 11. Engineering quality and offline validation

| Check | Result |
|---|---|
| `make test` | PASS — 169 tests, 3 skipped; lifecycle, install/upgrade/rollback, V1/V2 config, analytics and engineering contracts included |
| `make eval-engineering` | PASS — 3 deterministic fixtures × 3 repetitions; completion and injected-boundary checks passed |
| `make eval-analytics` | PASS — 148 offline certification checks |
| `make eval-analytical` | PASS — deterministic L1/L2 fixtures; no model run; historical 2.13 comparison unavailable |
| `make eval-analytical-semantic` | PASS — deterministic semantic gates; FAST/STANDARD/DEEP measurements completed |
| Python compile and synthetic sanitized-error checks | PASS |
| `git diff --check` | PASS |
| Frozen baseline manifest | PASS — all hashes match in the detached baseline worktree |

The analytical FAST/STANDARD/DEEP measurements are separate deterministic subsystem benchmarks. They do not demonstrate that Anvil improves general software-engineering performance with an LLM.

## 12. Performance and efficiency

| Metric | Observed |
|---|---:|
| Smoke invocation | 8.16 s; 3,216 input / 7 output tokens; 42 reasoning tokens |
| Native challenge call | 64.744 s; tokens unavailable; cost unavailable |
| Anvil challenge call | 64.687 s; tokens unavailable; cost unavailable |
| Challenge tool calls | None observed in either run |
| Total live CLI invocations | 3 of 27 (1 smoke, 2 challenge) |
| Observed total model tokens | 3,216 input / 7 output, all from smoke; failed-call usage unavailable |
| Observed wall time | 137.591 s across the recorded invocations |
| Monetary cost | **NOT MEASURED**. The smoke emitted numeric cost telemetry `0`; its billing meaning is unverified. |

Unavailable measures remain null/unavailable; they are not treated as zero.

## 13. Remaining weaknesses

- Provider/runtime error detail needs a safe, non-content diagnostic path before live coding can be resumed.
- No valid live native or Anvil task score exists.
- No candidate optimization or generalization evidence exists.
- One repetition was registered per treatment, so the failed retry-policy attempts were not retried inside this evaluation ID.
- OpenCode 2 compaction has source/offline coverage only, not runtime certification.
- A live coding result would still require independent semantic review; deterministic graders alone cannot prove design quality.

## 14. Final engineering verdict

**NOT CERTIFIED.** The evaluation infrastructure and repository validations pass, but the central question—whether Anvil improves reliable coding with Luna 6 HIGH—remains unanswered. The blocker is a shared, unclassified OpenCode error before work starts. Do not make a release or performance claim from the current live artifacts.

To continue, first restore a healthy OpenCode provider request path and expose only a sanitized error class (HTTP status/category, never message or credential). Start a new evaluation ID with the same frozen benchmark and an explicitly reviewed call budget; do not reinterpret this blocked run as a completed baseline.

## Reproduction and artifacts

The exact runtime/configuration and resource budget are in `config.json`; fixture and grader hashes are in `benchmarks.json`; invocations and token accounting are in `budget-state.json`; the two treatment outcomes are in `native-baseline.json` and `anvil-baseline.json`. Safe event traces are referenced by those result files. The model smoke trace is `smoke/trace-metadata.jsonl`.

No commit or push was made, as required by the evaluation specification.
