# Testing

`make test` requires Bash, Python 3.11+, `tar`, and the standard system utilities used by Anvil. It makes no external OpenCode, Databricks, or model calls. Local OpenCode 1/2 fixtures and a fake Databricks CLI validate runtime and adapter contracts; all lifecycle paths use temporary HOME/XDG roots. Windows users can run the suite under WSL.

## Offline runtime and configuration checks

OpenCode fixtures validate the supported OpenCode 1.18.18 and 2.0.0 profile shapes, config loading, agent/command/skill discovery, plugin/Reference behavior, and runtime-specific capabilities. These are adapter contract fixtures, not real OpenCode binaries. The suite audits generated OpenCode 1 and 2 config, checks model neutrality, single-agent policy, denied subagents, empty MCP defaults, plugin scope, and scans text files for accidental secret signatures.

## Databricks checks

`tests/fixtures/bin/databricks` returns deterministic Anvil profile, identity, cluster/warehouse, execution, permission, and system-table responses. Tests cover clean Anvil-owned profile creation, external profile isolation, legacy state migration, auth strategy selection, secure config/state persistence, environment isolation, resource selection, stopped-resource approval, command context cleanup, timeout cancellation, SQL state/result bounds, mutation rejection, system-schema discovery, FinOps evidence cases, and query recipe contracts. Fixture logs contain endpoint names and bounded request metadata without Python source, SQL text, credentials, or result payloads.

No fixture contacts a real Databricks workspace. Passing these tests validates the adapter's offline behavior and API request/response contract, not a live connection.

## Memory, source, and lifecycle checks

V1-format Markdown fixtures are searched with `PATH` deliberately lacking `rg`; tests verify the original file hash remains unchanged. Memory tests cover validation, status/confidence/aliases, accent-insensitive multilingual retrieval, bounded results, explicit writes, provenance, duplicates, source freshness warnings, and no-write search behavior. `/distill` fixtures cover documentation/code/test corroboration, stale docs versus active behavior, unreferenced legacy code, policy/implementation conflicts, historical claims, source drift, idempotency, and unavailable images.

Lifecycle checks use local OpenCode wrappers and isolated HOME/XDG trees. They cover first-install runtime policy, repeated reforge, Anvil upgrade preserving OpenCode 1, dry runs, explicit runtime migration, verified rollback, provider conversion, opaque data/state restoration, and memory preservation. Failure injection covers candidate validation, rehearsal, backup creation, failures before mutation, post-config failure, and doctor failure after upgrade.

## Release, harness, and stats checks

The suite checks shell/Python syntax, runtime policy and capabilities, release documentation, the global harness budget and required invariants, skill use/do-not-use descriptions, query recipe constraints, the combined JSON capabilities shape, and the absence of the standalone legacy organization token in tracked or untracked repository text. The stats formatter is checked with a structured local fixture.

## Limits

The suite does not run a real model, contact a Databricks workspace, authenticate with a provider, or smoke-test live OpenCode release artifacts. Runtime install/upgrade still needs access to the official release source and verifies its published artifact digest. OpenCode database files remain opaque; Anvil does not inspect or edit undocumented SQLite schemas. Semantic distillation quality remains agent-guided and is not represented as benchmarked model behavior.
