# Releasing Anvil

Anvil uses Semantic Versioning. Anvil 2.0 was the runtime/configuration migration to OpenCode 2. Starting with Anvil 2.1, Anvil product versions and OpenCode runtime majors are independent; runtime-major migration is explicit.

## Version bumps

- **PATCH** fixes a bug without an intended behavior or data-format change.
- **MINOR** adds backward-compatible behavior or capabilities.
- **MAJOR** changes a breaking product, lifecycle, or persistent-data contract.
- OpenCode runtime support additions or runtime policy changes are released according to their Anvil compatibility impact; never infer a required OpenCode major from the Anvil version.

## Release checklist

1. Update `VERSION`.
2. Add the release to `CHANGELOG.md`.
3. Add or update `docs/versions/vN.md`, the capability matrix, and [runtime compatibility](runtime-compatibility.md).
4. Add migration instructions when config, runtime policy, backup, rollback, or persistent data behavior changes.
5. Update relevant ADRs when runtime adapters, capabilities, or lifecycle semantics change.
6. Recheck current official OpenCode 1 and 2 compatibility and update `docs/opencode-compatibility.md`.
7. Run `make test`, including the isolated upgrade and rollback lifecycle checks.
8. Verify that the implementation, tests, compatibility document, changelog, version history, and capability matrix agree.

The `make test` suite includes a deterministic version-documentation check. It rejects a `VERSION` without a matching changelog entry, version document, capability matrix, and release/migration documentation.
