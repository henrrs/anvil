# Local OpenCode Live Evaluation

The live engineering path runs the OpenCode executable already installed on the host. It inherits the current `HOME`, XDG directories, provider setup, and authentication. The evaluator does not open or copy credential files and does not create a parallel OpenCode profile.

## Run order

```bash
make eval-engineering-model MODE=smoke
make eval-engineering-model MODE=challenge TREATMENT=native-opencode FIXTURE=fast-control
make eval-engineering-model MODE=challenge TREATMENT=anvil-active FIXTURE=fast-control
make eval-engineering-model MODE=suite TREATMENT=anvil-active
```

The smoke must return assistant text plus token or cost telemetry. The disposable `fast-control` challenge must pass its independent grader before the suite starts. A failed smoke or challenge stops the sequence; automatic retries are disabled. A later evaluation after an external provider/profile change needs a new evaluation ID, a matching frozen budget config, and a fresh budget-state path; the original consumed record stays intact.

`TREATMENT=anvil-active` requires the installed profile to resolve an Anvil agent, an Anvil plugin with an available Anvil tool, Anvil skills, and an Anvil-scoped instruction source. A repository checkout by itself does not satisfy this check. Before the challenge, the runner fingerprints the effective agent definition and confirms the temporary permission overlay did not replace its content. If Anvil is missing, inspect with `make inspect` and preview the official activation path with `make reforge DRY_RUN=1`. Run activation only when that preflight confirms the user-owned profile can be preserved.

## Isolation and data handling

- Fixture repositories, their OpenCode project permission files, and per-fixture Anvil task state are kept under the temporary evaluation directory.
- The private grader stays in the repository and is executed by the evaluator after the model process; only its exit status, byte count, and diagnostic digest are retained.
- OpenCode's normal file tools are restricted to the fixture, plus the exact Anvil skill/helper paths and the state subtree for that fixture. Direct file edits to the temporary `opencode.json` and `.git` are denied. Shell commands can alter only the disposable fixture repository and its isolated evaluation state.
- Model shell commands use the fixture-scoped Landlock wrapper. It strips inherited environment variables before starting the shell, keeps the host's real HOME and XDG config/data paths, routes only Anvil's per-task state to a private directory under the temporary run root, permits writes only to the fixture and that state subtree, and denies network syscalls. The OpenCode process itself retains the real HOME/XDG configuration, authentication, and provider network access needed for inference.
- The project overlay changes tool permissions and the shell executable only; it does not set provider endpoints or API keys. Native treatment uses OpenCode's built-in `build` agent and `--pure`; the Anvil treatment uses the `anvil` agent from the installed profile.
- Anvil plugin tools are resolved during profile inspection but denied during fixture runs. This prevents the agent from reading durable user memory or calling tools that could change external Anvil state; the suite therefore does not score plugin side effects.
- Traces retain event types, counts, token fields, safe error classes, and hashes of session/run identifiers. They omit prompt/response text, tool arguments/results, stderr contents, credentials, and hidden grader diagnostics.

The global per-call step, time, output, token, concurrency, retry, and total invocation ceilings remain those in the frozen evaluation config. `budget-state.json` tracks consumed calls. The 2.20.0 baseline, previous reports, and legacy runner are retained; the previous isolated-profile path is available only as `make eval-engineering-model-legacy`.

Native runs made after Anvil is installed use `--pure` and the built-in `build` agent, but OpenCode may still include global instructions. Such runs are labeled with the active profile inventory and should be treated as descriptive if Anvil instructions remain in the context.

## Run record: 2026-11-14 auth refresh

Evaluation ID: `anvil-engineering-local-2026-11-14-auth-refresh-01`. Its budget and result history are separate from all earlier evaluation IDs. The immutable Anvil 2.20.0 baseline and legacy lab were retained in durable storage.

The local OpenCode executable is version 1.19.5. After the user renewed OpenAI authentication, `opencode run --model openai/gpt-6-luna --variant high` returned assistant text and token telemetry. The expired token is a **probable** explanation for the previous `UnknownError`; it is not proven as the cause.

The new-ID smoke passed in 5.688 seconds with 1,078 input, 7 output and 56 reasoning tokens. Cost telemetry was reported as zero, but billing semantics were unavailable, so monetary cost is not measured. Native `fast-control` passed independent acceptance in 74.222 seconds with 13,213 input, 2,318 output and 553 reasoning tokens, 15 completed tool calls, and no failure. This single native run is descriptive and does not establish statistical performance.

The installed OpenCode profile was not Anvil-active: it had no Anvil agent, plugin, skills, or Anvil instruction source. The repository checkout alone was not counted as an active Anvil treatment. `make inspect` classified the machine as `PARTIALLY_INSTALLED` with an external, unmanaged user profile and seven symlinks preserved. No Anvil benchmark was run against this profile.

The first authorized `ANVIL_YES=1 make reforge` attempt staged the profile, then the Analytics service failed to start. OpenCode 1.19.5's `serve` command rejects the existing global OpenCode database because its valid SQLite schema has `session_v2` but no `session` table. This does not establish database corruption; its SQLite integrity check was `ok`. Lifecycle automatically restored its degraded pre-operation baseline. The external config was then checked against the durable pre-operation inventory: all 3,932 nodes, contents, modes and symlink targets matched, and the Anvil profile remained inactive.

The corrective working-tree change starts the real OpenCode executable with `OPENCODE_DB` pointed at the Anvil-owned Analytics state directory. It retains the current HOME, XDG paths, OpenCode configuration and authentication, and leaves the user's default OpenCode database untouched. The direct integration smoke passed OpenCode health and session creation with this isolated database. Lifecycle now snapshots that Anvil-owned database with SQLite's online backup API and checks integrity without inspecting its tables or messages. This fix is not installed on the user profile.

Validation: 170 Analytics unit tests passed (3 physical certifications skipped because pinned DuckDB/PyArrow dependencies were unavailable); `make test-lifecycle` passed all offline checks; the real OpenCode server/database smoke passed. At the time these results were captured, the actual release installer had not been rerun after the code change: release integrity requires modified release-owned files and their manifest to match the committed checkout. The then-active instruction prohibited commit/push, so the Native-vs-Anvil comparison, full suite, diagnostic improvement loop, and regression report remained pending at that point.
