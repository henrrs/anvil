# OpenCode Live Runtime Diagnostic

- **Evaluation ID:** `anvil-engineering-runtime-diagnostic-2026-11-14`
- **Status:** **BLOCKED — NOT READY**
- **Runtime:** OpenCode 1.19.5 · `openai/gpt-6-luna` · HIGH
**Date:** 2026-11-14

## Result

Two equivalent, no-tool native smoke attempts ended with an OpenCode `UnknownError`, exit code 1, after 66.926 s and 66.317 s. Neither produced assistant text, token usage, or tool calls. The second attempt used the new bounded log collector and still had no HTTP status, provider error code, or retry count to identify the cause.

The failure happens before task execution. This rules out shell tool execution as the trigger for this smoke: it used one agent step, a 256-token output cap, no configured shell launcher, an empty project, and denied all tools. It does **not** identify the provider failure itself.

The earlier evaluation remains unchanged under `anvil-engineering-live-2026-11-14`. Its native and Anvil `retry-policy` calls both failed before a tool call at about 65 s. This new diagnostic ID is separate and does not merge or replace those results.

## Evidence and endpoint interpretation

| Observation | Result | Meaning |
|---|---:|---|
| Native smoke 1 | `UnknownError`, exit 1, 66.926 s | No text, tokens, or tools |
| Native smoke 2 | `UnknownError`, exit 1, 66.317 s | Same failure after safe log capture |
| Provider/error metadata | provider `openai`; no HTTP status, code, or retry count | Cause remains unclassified |
| Direct GET `models.opencode.ai/api.json` | HTTP 200 | Catalog host is reachable from the host |
| Direct GET `api.openai.com/v1/models` without credentials | HTTP 401 | DNS, TLS, and HTTP are reachable; this does not validate the configured credential |

The only host found in the OpenCode runtime log was `models.opencode.ai`. OpenCode 1.19.5 uses that host to fetch its model catalog at `/api.json`; its provider code resolves inference separately from the configured base URL or the model’s API URL ([catalog fetch](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/models-dev.ts#L150-L169), [provider URL resolution](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/provider/provider.ts#L1701-L1721)). Therefore the log host is **not evidence that the inference request reached that host**. The actual inference destination was not exposed by the retained logs or resolved configuration.

The model catalog currently contains the `openai` provider and `gpt-6-luna` entry, and the generated profile has no custom provider base URL. Network probes used no credentials and did not inspect the auth file. They cannot establish whether the configured key is accepted or whether the inference request is rejected for another reason.

## Environment comparison

- The successful historical smoke used one step, 256 output tokens, and no custom shell launcher. Its original prompt was not retained, so this is an equivalent smoke, not a literal replay.
- The failed challenge configuration used 12 steps, 2,048 output tokens, a 2,813-byte project, and the Landlock/seccomp shell launcher. The current native smoke fails without that launcher or tool access, so those challenge-only settings are not required to reproduce this failure.
- The isolated profiles use the same read-only OpenCode auth-file bind and clear the child environment. Credential contents were not read or printed. No global auth or service was changed.
- The previous Anvil challenge loaded its managed V1 plugin and failed with the same pre-tool pattern as native. No Anvil smoke was started for this diagnostic ID because the native smoke hit the stop condition: an unclassified terminal error before any tool or token event.

## Correction and security

The evaluation runner now retains bounded, sanitized runtime metadata from JSON events and OpenCode debug logs: error type/code, HTTP status, provider, retry count, process and exit status, elapsed time, stage, endpoint origin, and safe identifiers. It keeps raw log bytes in memory only, writes hashes and allow-listed metadata to mode-`0600` traces, and removes each isolated OpenCode runtime store after extraction. A synthetic redaction check passed.

The temporary logs and databases from the old attempts were inspected through a metadata-only parser and removed. No raw prompt, response, reasoning, credential, header, or response body is retained in this diagnostic’s artifacts. The diagnostic prompt is supplied through `ANVIL_DIAGNOSTIC_SMOKE_PROMPT` and is not stored in the script or report.

No production Anvil component was changed. The exact runtime/provider cause is still unknown, so changing Anvil behavior would be unsupported.

## Baseline preservation

Before the diagnostic calls, the Anvil 2.20.0 baseline was copied out of `/tmp` to:

`$ANVIL_DATA_HOME/evaluations/anvil-engineering-live-2026-11-14/`

That durable directory contains a detached worktree at commit `b09d9651952aef9f6a296b559cf38c08c320ca74` and an independent `baseline.tar.gz` with SHA-256 `aa40c198b23e128dca4e39cb0a62d41df6b0263ea5b82ba35ef12732025e0630`. All 713 manifest hashes passed before and after the live attempts; the worktree remains clean.

## Decision

**BLOCKED.** Do not resume the full benchmark yet. The model/provider path still fails before coding in the native smoke, and the safe evidence has no status or error code to target. The current evidence does not justify an Anvil production fix or a quality conclusion. Preserve this report and the original blocked run as separate history; retry only after the provider/runtime failure can be classified.

## Artifacts and reproduction

- `metrics.json` — safe results, request limits, network probes, and baseline hashes.
- `budget-state.json` — two smoke invocations; zero observed tokens; no challenge invocation.
- `config.json` — explicit diagnostic budget and stop conditions.
- `diagnose.py` — bounded smoke/challenge controller; prompts are supplied externally through `ANVIL_DIAGNOSTIC_SMOKE_PROMPT`.
- Safe traces and isolated project directories are under `$ANVIL_DATA_HOME/evaluations/anvil-engineering-runtime-diagnostic-2026-11-14/runs/`.

These are the commands used for the archived diagnostic attempts:

```sh
python3 evals/engineering/live-diagnostic-2026-11-14/diagnose.py
```

The bounded diagnostic repeat used after adding log extraction was:

```sh
python3 evals/engineering/live-diagnostic-2026-11-14/diagnose.py --continue-after-log-capture
```

The archived run directories and budget state are intentionally retained, so this diagnostic ID refuses further attempts. Any new attempt needs a fresh evaluation ID and budget. No full benchmark, commit, or push was performed.
