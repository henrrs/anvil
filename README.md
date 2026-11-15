# Anvil

**Anvil — A lean, model-agnostic OpenCode harness designed to maximize reliable task completion while minimizing unnecessary context and token usage.**

*Better harness. Better execution.*

Anvil provides the working environment around an existing model: focused instructions, skills, memory, tools, and execution rules. It does not create or route models. The model can change; the harness remains the stable surface on which work is shaped and verified.

The name refers to a blacksmith's anvil: the base that supports shaping and refining material. Anvil applies that idea to model-assisted engineering: **less noise → better context → disciplined execution → verification.**

```text
                 LLM
                  │
                  ▼
            Anvil harness
   context · skills · memory · tools
                  │
                  ▼
      more reliable task completion
```

Anvil currently supports **OpenCode 1.x**, with a minimum version defined in [runtime policy](config/runtime-policy.json). OpenCode remains responsible for models, providers, authentication, sessions, and runtime data. Databricks integration is optional.

## Install

Requirements: Linux or WSL, Bash, Make, Python 3.11+, and `tar`.

```bash
git clone https://github.com/henrrs/anvil.git
cd anvil
make inspect
make reforge
make doctor
```

After pulling a new Anvil release, review and apply it with:

```bash
make inspect
make upgrade DRY_RUN=1
make upgrade
```

`make upgrade` updates Anvil-owned files and preserves the installed OpenCode executable, authentication, session data, shared settings, and user-owned configuration. `make update-runtime` is the explicit command for updating OpenCode within supported 1.x releases. `make rollback` restores the latest verified lifecycle snapshot.

## Everyday commands

| Command | Purpose |
| --- | --- |
| `make inspect` | Read-only summary of installed runtime and Anvil state |
| `make doctor` | Check Anvil, OpenCode, memory, and local Databricks readiness |
| `make capabilities` | Show available Anvil and provider capabilities |
| `make stats` | Show native OpenCode usage statistics when available |
| `make databricks-setup` | Set up Anvil-owned Databricks CLI authentication and readiness |
| `make rollback` | Restore the latest verified lifecycle snapshot |
| `make test` | Run the offline test suite in temporary HOME/XDG directories |

See [capabilities](docs/capabilities.md), [lifecycle and recovery](docs/lifecycle.md), [architecture](docs/architecture.md), and [development and tests](docs/development.md).

## Safety and ownership

Anvil keeps OpenCode authentication and sessions in OpenCode's existing data paths. Lifecycle operations take verified snapshots before applying managed changes. Shared user settings and files outside Anvil's managed ownership are preserved; unsafe ownership conflicts stop the operation for review.

Databricks setup writes only Anvil-owned configuration and uses its isolated CLI installation. It does not adopt or rewrite external profiles.
