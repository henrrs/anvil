"""Pure lifecycle planning from a normalized local observation.

The plan is a decision record. The existing command adapters still implement
the physical operations while they are migrated to the shared executor.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from lifecycle_contributors import DatabricksContributor, MemoryContributor, OpenCodeContributor
from lifecycle_resolver import CurrentState, resolve
from public_errors import run_public


class OperationKind(str, Enum):
    SNAPSHOT = "CreateSnapshot"
    REPLACE_MANAGED = "ReplaceManagedArtifacts"
    INSTALL_RUNTIME = "InstallRuntimeArtifact"
    INITIALIZE_MEMORY = "InitializeMemory"
    VERIFY = "VerifyInstallation"
    COMMIT = "CommitInstallationRecord"
    RESTORE = "RestoreSnapshot"
    DATABRICKS_SETUP = "ConvergeDatabricksConfiguration"


ORDER = {OperationKind.SNAPSHOT: 0, OperationKind.REPLACE_MANAGED: 1,
         OperationKind.INSTALL_RUNTIME: 1, OperationKind.INITIALIZE_MEMORY: 2,
         OperationKind.VERIFY: 3, OperationKind.COMMIT: 4, OperationKind.RESTORE: 1,
         OperationKind.DATABRICKS_SETUP: 1}


@dataclass(frozen=True)
class DesiredState:
    operation: str
    product_version: str | None = None
    runtime_major: int | None = None


@dataclass(frozen=True)
class Operation:
    kind: OperationKind
    scope: str
    description: str
    reason: str
    rollback: bool
    idempotent: bool


@dataclass(frozen=True)
class ChangePlan:
    desired: DesiredState
    source_product_version: str | None
    operations: tuple[Operation, ...]
    blockers: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.blockers and self.operations:
            raise ValueError("blocked plans cannot carry mutations")
        kinds = [item.kind for item in self.operations]
        if len(kinds) != len(set(kinds)):
            raise ValueError("plan contains duplicate semantic operations")
        if kinds != sorted(kinds, key=lambda kind: ORDER[kind]):
            raise ValueError("plan operations are not in lifecycle order")
        if any(not item.rollback for item in self.operations if item.kind not in {OperationKind.VERIFY, OperationKind.COMMIT}):
            raise ValueError("mutating operation lacks snapshot rollback support")
        if self.desired.operation == "rollback":
            if kinds and kinds[0] != OperationKind.RESTORE:
                raise ValueError("rollback plan must begin by restoring its verified snapshot")
            if kinds and kinds != [OperationKind.RESTORE, OperationKind.VERIFY]:
                raise ValueError("rollback plan must restore and then verify the selected snapshot")
        elif kinds and kinds[0] != OperationKind.SNAPSHOT:
            raise ValueError("mutating plan must begin with a snapshot")
        if OperationKind.COMMIT in kinds and (not kinds or kinds[-1] != OperationKind.COMMIT):
            raise ValueError("installation record must be committed last")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"schema_version": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, value: Any) -> "ChangePlan":
        """Parse an untrusted serialized plan back into its typed contract."""
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("change plan has an unsupported schema")
        desired = value.get("desired")
        operations = value.get("operations")
        blockers = value.get("blockers", [])
        source = value.get("source_product_version")
        if (not isinstance(desired, dict) or not isinstance(desired.get("operation"), str)
                or (desired.get("product_version") is not None and not isinstance(desired.get("product_version"), str))
                or (desired.get("runtime_major") is not None and type(desired.get("runtime_major")) is not int)
                or not isinstance(operations, list) or not isinstance(blockers, list)
                or not all(isinstance(item, str) for item in blockers)
                or (source is not None and not isinstance(source, str))):
            raise ValueError("change plan has an invalid shape")
        parsed_operations: list[Operation] = []
        for item in operations:
            if not isinstance(item, dict):
                raise ValueError("change plan operation has an invalid shape")
            try:
                kind = OperationKind(item.get("kind"))
            except (ValueError, TypeError):
                raise ValueError("change plan contains an unknown operation") from None
            if (not isinstance(item.get("scope"), str) or not isinstance(item.get("description"), str)
                    or not isinstance(item.get("reason"), str)
                    or type(item.get("rollback")) is not bool or type(item.get("idempotent")) is not bool):
                raise ValueError("change plan operation has an invalid field")
            parsed_operations.append(Operation(kind, item["scope"], item["description"], item["reason"],
                                               item["rollback"], item["idempotent"]))
        parsed = cls(DesiredState(desired["operation"], desired.get("product_version"), desired.get("runtime_major")),
                     source, tuple(parsed_operations), tuple(blockers))
        parsed.validate()
        return parsed


def _op(kind: OperationKind, scope: str, reason: str, *, idempotent: bool = True) -> Operation:
    return Operation(kind, scope, kind.value, reason, kind not in {OperationKind.VERIFY, OperationKind.COMMIT}, idempotent)


def plan(current: CurrentState, desired: DesiredState) -> ChangePlan:
    """Plan Anvil lifecycle actions for the OpenCode 1 profile."""
    state = current.lifecycle
    lifecycle = state["lifecycle"]
    source = current.persisted.installation.product_version
    runtime_operation = desired.operation == "update-runtime"
    target = desired.product_version or (source if runtime_operation else state["repository"]["version"])
    blockers: list[str] = []
    operations: list[Operation] = []

    if desired.operation == "upgrade":
        if lifecycle in {"CORRUPTED", "UNSUPPORTED", "RECOVERY_REQUIRED", "TRANSITION_IN_PROGRESS"}:
            blockers.append(state.get("recovery", {}).get("instruction") or "The installation needs review before upgrade.")
        elif lifecycle in {"REPOSITORY_ONLY", "PARTIALLY_INSTALLED"}:
            blockers.append("Run make reforge to complete first installation before upgrading.")
        elif lifecycle in {"READY", "INSTALLED", "DEGRADED", "STALE", "RECOVERABLE"}:
            operations.extend((_op(OperationKind.SNAPSHOT, "anvil", "Preserve exact pre-upgrade state"),
                               _op(OperationKind.REPLACE_MANAGED, "managed-config", "Converge target release artifacts"),
                               *MemoryContributor().plan_initialize(state["memory"]["present"]),
                               _op(OperationKind.VERIFY, "installation", "Verify target before metadata commit"),
                               _op(OperationKind.COMMIT, "installation", "Mark target release installed")))
    elif desired.operation == "reforge":
        if desired.runtime_major not in {None, 1}:
            blockers.append("Anvil supports only OpenCode 1.x.")
        elif source and source != target:
            blockers.append("Reforge rebuilds the installed release; run make upgrade for a release change.")
        elif lifecycle in {"UNSUPPORTED", "RECOVERY_REQUIRED", "TRANSITION_IN_PROGRESS"}:
            blockers.append("Resolve the lifecycle blocker before reforge.")
        elif lifecycle == "CORRUPTED" and not state.get("recovery", {}).get("applicable"):
            blockers.append("Unsafe managed state requires manual review before reforge.")
        else:
            runtime = current.active_runtime.get("runtime") if isinstance(current.active_runtime, dict) else {}
            runtime = runtime if isinstance(runtime, dict) else {}
            operations.extend((_op(OperationKind.SNAPSHOT, "anvil", "Preserve pre-reforge state"),
                               _op(OperationKind.REPLACE_MANAGED, "managed-config", "Rebuild managed artifacts")))
            if not runtime.get("usable"):
                operations.append(_op(OperationKind.INSTALL_RUNTIME, "opencode",
                                      "Provision OpenCode 1 on first installation", idempotent=False))
            operations.extend((*MemoryContributor().plan_initialize(state["memory"]["present"]),
                               _op(OperationKind.VERIFY, "installation", "Verify rebuilt artifacts"),
                               _op(OperationKind.COMMIT, "installation", "Record rebuilt installation")))
    elif desired.operation == "update-runtime":
        allowed = {"READY", "INSTALLED", "DEGRADED", "STALE", "RECOVERABLE"}
        if lifecycle not in allowed:
            blockers.append("A current supported Anvil installation is required for runtime updates.")
        elif desired.runtime_major not in {None, 1}:
            blockers.append("Anvil supports only OpenCode 1.x.")
        else:
            operations.extend((_op(OperationKind.SNAPSHOT, "runtime", "Preserve complete pre-runtime state"),
                               *OpenCodeContributor().plan_runtime(),
                               _op(OperationKind.VERIFY, "runtime", "Verify OpenCode 1 compatibility"),
                               _op(OperationKind.COMMIT, "installation", "Record runtime provenance")))
    elif desired.operation == "rollback":
        if not state["backups"]["latest"]:
            blockers.append("No verified rollback snapshot is available.")
        else:
            operations.extend((_op(OperationKind.RESTORE, "snapshot", "Restore exact recorded pre-operation snapshot"),
                               _op(OperationKind.VERIFY, "installation", "Verify restored state")))
    elif desired.operation == "databricks-setup":
        contribution = DatabricksContributor().plan_setup(current.databricks)
        if contribution:
            operations.extend((_op(OperationKind.SNAPSHOT, "databricks", "Preserve Anvil-owned provider state"),
                               *contribution,
                               _op(OperationKind.VERIFY, "databricks", "Verify local provider state")))
    else:
        raise ValueError(f"unknown lifecycle operation: {desired.operation}")

    selected_runtime_major = 1 if runtime_operation or (
        desired.operation == "reforge" and desired.runtime_major is not None) else None
    plan_desired = DesiredState(desired.operation, desired.product_version, selected_runtime_major)
    result = ChangePlan(plan_desired, source, tuple(operations), tuple(blockers))
    result.validate()
    return result

def render_text(result: ChangePlan) -> str:
    """Render a previously accepted plan without resolving or replanning state."""
    desired = result.desired
    target = desired.product_version
    if target is None and desired.operation == "update-runtime":
        target = result.source_product_version
    lines = [f"Anvil {desired.operation} plan",
             f"  installed release  {result.source_product_version or 'not recorded'}",
             f"  target release     {target or 'checkout release'}"]
    if desired.runtime_major is not None:
        lines.append(f"  target runtime     OpenCode {desired.runtime_major}")
    for blocker in result.blockers:
        lines.append(f"  BLOCKED            {blocker}")
    for index, item in enumerate(result.operations, 1):
        lines.append(f"  {index}. {item.kind.value} [{item.scope}]")
        lines.append(f"     {item.reason}")
    if not result.operations and not result.blockers:
        lines.append("  No changes required")
    lines.append("  No changes applied")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", nargs="?", choices=("upgrade", "reforge", "update-runtime",
                                                          "rollback", "databricks-setup"))
    parser.add_argument("--target-version")
    parser.add_argument("--runtime-major", type=int)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--json-output", help="Write this exact plan to a private file while rendering the selected format.")
    parser.add_argument("--render-file", help="Render an already-generated plan without discovering or replanning state.")
    args = parser.parse_args()
    if args.render_file:
        if args.operation or args.target_version or args.runtime_major or args.json_output:
            parser.error("--render-file cannot be combined with planning or output-file arguments")
        try:
            result = ChangePlan.from_dict(json.loads(Path(args.render_file).read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            print(f"ERROR LIFECYCLE_PLAN: cannot render accepted plan: {exc}", file=__import__("sys").stderr)
            return 2
    else:
        if not args.operation:
            parser.error("operation is required unless --render-file is used")
        desired = DesiredState(args.operation, args.target_version, args.runtime_major)
        result = plan(resolve(), desired)
    if args.json_output:
        destination = Path(args.json_output)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(destination, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result.as_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(destination, 0o600)
    if args.format == "json":
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print(render_text(result))
    return 1 if result.blockers else 0


if __name__ == "__main__":
    raise SystemExit(run_public(main, command="Anvil lifecycle plan"))
