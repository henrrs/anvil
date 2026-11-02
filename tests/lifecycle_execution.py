#!/usr/bin/env python3
"""The shared executor consumes, validates and gates on the planned ChangePlan."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lifecycle_executor import validate
from lifecycle_model import resolve_persisted
from lifecycle_plan import DesiredState, OperationKind, plan
from lifecycle_resolver import CurrentState


def persist(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


with tempfile.TemporaryDirectory() as name:
    root = Path(name)
    persisted = resolve_persisted(root / "home", root / "config", root / "data")
    base = {"repository": {"version": "2.17.0"}, "configuration": {"present": True},
            "memory": {"present": True}, "backups": {"latest": str(root / "snapshot")},
            "recovery": {"applicable": True}}
    runtime = {"runtime": {"usable": True, "generation": 1, "executable": "/fixture/opencode"}}
    ready = CurrentState(persisted, dict(base, lifecycle="READY"), runtime, {}, {})

    for desired, executor_name, expected_profile, runtime_major in (
        (DesiredState("upgrade", "2.17.0"), "anvil-upgrade", "config", None),
        (DesiredState("reforge", "2.17.0", 1), "reforge", "config", 1),
        (DesiredState("update-runtime"), "update-runtime", "runtime", 1),
        (DesiredState("migrate-runtime", runtime_major=2), "migrate-runtime", "config", 2),
        (DesiredState("rollback"), "rollback", "rollback", None),
    ):
        accepted = plan(ready, desired)
        plan_file = root / f"{executor_name}.json"
        persist(plan_file, accepted.as_dict())
        assert validate(plan_file, executor_name, runtime_major) == expected_profile

    plan_file = root / "bad.json"
    wrong_operation = plan(ready, DesiredState("update-runtime")).as_dict()
    persist(plan_file, wrong_operation)
    try:
        validate(plan_file, "anvil-upgrade")
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("executor accepted a ChangePlan for a different operation")

    update_plan = plan(ready, DesiredState("update-runtime")).as_dict()
    persist(plan_file, update_plan)
    try:
        validate(plan_file, "update-runtime", 2)
    except ValueError as exc:
        assert "runtime major" in str(exc)
    else:
        raise AssertionError("executor accepted a plan for a different runtime major")

    incomplete = copy.deepcopy(plan(ready, DesiredState("update-runtime")).as_dict())
    incomplete["operations"] = [item for item in incomplete["operations"]
                                if item["kind"] != OperationKind.INSTALL_RUNTIME.value]
    persist(plan_file, incomplete)
    try:
        validate(plan_file, "update-runtime")
    except ValueError as exc:
        assert "omits required" in str(exc)
    else:
        raise AssertionError("executor accepted a plan with a missing runtime operation")

    blocked = copy.deepcopy(plan(ready, DesiredState("upgrade", "2.17.0")).as_dict())
    blocked["blockers"] = ["review required"]
    persist(plan_file, blocked)
    try:
        validate(plan_file, "anvil-upgrade")
    except ValueError as exc:
        assert "blocked" in str(exc)
    else:
        raise AssertionError("executor accepted a blocked ChangePlan")

    plan_file.chmod(0o644)
    try:
        validate(plan_file, "anvil-upgrade")
    except ValueError as exc:
        assert "private regular file" in str(exc)
    else:
        raise AssertionError("executor accepted a world-readable plan file")

print("PASS shared lifecycle executor validates the exact serialized plan before applying adapters")
