# Releasing Anvil

Anvil uses Semantic Versioning. The runtime/configuration migration to OpenCode 2 makes V2 a major release.

## Version bumps

- **PATCH** fixes a bug without an intended behavior or data-format change.
- **MINOR** adds backward-compatible behavior or capabilities.
- **MAJOR** changes a breaking product, lifecycle, runtime-generation, or persistent-data contract.

## Release checklist

1. Update `VERSION`.
2. Add the release to `CHANGELOG.md`.
3. Add or update `docs/versions/vN.md` and the capability matrix in `docs/versions/README.md`.
4. Add migration instructions when config, runtime, backup, rollback, or persistent data behavior changes.
5. Update relevant ADRs when an architecture decision changes.
6. Recheck current official OpenCode compatibility and update `docs/opencode-compatibility.md`.
7. Run `make test`, including the isolated upgrade and rollback lifecycle checks.
8. Verify that the implementation, tests, compatibility document, changelog, version history, and capability matrix agree.

The `make test` suite includes a deterministic version-documentation check. It rejects a `VERSION` without a matching changelog entry, version document, capability matrix, and release/migration documentation.
