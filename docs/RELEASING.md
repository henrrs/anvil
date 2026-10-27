# Releasing Anvil

Anvil uses Semantic Versioning. Anvil 2.0 was the runtime/configuration migration to OpenCode 2. Starting with Anvil 2.1, Anvil product versions and OpenCode runtime majors are independent; runtime-major migration is explicit. Anvil 2.3 adds Databricks provider independence; 2.3.1 corrects runtime independence; 2.4.0 adds safe runtime quiescing and topology-aware setup; 2.5.0 moves Databricks onboarding to an Anvil-owned config and profile. Anvil 2.6.0 is a MINOR release because it formalizes readiness as a persisted, validated runtime contract and advances the provider state schema while preserving command compatibility and lazy legacy migration. Anvil 2.6.1 fixes provider fallback provisioning and persisted SDK executable reuse. Anvil 2.6.2 is a PATCH release: it hardens lifecycle reporting, offline test isolation, and SDK setup/diagnostic handling without changing the Databricks state schema or readiness contract. Anvil 2.7.0 is a MINOR release adding backward-compatible, runtime-independent evidence-backed communication and artifact capabilities without a persistent-data migration. Anvil 2.7.1 is a PATCH release restoring installed-profile compatibility during lifecycle audits. Anvil 2.8.0 is a MINOR release because it introduces a managed-config manifest and durable lifecycle recovery contract.

## Version bumps

- **PATCH** fixes a bug without an intended behavior or data-format change.
- **MINOR** adds backward-compatible behavior or capabilities.
- **MAJOR** changes a breaking product, lifecycle, or persistent-data contract.
- OpenCode runtime support additions or runtime policy changes are released according to their Anvil compatibility impact; never infer a required OpenCode major from the Anvil version.

## Release checklist

1. Update `VERSION`.
2. Add the release to `CHANGELOG.md`.
3. Add or update `docs/versions/vN.md`; a separately documented patch may use `docs/versions/vN.N.N.md`. Update the capability matrix and [runtime compatibility](runtime-compatibility.md).
4. Add migration instructions when config, runtime policy, backup, rollback, or persistent data behavior changes.
5. Update relevant ADRs when runtime adapters, capabilities, or lifecycle semantics change.
6. Recheck current official OpenCode 1 and 2 compatibility and update `docs/opencode-compatibility.md`.
7. Run `make test`; the mandatory suite must remain offline and includes OpenCode 1/2 and Databricks fixtures plus isolated upgrade and rollback lifecycle checks.
8. If a release claim requires live OpenCode or Databricks compatibility, run and record a separate authorized smoke check; never describe fixture validation as a live service test.
9. Verify that the implementation, tests, compatibility document, changelog, version history, and capability matrix agree.
10. Verify that public command text and JSON output remain separate, setup authentication choices are topology-aware, and `make upgrade DRY_RUN=1` does not signal or write live state.

The `make test` suite includes deterministic provider, install-double, PATH, SDK fallback, VS Code discovery, state-security, dry-run, version-documentation, harness, query-recipe, FinOps, runtime-independence, credential-boundary, and repository-hygiene checks. It denies external socket connections during local lifecycle tests while allowing loopback for isolated runtime fixtures. It rejects a `VERSION` without matching changelog, version, capability, compatibility, and migration documentation. It does not resolve external runtime releases or contact a Databricks workspace.

## Anvil 2.9 engineering gate

This MINOR release adds optional task state and progressive skills without runtime or memory migration. Run engineering unit/fault/concurrency/compaction tests and ingestion plus unrelated scheduler replays through `make test`. Keep model/semantic results explicitly unmeasured unless the optional live harness and rubric adjudication actually ran. Preserve the short-task state bypass and 4,200-byte permanent-kernel budget. Verify older source profiles, separate XDG task-store preservation, new manifest ownership and the three-prior-minor migration window.
