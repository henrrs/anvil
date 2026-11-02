"""Lifecycle facts and semantic contributions from real module boundaries.

Contributors never own a transaction. The planner orders their proposed
operations, and the command adapter owns snapshot/apply/verify/rollback.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import runtime_state
from analytics.diagnostics import collect as collect_analytics


class OpenCodeContributor:
    def inspect(self) -> dict[str, Any]:
        return runtime_state.discover()

    def plan_runtime(self, operation: str, *, analytics_installed: bool = False) -> tuple[Any, ...]:
        from lifecycle_plan import OperationKind, _op
        proposed = [_op(OperationKind.INSTALL_RUNTIME, "opencode",
                        "Update the runtime without changing product release", idempotent=False)]
        if operation == "migrate-runtime":
            proposed.append(_op(OperationKind.MIGRATE_ADAPTER, "managed-config", "Change runtime adapter major"))
        if analytics_installed:
            proposed.append(_op(OperationKind.SYNC_DEPENDENCIES, "analytics",
                                "Revalidate release-pinned local dependencies"))
        return tuple(proposed)

    def verify(self, binary: Path, version: str, major: int) -> None:
        candidate = runtime_state.discover(str(binary)).get("runtime") or {}
        if (not candidate.get("supported") or candidate.get("version") != version
                or candidate.get("generation") != major):
            raise ValueError("runtime does not match the planned supported candidate")


class AnalyticsContributor:
    def inspect(self, config: Path, home: Path) -> dict[str, Any]:
        try:
            port = int(os.environ.get("ANVIL_ANALYTICS_PORT", "8765"))
            if not 1 <= port <= 65535:
                port = 8765
        except ValueError:
            port = 8765
        result = collect_analytics(config, home, port)
        try:
            import analytics_schema
            from analytics.store import SCHEMA_VERSION, migration_rollback_policy
            state_root = Path(os.environ.get("ANVIL_HOME", str(home / ".anvil"))).expanduser().absolute()
            database = state_root / "analytics" / "context.db"
            observed = analytics_schema.inspect_database(database)
            policy = migration_rollback_policy(observed["schema_version"])
            result["schema_rollback"] = {**observed, **policy,
                                          "target_schema_version": SCHEMA_VERSION}
        except (OSError, ValueError, RuntimeError) as exc:
            result["schema_rollback"] = {"status": "BLOCKED", "reason": type(exc).__name__}
        return result

    def plan_rollback_state(self, schema_plan: dict[str, Any]) -> tuple[Any, ...]:
        from lifecycle_plan import OperationKind, _op
        if schema_plan.get("policy") == "BACKUP_RESTORE_REQUIRED":
            return (_op(OperationKind.CAPTURE_ANALYTICS_STATE, "analytics-control-store",
                        "Capture a verified SQLite rollback snapshot before an incompatible schema migration"),)
        return ()

    def plan_product(self, installed: bool) -> tuple[Any, ...]:
        from lifecycle_plan import OperationKind, _op
        lock = Path(__file__).resolve().parents[1] / "config" / "analytics-requirements.lock"
        package_summary = "release-pinned Analytics dependencies"
        try:
            import analytics_dependencies
            _, packages = analytics_dependencies.parse_lock(lock)
            policy = analytics_dependencies.package_resolution_policy()
            package_summary = (", ".join(f"{name}=={version}" for name, version in packages)
                               + f"; source policy {policy.policy}; public fallback "
                               + ("enabled" if policy.public_fallback else "disabled"))
        except (OSError, ValueError, RuntimeError):
            package_summary += "; corporate-first source policy with policy-controlled public fallback"
        return ((_op(OperationKind.SYNC_DEPENDENCIES, "analytics",
                     "Stage and verify " + package_summary),) if installed else ())

    def plan_service(self, readiness: dict[str, Any]) -> tuple[Any, ...]:
        from lifecycle_plan import OperationKind, _op
        service = readiness.get("service") if isinstance(readiness.get("service"), dict) else {}
        return ((_op(OperationKind.ENSURE_SERVICE, "analytics",
                     "Ensure installed Analytics service is available"),)
                if service.get("status") != "READY" else ())

    def verify(self, config: Path, memory: Path) -> None:
        lock = config / "runtime" / "analytics-requirements.lock"
        if not lock.is_file() or os.environ.get("ANVIL_TEST_MODE") == "1":
            return
        import analytics_dependencies
        data_home = memory.parent.parent
        operation_id = os.environ.get("ANVIL_LIFECYCLE_OPERATION_ID")
        marker = (analytics_dependencies._operation_marker(data_home, operation_id)
                  if operation_id else None)
        interpreter = (analytics_dependencies.staged_interpreter(lock, data_home, operation_id)
                       if marker is not None and marker.is_file()
                       else analytics_dependencies.runtime_path(lock, data_home) / "bin" / "python")
        _, packages = analytics_dependencies.parse_lock(lock)
        if not analytics_dependencies._validate(interpreter, packages):
            raise ValueError("pinned Analytics dependencies are unavailable")

    def verify_service(self, config: Path, home: Path) -> None:
        import analytics_service
        systemd = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "systemd" / "user"
        try:
            port = int(os.environ.get("ANVIL_ANALYTICS_PORT", "8765"))
        except ValueError:
            port = 8765
        if analytics_service.service_state(config, home, systemd, port)["status"] != "READY":
            raise ValueError("Analytics service is not ready")

    def verify_service_candidate(self, config: Path, home: Path) -> None:
        import analytics_service
        systemd = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "systemd" / "user"
        try:
            port = int(os.environ.get("ANVIL_ANALYTICS_PORT", "8765"))
        except ValueError:
            port = 8765
        if not 1 <= port <= 65535:
            raise ValueError("Analytics service port is invalid")
        lock = config / "runtime" / "analytics-requirements.lock"
        interpreter = None
        operation_id = os.environ.get("ANVIL_LIFECYCLE_OPERATION_ID")
        if lock.is_file() and operation_id:
            import analytics_dependencies
            data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share"))).expanduser()
            marker = analytics_dependencies._operation_marker(data_home, operation_id)
            if marker.is_file():
                interpreter = analytics_dependencies.staged_interpreter(lock, data_home, operation_id)
        analytics_service.validate_candidate(config, home, systemd, port, interpreter)


class DatabricksContributor:
    def inspect(self) -> dict[str, Any]:
        import databricks
        return databricks.local_status()

    def plan_setup(self, readiness: dict[str, Any]) -> tuple[Any, ...]:
        from lifecycle_plan import OperationKind, _op
        return ((_op(OperationKind.DATABRICKS_SETUP, "databricks", "Converge provider configuration"),)
                if readiness.get("overall") != "READY" else ())


class MemoryContributor:
    def plan_initialize(self, present: bool) -> tuple[Any, ...]:
        from lifecycle_plan import OperationKind, _op
        return () if present else (_op(OperationKind.INITIALIZE_MEMORY, "memory", "Memory directory is absent"),)

    def verify(self, memory: Path) -> None:
        if memory.is_symlink() or not memory.is_dir():
            raise ValueError("memory root is unavailable")
