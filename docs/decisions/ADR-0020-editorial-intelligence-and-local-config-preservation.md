# ADR-0020: Editorial judgment and local configuration preservation

**Status:** Accepted

**Release gate:** The 2.12 candidate is **NOT RELEASE READY** until the real presentation benchmark and live-model responsiveness evaluation are completed.

**Date:** 2026-10-30

## Context

Anvil 2.11 already separated artifact contracts, deterministic rendering/review, and the lazy `anvil-communication` skill. It did not give the model concise guidance for missing comparison context, materiality, editorial compression, chart skepticism, composition, or information-bearing motion.

Lifecycle operations already staged a target tree and maintained a managed-file manifest. The shared `opencode.jsonc` profile had a null digest, but its merge preserved providers, selected disabled agents, and CLI/TUI preferences only. Rebuilding could remove user plugins, MCP servers, references, active custom agents, unknown profile settings, and local runtime preferences. Backups also archived unowned trees such as package-manager content, while rollback replaced the entire config directory and could discard user changes made after the snapshot.

## Decision

- Keep communication judgment in the artifact-only skill. Add short guidance for evidence context, observed change versus materiality, finding/insight/implication, reduction, semantic relationships, chart value, annotation, whitespace, composition, and temporal motion. Do not add a deterministic editorial rule engine or load this material for ordinary coding tasks.
- Extend the existing `.anvil-managed.json` config ownership section additively. It records Anvil-owned top-level keys, shipped agent names, the V2 Anvil plugin identifier, and Anvil references. Existing schema-1 manifests without the additional fields remain valid.
- Treat `opencode.jsonc` as a shared file. Update Anvil-owned profile fields while merging provider settings, external plugin entries/config, MCP, user references, custom agents, preferences, and unknown keys. Convert supported V1/V2 provider, plugin, MCP, and agent fields during explicit runtime migration. Refuse incompatible plugin config shapes rather than replace them.
- Snapshot only Anvil-managed files, the shared OpenCode profile, and CLI/TUI preferences. Leave unrelated external files in place; retain the existing private archive permissions.
- During rollback, restore the snapshot into staging, merge current user-owned files and shared profile settings, and atomically activate the result. A path that is user-owned now but Anvil-owned in the prior profile is a manual-review conflict; the live config is left intact. Files outside the OpenCode config directory are not lifecycle inputs or outputs.
- Keep Make targets and OpenCode runtime behavior unchanged. Retain the source migration window for Anvil 2.6.x installations.

## Responsibilities

| Responsibility | Owner | Must not own |
| --- | --- | --- |
| Artifact interpretation, materiality, visual selection, composition | `anvil-communication` skill + model | Deterministic lifecycle or renderer policy |
| OpenCode shared profile merge and runtime field conversion | `configure.py` | Files outside the configured OpenCode config directory |
| File ownership, manifest, selective snapshot and rollback reconciliation | `managed_config.py` and existing lifecycle shell flows | User-owned config values or external machine files |
| Geometry, serialization and structural validation | Existing renderer/configure/review code | Editorial truth or aesthetic acceptance |

## Consequences

- Normal config upgrade/rebuild cost follows Anvil-owned file count rather than all files below the OpenCode config root.
- User changes inside `opencode.jsonc` survive upgrades and reforge. User changes made after a snapshot survive rollback where ownership boundaries do not conflict.
- Package repositories, proxy/certificate settings, shell configuration, Databricks profiles, and credentials outside the OpenCode config path remain untouched.
- Configuration comments and original formatting are not preserved when a structured `opencode.jsonc` merge is serialized. Values and unknown keys are preserved. Unsupported or malformed shared config fails before live replacement.
- Semantic artifact cases remain model-evaluation inputs; offline fixture integrity is not claimed as a live-model quality result.

## Verification

Isolated HOME/XDG lifecycle tests cover first use with an external OpenCode profile, V1/V2 transitions, external plugins/MCP/references, active custom agents, unknown keys, local package/proxy/certificate/shell files, dry-run immutability and redaction, selective backup content, post-upgrade user edits through rollback, and reforge preservation. The complete offline release suite is required before release readiness.
