"""Validate the immutable ChangePlan handed to the shared shell executor."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from lifecycle_plan import ChangePlan, OperationKind
from public_errors import run_public


PLAN_OPERATIONS = {
    "anvil-upgrade": "upgrade",
    "reforge": "reforge",
    "update-runtime": "update-runtime",
    "migrate-runtime": "migrate-runtime",
    "rollback": "rollback",
}

REQUIRED = {
    "upgrade": {OperationKind.SNAPSHOT, OperationKind.REPLACE_MANAGED,
                OperationKind.VERIFY, OperationKind.COMMIT},
    "reforge": {OperationKind.SNAPSHOT, OperationKind.REPLACE_MANAGED,
                OperationKind.VERIFY, OperationKind.COMMIT},
    "update-runtime": {OperationKind.SNAPSHOT, OperationKind.INSTALL_RUNTIME,
                       OperationKind.VERIFY, OperationKind.COMMIT},
    "migrate-runtime": {OperationKind.SNAPSHOT, OperationKind.INSTALL_RUNTIME,
                         OperationKind.MIGRATE_ADAPTER, OperationKind.VERIFY,
                         OperationKind.COMMIT},
    "rollback": {OperationKind.RESTORE, OperationKind.VERIFY},
}

ALLOWED = {
    "upgrade": REQUIRED["upgrade"] | {OperationKind.SYNC_DEPENDENCIES,
                                      OperationKind.INITIALIZE_MEMORY},
    "reforge": REQUIRED["reforge"] | {OperationKind.INSTALL_RUNTIME,
                                      OperationKind.SYNC_DEPENDENCIES,
                                      OperationKind.INITIALIZE_MEMORY},
    "update-runtime": REQUIRED["update-runtime"] | {OperationKind.MIGRATE_ADAPTER,
                                                    OperationKind.SYNC_DEPENDENCIES},
    "migrate-runtime": REQUIRED["migrate-runtime"] | {OperationKind.SYNC_DEPENDENCIES,
                                                      OperationKind.INITIALIZE_MEMORY},
    "rollback": REQUIRED["rollback"],
}


def validate(plan_path: Path, execution_operation: str, runtime_major: int | None = None) -> str:
    expected_desired = PLAN_OPERATIONS.get(execution_operation)
    if expected_desired is None:
        raise ValueError(f"unsupported lifecycle executor operation: {execution_operation}")
    try:
        info = plan_path.lstat()
    except OSError as exc:
        raise ValueError(f"change plan is unavailable: {exc.strerror or type(exc).__name__}") from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("change plan must be a private regular file owned by the current user")
    try:
        raw = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"change plan cannot be read: {type(exc).__name__}") from None
    change_plan = ChangePlan.from_dict(raw)
    if change_plan.desired.operation != expected_desired:
        raise ValueError("change plan does not match the lifecycle operation being executed")
    if runtime_major is not None and change_plan.desired.runtime_major != runtime_major:
        raise ValueError("change plan runtime major does not match the validated runtime candidate")
    if change_plan.blockers:
        raise ValueError("a blocked lifecycle plan cannot be executed")
    kinds = {item.kind for item in change_plan.operations}
    missing = REQUIRED[expected_desired] - kinds
    unexpected = kinds - ALLOWED[expected_desired]
    if missing:
        raise ValueError("change plan omits required operation(s): " + ", ".join(sorted(item.value for item in missing)))
    if unexpected:
        raise ValueError("change plan contains operation(s) this executor cannot apply: "
                         + ", ".join(sorted(item.value for item in unexpected)))
    # The transaction runner uses this profile to record config phases only
    # when the serialized plan actually includes a configuration mutation.
    if expected_desired == "rollback":
        return "rollback"
    return "config" if kinds & {OperationKind.REPLACE_MANAGED, OperationKind.MIGRATE_ADAPTER} else "runtime"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--plan-file", required=True, type=Path)
    parser.add_argument("--runtime-major", type=int)
    args = parser.parse_args()
    print(validate(args.plan_file, args.operation, args.runtime_major))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_public(main, command="Anvil lifecycle executor"))
