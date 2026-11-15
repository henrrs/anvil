#!/usr/bin/env python3
"""Pure lifecycle plan ordering, safety blockers and runtime boundaries."""

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
    life = {"lifecycle": "READY", "repository": {"version": "2.20.1"},
            "configuration": {"present": True}, "memory": {"present": False},
            "backups": {"latest": str(root / "backup")}, "recovery": {"applicable": True}}
    runtime = {"runtime": {"usable": True, "generation": 1, "executable": "/fixture/opencode"}}
    databricks = {"overall": "NOT_CONFIGURED"}
    current = CurrentState(persisted, life, runtime, databricks)
    before = copy.deepcopy(current.as_dict())
    upgrade = plan(current, DesiredState("upgrade", "2.20.1"))
    assert [item.kind for item in upgrade.operations] == [
        OperationKind.SNAPSHOT, OperationKind.REPLACE_MANAGED, OperationKind.INITIALIZE_MEMORY,
        OperationKind.VERIFY, OperationKind.COMMIT]
    assert before == current.as_dict() and not list(root.rglob("*")), "planner mutated or discovered state"

    unsafe = CurrentState(persisted, dict(life, lifecycle="CORRUPTED",
                                          recovery={"applicable": False, "instruction": "Manual review"}),
                          runtime, databricks)
    blocked = plan(unsafe, DesiredState("upgrade", "2.20.1"))
    assert blocked.blockers == ("Manual review",) and not blocked.operations

    rollback = plan(current, DesiredState("rollback"))
    assert [item.kind for item in rollback.operations] == [OperationKind.RESTORE, OperationKind.VERIFY]
    no_snapshot = CurrentState(persisted, dict(life, backups={"latest": None}), runtime, databricks)
    assert plan(no_snapshot, DesiredState("rollback")).blockers

    absent_runtime = CurrentState(persisted, dict(life, lifecycle="PARTIALLY_INSTALLED"),
                                  {"runtime": {"usable": False}}, databricks)
    first_install = plan(absent_runtime, DesiredState("reforge", "2.20.1"))
    assert OperationKind.INSTALL_RUNTIME in {item.kind for item in first_install.operations}
    refroged_v1 = plan(absent_runtime, DesiredState("reforge", "2.20.1", runtime_major=1))
    assert refroged_v1.desired.runtime_major == 1
    unsupported_reforge = plan(absent_runtime, DesiredState("reforge", "2.20.1", runtime_major=99))
    assert unsupported_reforge.blockers and not unsupported_reforge.operations
    unsupported_runtime = plan(current, DesiredState("update-runtime", runtime_major=99))
    assert unsupported_runtime.blockers and not unsupported_runtime.operations

    ready_release_path = root / "data" / "anvil" / "installation.json"
    ready_release_path.parent.mkdir(parents=True)
    ready_release_path.write_text(json.dumps({"schema_version": 3, "anvil_version": "2.20.1"}))
    persisted_with_release = resolve_persisted(root / "home", root / "config", root / "data")
    ready = CurrentState(persisted_with_release, dict(life, memory={"present": True}), runtime, databricks)
    runtime_plan = plan(ready, DesiredState("update-runtime"))
    assert runtime_plan.source_product_version == "2.20.1"
    assert runtime_plan.desired.runtime_major == 1
    assert OperationKind.REPLACE_MANAGED not in {item.kind for item in runtime_plan.operations}
    assert OperationKind.INSTALL_RUNTIME in {item.kind for item in runtime_plan.operations}

    databricks_plan = plan(current, DesiredState("databricks-setup"))
    assert [item.kind for item in databricks_plan.operations] == [
        OperationKind.SNAPSHOT, OperationKind.DATABRICKS_SETUP, OperationKind.VERIFY]

print("PASS lifecycle plans preserve ordering, rollback and OpenCode 1 boundaries")
