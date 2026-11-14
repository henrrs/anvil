# Local OpenCode Engineering Evaluation

- **Evaluation:** `anvil-engineering-local-2026-11-14`
- **Status:** **BLOCKED — NOT CERTIFIED**
- **Runtime:** OpenCode 1.19.5 · `openai/gpt-6-luna` · HIGH
**Baseline:** Anvil 2.20.0 · `b09d9651952aef9f6a296b559cf38c08c320ca74`

## Result

The OpenCode executable found on PATH ran with the existing user environment and a temporary project that denied every agent tool. It returned one `UnknownError` event and exit code 1 after 2.197 seconds. No assistant response, token telemetry, cost telemetry, or tool call was observed. The event and error text were not retained.

The smoke did not satisfy the gate for a code challenge. No challenge or full benchmark was started. The prior two failed isolated-profile smoke attempts remain in their historical diagnostic report; this local attempt is a separate evaluation record.

## Active Anvil profile

`make inspect` reported OpenCode 1.19.5 usable, but Anvil was not installed or recorded. Its global profile was not recognized as an Anvil profile; no Anvil agent, skills, plugin, commands, or managed profile were present. `make reforge DRY_RUN=1` stopped with **Unsafe managed state requires manual review before reforge** and applied no changes. There is no verified rollback snapshot. The official activation path is therefore blocked pending the manual profile review required by the lifecycle preflight.

## Preservation

- The prior Evaluation Lab source, fixtures, private graders, budgets, reports, and safe traces are preserved in `~/.local/share/anvil/evaluations/legacy-lab-2026-11-14/evaluation-lab.tar.gz` (SHA-256 `31975b66ec3cd6e869bce03cd1e3baca6cbe76e06c996ffdc3660e31cd82d300`; 103 files verified). The previous Makefile is preserved alongside it as a separately hashed supplement.
- The immutable Anvil 2.20.0 baseline remains in `~/.local/share/anvil/evaluations/anvil-engineering-live-2026-11-14/`; its 713-file manifest and archive hashes remain valid.
- Historical evaluation and diagnostic reports were not changed.

## Safety and limits

The local runner uses the installed OpenCode CLI and inherits the real HOME/XDG/provider settings. It does not open, copy, or modify credential files or the user's OpenCode profile. A temporary project permission overlay scopes model edits to disposable fixtures; the shell wrapper uses Landlock, denies network access from model shell commands, and routes Anvil task state into the temporary run directory. Private graders remain outside model workspaces. The registered per-invocation time, step, token, output, and total-call ceilings are unchanged; automatic retries remain disabled.

For a future fixture run, Anvil plugin tools stay denied to protect durable user memory and external Anvil state. The evaluation can measure the installed agent and skill behavior under those restrictions, but it will not score plugin side effects.

**Verdict:** No engineering score is available. Resume only after the local OpenCode smoke returns text and telemetry, the disposable fast-control challenge passes its independent grader, and the official Anvil profile can be activated without overwriting unreviewed user files.
