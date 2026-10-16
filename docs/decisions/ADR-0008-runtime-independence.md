# ADR 0008: Separate Anvil releases from OpenCode runtime majors

- **Status:** Accepted
- **Date:** 2026-10-16

## Context

Anvil 2.0 coupled the product release and `make upgrade` flow to OpenCode 2. Organizations that could not approve an OpenCode major migration could not receive Anvil improvements, including runtime-independent memory and source workflows.

## Decision

Support OpenCode 1.x and 2.x through small native config/runtime profiles, central local runtime discovery, and one capability adapter. `make upgrade` updates Anvil only and preserves the exact validated runtime without release lookup or network access. `make update-runtime` explicitly updates within the current major. `make migrate-runtime OPENCODE_MAJOR=N` explicitly changes runtime major. `make reforge` reuses an existing healthy supported runtime and provisions the policy default only when OpenCode is absent. Runtime-changing operations retain candidate verification, isolated rehearsal, a complete backup, postflight doctor, and rollback.

Keep common Anvil commands, skills, Markdown memory, source registry and distillation shared. Gate the native V2 plugin, Reference, ordered permissions and structured stats by actual runtime capabilities. An unavailable native feature must use the documented fallback or report unavailable without blocking unrelated Anvil features.

## Consequences

Anvil and OpenCode versions can now differ. Release resolvers maintain separate stable lines and are reachable only from fresh runtime provisioning, `make update-runtime`, and `make migrate-runtime`. A blocked release service cannot prevent an Anvil product upgrade. Runtime updates use official artifact digests, and a runtime-major migration requires an explicit target and is reversible from the complete snapshot. OpenCode databases stay opaque; migration rehearsal operates only on copied data/state. Local runtime state is a validated cache, never trusted without rechecking the executable.

The runtime policy is deliberately small JSON with supported majors, minimum versions, first-install default, and automatic-major-upgrade behavior. Runtime behavior is not spread through product commands as independent version policy.
