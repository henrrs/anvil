# Testing

`make test` requires Linux or macOS, Bash, Python 3.11+, `tar`, and internet access to the official OpenCode GitHub release API and asset (`unzip` on macOS). It resolves a stable non-prerelease, downloads one exact official release asset, verifies the published SHA-256, and records the candidate version. The candidate is not installed into the user's environment. Windows users can run under WSL.

## Candidate smoke test

OpenCode is run with a temporary `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, and empty project directory. The test invokes `debug config`, `debug skill`, and `agent list` to verify that the exact candidate accepts the generated config, selects Anvil, leaves maintenance agents intact, exposes the five skills and two commands, disables the four built-in user-facing agent IDs, applies task/skill denial, and leaves model selection unpinned.

## Local and fixture checks

The suite also checks Bash syntax, Python source parsing, required templates, the Anvil config audit, model neutrality, and a narrow secret scan. Memory fixtures cover directory creation, search-without-write, explicit JSON entry creation, frontmatter/provenance, duplicate refusal, and update behavior.

Dirty global fixtures use a HOME and XDG paths containing spaces. Backup tests check config and installer archives, manifest/checksum validation, and restored CLI settings. Repeated config application must be byte-for-byte stable. A controlled failure after replacement in `make reforge` exercises automatic rollback. Manual rollback restores the old config/installer while preserving Anvil memory. No test command receives the real OpenCode config, data, or state paths as its active destination.

## Limits

The smoke check validates config behavior against the candidate's CLI and current official schema. It does not authenticate to a provider, start a paid model request, verify every cloud/provider implementation, or exercise organization remote config in the user's account. Those data/state stores are intentionally not copied into the test HOME. Project and managed config precedence is reported separately by doctor.
