# Testing

`make test` requires Linux or macOS, Bash, Python 3.11+, `tar`, and network access to the official npm registry for the stable OpenCode candidate. It resolves the candidate once, downloads the host package, verifies its published integrity, and keeps all candidate runtime data under temporary HOME/XDG paths. Windows users can run under WSL.

## Candidate smoke test

The exact official candidate is run with isolated `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME`. The test validates native V2 config loading and checks the actual runtime registration of the Anvil primary agent, `/remember`, `/recall`, `/distill`, five skills, `anvil-core`, `anvil_memory_search`, and the `anvil-knowledge` Reference. It does not make a provider/model request or open an interactive TUI.

## Regression and memory checks

The deterministic checks parse shell/Python sources, audit the V2 config and V1 fixture, check release documentation consistency, assert model neutrality, disabled built-in agents, denied subagents, empty MCP defaults, the narrow plugin scope, and scan repository files for a small set of accidental secret signatures.

V1-format Markdown fixtures are searched with `PATH` deliberately lacking `rg`; tests verify the original file hash remains unchanged. Memory checks also cover validation counts, accent-insensitive aliases, bounded retrieval, explicit writes, provenance, duplicate handling, and no-write search behavior. `/distill` fixtures cover current doc/code/test corroboration, stale documentation versus active behavior, an unreferenced legacy implementation, normative policy versus implementation conflict, historical claims, documented `numPartitions = 8` versus active configured/tested `16`, and a Markdown reference to an unavailable image. The source registry checks hash drift and unchanged-source skip results.

## Lifecycle and recovery

Lifecycle integration uses temporary HOME/XDG trees and a small executable wrapper that reports a representative V1 version before delegating runtime operations to the exact OpenCode 2 candidate. It tests supported V1 provider/config conversion, isolated rehearsal with copied config/data/state/memory, repeated idempotent reforge and PATH handling, successful upgrade, automatic rollback after injected failures, manual rollback, opaque data/state restoration, and Anvil memory preservation.

Failure injection covers candidate runtime validation failure, rehearsal abort, backup creation failure, failure after a verified backup but before mutation, post-config failure, and post-upgrade doctor failure. Tests assert that pre-mutation failures do not modify live fixture state and that post-mutation failures restore the captured config/runtime/data/state snapshot. No test command is given the developer's real OpenCode directories as its active destination.

## Stats and version documentation

The stats formatter is checked against structured native OpenCode JSON including model, token, and cost values. No-usage behavior is supported by the script's empty native result path. The version documentation validator checks `VERSION`, the matching changelog and version history, capability matrix, migration guide, release guide, and OpenCode compatibility record.

## Limits

Rehearsal triggers OpenCode's native runtime/state handling through standalone stats and validates CLI/API discovery. It does not verify terminal rendering, live provider authentication, every provider integration, or a paid model request. Database files are copied and restored as opaque files; Anvil does not read or mutate internal SQLite schemas. Distillation is model-guided semantic synthesis, so deterministic fixtures check workflow instructions, provenance, evidence labels and registry behavior, not the quality of a future model's reasoning.
