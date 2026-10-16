# Anvil 2.0 to 2.1 migration

Anvil 2.1 separates Anvil's product release from the OpenCode runtime generation. This lets a supported OpenCode 1 installation receive Anvil 2.1 without installing OpenCode 2.

## Normal upgrade

Inspect the current setup, review the staged plan, then upgrade Anvil:

```bash
make inspect
make upgrade DRY_RUN=1
make upgrade
make doctor
make capabilities
```

`make upgrade` preserves the installed OpenCode major while updating Anvil and the runtime release within that same major. For OpenCode 1, Anvil installs the V1 config adapter and file-search/direct-read fallbacks. For OpenCode 2, Anvil retains its V2 adapter, native memory-search plugin, Reference, and structured stats.

The dry run stages the exact target release, builds/audits its config and rehearses on copies of user config, OpenCode data/state, and Anvil Markdown memory. It stops before live backup or mutation. A normal upgrade proceeds only after rehearsal; it then verifies a complete backup, installs the tested candidate, runs doctor, and rolls back on postflight failure.

## Explicit runtime migration

OpenCode major changes are separate from a normal Anvil upgrade. When organizational policy permits a runtime move, request it directly:

```bash
make migrate-runtime OPENCODE_MAJOR=2 DRY_RUN=1
make migrate-runtime OPENCODE_MAJOR=2
```

Use `OPENCODE_MAJOR=1` to migrate back to the supported OpenCode 1 profile. The requested major must be supported and differ from the installed major. Runtime migration uses the same exact candidate, adapter config, copied-state rehearsal, verified backup, postflight doctor, and rollback path as the product upgrade.

## Runtime policy

`config/runtime-policy.json` declares supported majors, minimum versions, a first-install default, and that automatic major upgrades are disabled. The current default is OpenCode 1. An existing OpenCode 2 installation remains on OpenCode 2 for `make upgrade` and `make reforge`; a first install follows the policy default.

`make capabilities` reports the detected adapter and feature fallbacks. `FORMAT=json make capabilities` returns the machine-readable profile. See [runtime compatibility](../runtime-compatibility.md) for the tested versions and feature matrix.

## Memory compatibility

Memory remains human-readable Markdown under `$XDG_DATA_HOME/anvil/memory/`. Anvil does not rewrite historical memory files during upgrade or runtime migration. Both adapters run the same `/remember`, `/recall`, `/distill`, source registry, lexical aliases, provenance, and source freshness workflows. OpenCode 1 uses Python file search and direct file reads for named knowledge; OpenCode 2 adds the native search tool and Reference.

OpenCode config provider mappings are preserved when switching runtime schema: V1 `provider` fields are mapped into V2 `providers`, and V2 providers map back when rendering the V1 profile. Other files inside the managed OpenCode config tree are replaced by Anvil's staged profile; the verified backup retains the complete previous tree.

## Data, rollback, and limits

OpenCode data, authentication, sessions, and state are copied to a private isolated rehearsal and stored in verified backups as opaque files. Anvil does not read or mutate undocumented database tables. The target candidate starts against copied state through its own native stats command. Rehearsal does not authenticate to a provider or make a model request.

Run `make rollback` to restore the last verified config/runtime/data/state snapshot. Current Anvil Markdown memory remains portable and is archived separately before rollback. Runtime rollback restores the prior binary and files rather than attempting an in-place database downgrade.

Anvil 2.1 cannot enable capabilities absent from a runtime. OpenCode 1 has no Anvil native plugin or Reference, and its native stats are text rather than structured JSON. The fallbacks preserve the common workflow without claiming those native capabilities exist.
