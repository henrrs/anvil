# Local OpenCode Evaluation Follow-up — 2026-11-14

## Scope and runtime

This checkpoint resumes the live engineering evaluation with the OpenCode installation already present on the machine. The selected runtime is OpenCode 1.19.5 with `openai/gpt-6-luna` and variant `high`. The requested treatment is the installed Anvil 2.20.0 profile.

Anvil 2.20.0 was already installed and passed its managed-profile checks. OpenCode's resolved metadata showed the Anvil agent, core plugin tools, eight Anvil skills, and global Anvil instructions. The evaluation did not need to install Anvil, run `reforge`, upgrade the runtime, or rebuild the user's profile. No credential file was opened, copied, or changed.

## Changes made

- Kept the Anvil-only upgrade rehearsal independent of personal OpenCode databases, runtime state, credentials, and Anvil memory. Its native stats probe uses disposable XDG data and state directories.
- Kept profile metadata checks on the real OpenCode configuration while directing their data, state, and cache to fresh temporary directories. These probes use an allowlisted environment without provider credential variables and request only agent/skill metadata.
- Added privacy-preserving failure diagnostics to the local evaluator. It records only bounded identifiers, status codes, failure categories, byte counts, and hashes; it does not persist stderr, log lines, prompts, responses, or reasoning.
- Scoped local log inspection to files modified during the current invocation so an old provider or network error cannot be attributed to a new smoke attempt. Local OpenCode database startup errors are classified separately from provider failures.

## Validation

`make test` passed after these changes. The run covered the full lifecycle/upgrade/rollback matrices, Anvil Engineering tests (27), Evaluation Lab tests (7), and the Analytics suite (170 tests, 3 skipped). The new evaluator regressions verify that credential-like strings and raw error messages do not appear in persisted diagnostics, stale log entries are excluded, and the local database startup error is not mislabeled as a provider failure.

## Live evaluation status

The earlier `auth-refresh-03` run remains a partial historical result: it completed a smoke and the Native `fast-control` challenge, but its configuration targeted Anvil 2.20.1 while the intended treatment was the installed Anvil 2.20.0. It is not counted as the resumed comparison.

The correctly targeted `auth-refresh-04` attempt reserved a fresh budget and started the smoke. OpenCode exited with code 1 after 0.648 seconds, before returning assistant text or token telemetry. No challenge was run, and no automatic retry was made. A separate read-only `opencode models openai` command then returned `Database is not empty and has no session table`. This is evidence of a local OpenCode state-store problem and a plausible explanation for the smoke failure, but the captured ID04 attempt did not retain enough per-process metadata to prove that they were the same failure.

The user-reported expired OpenAI token remains a prior probable cause, not a proven cause. The latest evidence does not establish that authentication is still failing; it points to a local CLI database startup issue that must be resolved before the evaluator can safely pass its smoke gate. No Native-versus-Anvil comparison, FAST acceptance run for ID04, or full-suite live evaluation is claimed here. The next benchmark remains gated on a successful Luna 6 High smoke with response and telemetry.

## Preservation and safety

Historical evaluation IDs and their budgets were not overwritten. Fixture repositories remain disposable and separate from the Anvil checkout. The local OpenCode configuration, authentication, runtime, and persistent data were not changed by the evaluator. This checkpoint makes no quality, latency, token-efficiency, or cost claim for the blocked resumed run.
