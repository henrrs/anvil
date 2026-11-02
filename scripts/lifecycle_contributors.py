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
        return collect_analytics(config, home, port)

    def plan_product(self, installed: bool) -> tuple[Any, ...]:
        from lifecycle_plan import OperationKind, _op
        return ((_op(OperationKind.SYNC_DEPENDENCIES, "analytics",
                     "Converge release-pinned local dependencies"),) if installed else ())

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
        target = analytics_dependencies.runtime_path(lock, data_home)
        _, packages = analytics_dependencies.parse_lock(lock)
        if not analytics_dependencies._validate(target / "bin" / "python", packages):
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
