# Releasing Anvil

Anvil uses Semantic Versioning. Anvil 2.0 was the runtime/configuration migration to OpenCode 2. Starting with Anvil 2.1, Anvil product versions and OpenCode runtime majors are independent; runtime-major migration is explicit. Anvil 2.2 adds optional Databricks support through shared CLI/filesystem primitives and keeps the same runtime policy.

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
7. Run `make test`; the mandatory suite must remain offline and includes OpenCode 1/2 and Databricks fixtures plus isolated upgrade and rollback lifecycle checks.
8. If a release claim requires live OpenCode or Databricks compatibility, run and record a separate authorized smoke check; never describe fixture validation as a live service test.
9. Verify that the implementation, tests, compatibility document, changelog, version history, and capability matrix agree.

The `make test` suite includes deterministic version-documentation, harness-size/invariant, query-recipe, FinOps evidence, runtime-independence, credential-boundary, and legacy-token checks. It rejects a `VERSION` without matching changelog, version, capability, compatibility, and migration documentation. It does not resolve external runtime releases or contact a Databricks workspace.
