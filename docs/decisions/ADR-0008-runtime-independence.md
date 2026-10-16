# ADR 0008: Separate Anvil releases from OpenCode runtime majors

- **Status:** Accepted
- **Date:** 2026-10-16

## Context

Anvil 2.0 coupled the product release and `make upgrade` flow to OpenCode 2. Organizations that could not approve an OpenCode major migration could not receive Anvil improvements, including runtime-independent memory and source workflows.

## Decision

Support OpenCode 1.x and 2.x through small native config/runtime profiles and one central capability adapter. `make upgrade` and `make reforge` preserve an existing supported OpenCode major; a first `make reforge` follows the policy default. `make migrate-runtime OPENCODE_MAJOR=N` is the only operation that changes the runtime major. Every lifecycle operation retains candidate verification, isolated rehearsal, a complete backup, postflight doctor, and rollback.

Keep common Anvil commands, skills, Markdown memory, source registry and distillation shared. Gate the native V2 plugin, Reference, ordered permissions and structured stats by actual runtime capabilities. An unavailable native feature must use the documented fallback or report unavailable without blocking unrelated Anvil features.

## Consequences

Anvil and OpenCode versions can now differ. Runtime resolvers maintain separate stable lines and use their official artifact digests. A runtime-major migration remains possible but requires an explicit target and is reversible from the complete snapshot. OpenCode databases stay opaque; migration rehearsal operates only on copied data/state.

The runtime policy is deliberately small JSON with supported majors, minimum versions, first-install default, and automatic-major-upgrade behavior. Runtime behavior is not spread through product commands as independent version policy.
