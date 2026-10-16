# Testing

`make test` requires Linux or macOS, Bash, Python 3.11+, `tar`, and network access to the official OpenCode 1 GitHub release source and OpenCode 2 npm registry. It stages the current stable candidate for each supported major plus the OpenCode 1 compatibility floor `1.18.18`. Every candidate uses temporary HOME/XDG roots; Windows users can run the suite under WSL.

## Runtime candidate smoke tests

The exact OpenCode 1.18.18, latest stable OpenCode 1.x, and latest stable OpenCode 2.x candidates are each tested with isolated `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME`. OpenCode 1 validation checks its singular config, one Anvil primary agent, denied `task`, `/remember`, `/recall`, `/distill`, and all five skills. OpenCode 2 validation checks native config and the actual agent, commands, skills, local plugin/memory-search tool, and Knowledge Reference. No test makes a provider/model request or opens an interactive TUI.

## Policy, config, memory, and source checks

Deterministic checks parse all shell/Python sources; audit generated V1 and V2 profiles; exercise the runtime policy and capability maps; check reverse and forward provider conversion; validate release documentation; assert model neutrality, disabled built-in agents, denied subagents, empty MCP defaults, narrow plugin scope, and scan repository files for a small set of accidental secret signatures.

V1-format Markdown fixtures are searched with `PATH` deliberately lacking `rg`; tests verify the original file hash remains unchanged. Memory checks cover validation, status/confidence/aliases, accent-insensitive multilingual retrieval, bounded results, explicit writes, provenance, duplicate handling, changed-source freshness warnings, and no-write search behavior. `/distill` fixtures cover documentation/code/test corroboration, stale docs versus active behavior, unreferenced legacy code, normative policy versus implementation conflict, historical claims, source drift, idempotency, and unavailable images.

## Lifecycle and recovery

Lifecycle integration uses isolated HOME/XDG trees and representative OpenCode 1/2 candidates. It tests first-install runtime policy, repeated reforge, Anvil upgrade preserving OpenCode 1, both upgrade and runtime-migration dry runs, explicit V1-to-V2 migration, verified rollback, provider conversion, opaque data/state restoration, and memory preservation.

Failure injection covers candidate validation, rehearsal, backup creation, failure after a verified backup but before mutation, post-config failure, and post-upgrade doctor failure. Tests assert pre-mutation failures leave live fixture state unchanged and post-mutation failures restore the captured runtime/config/data/state snapshot. No test points the active destination at the developer's OpenCode directories.

## Stats and version documentation

The structured stats formatter is checked against native OpenCode JSON including model, token and cost fields. The OpenCode 1 adapter is smoke-tested through native text stats; missing-runtime stats guidance is also checked. The version documentation validator checks `VERSION`, `CHANGELOG.md`, Anvil 2.1 history, runtime capability matrix, migration guides, release guide, and compatibility documentation.

## Limits

Rehearsal starts each candidate against copied state through its native stats path and validates CLI/config discovery. It does not verify terminal rendering, live provider authentication, every provider integration, or a paid model request. Database files are copied/restored as opaque files; Anvil does not read or mutate internal SQLite schemas. Distillation is model-guided, so deterministic fixtures check evidence labels, workflow instructions, provenance and registry behavior rather than LLM reasoning quality.
