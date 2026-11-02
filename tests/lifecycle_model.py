#!/usr/bin/env python3
"""Persisted lifecycle data is normalized without reading secrets or writing files."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lifecycle_model import (DocumentStatus, normalize_analytics_session,
                             normalize_databricks, normalize_installation,
                             normalize_managed_manifest, normalize_memory,
                             normalize_runtime, resolve_persisted)
from lifecycle_migrations import migrate_installation


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


with tempfile.TemporaryDirectory() as name:
    root = Path(name)
    home, config, data = root / "home", root / "config", root / "data"
    installation = data / "anvil/installation.json"
    manifest = config / "opencode/.anvil-managed.json"
    runtime = data / "anvil/runtime.json"
    analytics = home / ".anvil/analytics/runtime.json"
    databricks = config / "anvil/databricks.json"
    memory = data / "anvil/memory"

    initial = resolve_persisted(home, config, data)
    assert all(item["document"]["status"] == "NOT_PRESENT" for item in initial.as_dict().values())
    assert not root.exists() or not list(root.rglob("*")), "normalization wrote state"

    write(installation, {"schema_version": 3, "anvil_version": "2.17.0", "version": "1.19.3",
                         "runtime_major": 1, "binary": "/bin/opencode"})
    write(manifest, {"schema_version": 1, "anvil_version": "2.17.0", "files": {"AGENTS.md": "abc"}})
    write(runtime, {"schema_version": 1, "runtime": {"executable": "/bin/opencode",
                                                 "version": "1.19.3", "generation": 1, "adapter": "opencode-v1"}})
    write(analytics, {"schema_version": 1, "canonical_session_id": "session", "runtime_generation": 1})
    write(databricks, {"schema_version": 3, "selected_profile": "anvil-prod",
                       "readiness": {"overall": "READY", "provider": {"selected": "cli"}}})
    memory.mkdir(parents=True)
    current = resolve_persisted(home, config, data)
    assert current.installation.document.status == DocumentStatus.CURRENT
    assert current.managed_manifest.owned_files == 1
    assert current.runtime.generation == 1
    assert current.analytics_session.canonical_session_present
    assert current.databricks.configured and current.databricks.readiness == "READY"
    assert current.memory.document.status == DocumentStatus.CURRENT

    for path, normalizer in ((installation, normalize_installation), (manifest, normalize_managed_manifest),
                             (runtime, normalize_runtime), (analytics, normalize_analytics_session),
                             (databricks, normalize_databricks)):
        write(path, "legacy")
        assert normalizer(path).document.status == DocumentStatus.LEGACY, path
        write(path, {"schema_version": 999})
        assert normalizer(path).document.status == DocumentStatus.UNSUPPORTED, path
        path.write_text("{bad JSON", encoding="utf-8")
        assert normalizer(path).document.status == DocumentStatus.INVALID, path
    write(runtime, {"schema_version": 1, "runtime": "bad"})
    assert normalize_runtime(runtime).document.status == DocumentStatus.INVALID
    write(manifest, {"schema_version": 1, "files": "bad"})
    assert normalize_managed_manifest(manifest).document.status == DocumentStatus.INVALID
    write(databricks, {"schema_version": 3, "readiness": "bad"})
    assert normalize_databricks(databricks).document.status == DocumentStatus.INVALID
    memory.rmdir()
    memory.symlink_to(root, target_is_directory=True)
    assert normalize_memory(memory).document.status == DocumentStatus.INVALID

print("PASS lifecycle state normalization: current, absent, legacy, malformed and unsupported schemas")

legacy = {"schema_version": 1, "generation": 1, "anvil_version": "2.6.1"}
migrated = migrate_installation(legacy)
assert migrated["schema_version"] == 3 and migrated["runtime_major"] == 1
assert migrated["runtime_profile"] == "opencode-v1" and migrated["anvil_version"] == "2.6.1"
assert migrate_installation(migrated) == migrated and legacy["schema_version"] == 1
for invalid in ("legacy", {"schema_version": "3"}, {"schema_version": 999}):
    try:
        migrate_installation(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid or unsupported installation state was accepted")
print("PASS ordered installation metadata migration is idempotent and blocks unsupported schemas")

import os
import lifecycle_transaction
with tempfile.TemporaryDirectory() as name:
    previous = {key: os.environ.get(key) for key in ("HOME", "XDG_DATA_HOME")}
    try:
        os.environ["HOME"] = name
        os.environ["XDG_DATA_HOME"] = str(Path(name) / "data")
        lifecycle_transaction.begin("upgrade", str(Path(name) / "data/anvil/backups/snapshot"),
                                    "2.16.0", "2.17.0", os.getpid())
        lifecycle_transaction.phase("applying-config")
        state = lifecycle_transaction.inspect()
        assert state["operation_id"].startswith("upgrade-")
        assert [event["phase"] for event in state["events"]] == ["snapshot-verified", "applying-config"]
        try:
            lifecycle_transaction.phase("postflight-validated")
        except ValueError:
            pass
        else:
            raise AssertionError("transaction journal accepted a skipped lifecycle phase")
        assert lifecycle_transaction.inspect()["phase"] == "applying-config"
        for phase in ("config-applied", "before-installation-metadata", "postflight-validated"):
            lifecycle_transaction.phase(phase)
        lifecycle_transaction.clear()
        lifecycle_transaction.begin("rollback", str(Path(name) / "data/anvil/backups/snapshot"),
                                    "2.17.0", "2.16.0", os.getpid())
        for phase in ("restoring-snapshot", "restoring-config", "restoring-metadata",
                      "verifying-restored-state", "postflight-validated"):
            lifecycle_transaction.phase(phase)
        lifecycle_transaction.clear()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
print("PASS lifecycle journal records operation IDs and ordered phases")
