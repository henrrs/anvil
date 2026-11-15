#!/usr/bin/env python3
"""The shared executor validates the exact lifecycle plan before applying it."""

from __future__ import annotations

import copy
import json
import os
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
    base = {"repository": {"version": "2.20.1"}, "configuration": {"present": True},
            "memory": {"present": True}, "backups": {"latest": str(root / "snapshot")},
            "recovery": {"applicable": True}}
    runtime = {"runtime": {"usable": True, "generation": 1, "executable": "/fixture/opencode"}}
    ready = CurrentState(persisted, dict(base, lifecycle="READY"), runtime, {"overall": "READY"})

    for desired, executor, expected_profile, runtime_major in (
        (DesiredState("upgrade", "2.20.1"), "anvil-upgrade", "config", None),
        (DesiredState("reforge", "2.20.1"), "reforge", "config", None),
        (DesiredState("update-runtime"), "update-runtime", "runtime", 1),
        (DesiredState("rollback"), "rollback", "rollback", None),
    ):
        accepted = plan(ready, desired)
        plan_file = root / f"{executor}.json"
        persist(plan_file, accepted.as_dict())
        assert validate(plan_file, executor, runtime_major) == expected_profile

    plan_file = root / "bad.json"
    persist(plan_file, plan(ready, DesiredState("update-runtime")).as_dict())
    try:
        validate(plan_file, "anvil-upgrade")
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("executor accepted a plan for another operation")

    persist(plan_file, plan(ready, DesiredState("update-runtime")).as_dict())
    try:
        validate(plan_file, "update-runtime", 99)
    except ValueError as exc:
        assert "OpenCode 1.x" in str(exc)
    else:
        raise AssertionError("executor accepted an unsupported runtime major")

    incomplete = copy.deepcopy(plan(ready, DesiredState("update-runtime")).as_dict())
    incomplete["operations"] = [item for item in incomplete["operations"]
                                if item["kind"] != OperationKind.INSTALL_RUNTIME.value]
    persist(plan_file, incomplete)
    try:
        validate(plan_file, "update-runtime")
    except ValueError as exc:
        assert "omits required" in str(exc)
    else:
        raise AssertionError("executor accepted a plan missing runtime installation")

    blocked = copy.deepcopy(plan(ready, DesiredState("upgrade", "2.20.1")).as_dict())
    blocked["blockers"] = ["review required"]
    persist(plan_file, blocked)
    try:
        validate(plan_file, "anvil-upgrade")
    except ValueError as exc:
        assert "blocked" in str(exc)
    else:
        raise AssertionError("executor accepted a blocked plan")

    plan_file.chmod(0o644)
    try:
        validate(plan_file, "anvil-upgrade")
    except ValueError as exc:
        assert "private regular file" in str(exc)
    else:
        raise AssertionError("executor accepted a world-readable plan file")

print("PASS lifecycle executor validates the planned operation and protects private plan files")
