# SE-05 — Local dependency installation with recoverable milestones

Implement the local package installation slice described below. This is an offline
engineering task; package metadata is supplied by `catalog.py`, and no package download,
network access, subprocess package manager, or system mutation is allowed.

## Milestones

1. **Manifest and constraints:** validate names, duplicate entries and version constraints.
   Supported constraints are comma-separated `==`, `>=`, `>`, `<=`, and `<` comparisons
   against three-part numeric versions.
2. **Dependency resolution:** include transitive dependencies, select the highest
   catalog version satisfying all discovered constraints, reject unknown packages,
   unsatisfied constraints and dependency cycles, and return a deterministic
   dependencies-first plan.
3. **Safe installation:** stage package metadata below the requested local root, make
   installation idempotent, and publish installed state only after the package set is
   ready. If an injected failure occurs during activation, restore the previous package
   directories and state without deleting unrelated files.
4. **CLI integration:** support `python3 cli.py plan --manifest FILE` and
   `python3 cli.py install --manifest FILE --root DIRECTORY`; emit stable JSON and return
   a non-zero status for invalid input or failed installation.

Keep ownership clear: `manifest.py` validates user intent, `resolver.py` owns dependency
policy, `installer.py` owns filesystem effects and rollback, `store.py` owns installed
state, and `cli.py` translates command-line requests. Preserve those module boundaries.
Use only the standard library. Add focused public tests, then run them and describe the
remaining limitations. A task plan alone is not completion; finish all milestones.
