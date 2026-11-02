#!/usr/bin/env python3
"""Pure plan ordering, blockers and product/runtime version boundaries."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lifecycle_model import resolve_persisted
from lifecycle_plan import DesiredState, OperationKind, plan
from lifecycle_resolver import CurrentState


with tempfile.TemporaryDirectory() as name:
    root = Path(name)
    persisted = resolve_persisted(root / "home", root / "config", root / "data")
    life = {"lifecycle": "MIGRATION_REQUIRED", "repository": {"version": "2.17.0"},
            "configuration": {"present": True}, "memory": {"present": False},
            "backups": {"latest": str(root / "backup")}, "recovery": {"applicable": True}}
    analytics = {"schema_rollback": {"status": "READY", "policy": "NO_MIGRATION",
                                     "schema_version": 3, "target_schema_version": 3}}
    current = CurrentState(persisted, life, {}, analytics, {})
    before = copy.deepcopy(current.as_dict())
    upgrade = plan(current, DesiredState("upgrade", "2.17.0"))
    assert [item.kind for item in upgrade.operations] == [
        OperationKind.SNAPSHOT, OperationKind.REPLACE_MANAGED, OperationKind.SYNC_DEPENDENCIES,
        OperationKind.INITIALIZE_MEMORY, OperationKind.ENSURE_SERVICE,
        OperationKind.VERIFY, OperationKind.COMMIT]
    assert before == current.as_dict() and not list(root.rglob("*")), "planner mutated or discovered state"

    unsafe = CurrentState(persisted, dict(life, lifecycle="CORRUPTED",
                                               recovery={"applicable": False, "instruction": "Manual review"}), {}, analytics, {})
    blocked = plan(unsafe, DesiredState("upgrade", "2.17.0"))
    assert blocked.blockers == ("Manual review",) and not blocked.operations
    migration_analytics = {"schema_rollback": {"status": "READY", "policy": "BACKUP_RESTORE_REQUIRED",
                                                "schema_version": 2, "target_schema_version": 3}}
    migration_current = CurrentState(persisted, life, {}, migration_analytics, {})
    migration_plan = plan(migration_current, DesiredState("upgrade", "2.17.0"))
    assert [item.kind for item in migration_plan.operations][:3] == [
        OperationKind.SNAPSHOT, OperationKind.CAPTURE_ANALYTICS_STATE, OperationKind.REPLACE_MANAGED]
    unsafe_migration = CurrentState(persisted, life, {}, {"schema_rollback": {"status": "BLOCKED"}}, {})
    assert plan(unsafe_migration, DesiredState("upgrade", "2.17.0")).blockers
    rollback = plan(current, DesiredState("rollback"))
    assert [item.kind for item in rollback.operations] == [OperationKind.RESTORE, OperationKind.VERIFY]
    assert plan(CurrentState(persisted, dict(life, backups={"latest": None}), {}, analytics, {}),
                DesiredState("rollback")).blockers

    ready = CurrentState(persisted, dict(life, lifecycle="READY", memory={"present": True}), {}, analytics, {})
    installation = root / "data" / "anvil" / "installation.json"
    installation.parent.mkdir(parents=True, exist_ok=True)
    installation.write_text(json.dumps({"schema_version": 3, "anvil_version": "2.17.0"}), encoding="utf-8")
    installed_state = resolve_persisted(root / "home", root / "config", root / "data")
    ready_with_release = CurrentState(installed_state, dict(life, lifecycle="READY", memory={"present": True}), {}, analytics, {})
    runtime = plan(ready_with_release, DesiredState("update-runtime"))
    assert runtime.desired.product_version == "2.17.0", "runtime plan does not preserve the installed product release"
    assert OperationKind.REPLACE_MANAGED not in {item.kind for item in runtime.operations}
    assert OperationKind.INSTALL_RUNTIME in {item.kind for item in runtime.operations}
    assert plan(ready, DesiredState("migrate-runtime", runtime_major=7)).blockers
    assert OperationKind.REPLACE_MANAGED in {item.kind for item in
           plan(ready, DesiredState("reforge", product_version="2.17.0")).operations}

print("PASS pure lifecycle plans, operation order, rollback and runtime/product boundaries")
