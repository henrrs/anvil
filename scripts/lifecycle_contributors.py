"""Lifecycle facts and semantic contributions from real module boundaries.

Contributors never own a transaction. The planner orders their proposed
operations, and the command adapter owns snapshot/apply/verify/rollback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import runtime_state


class OpenCodeContributor:
    def inspect(self) -> dict[str, Any]:
        return runtime_state.discover()

    def plan_runtime(self) -> tuple[Any, ...]:
        from lifecycle_plan import OperationKind, _op
        return (_op(OperationKind.INSTALL_RUNTIME, "opencode",
                    "Update OpenCode 1 without changing the Anvil release", idempotent=False),)

    def verify(self, binary: Path, version: str, major: int) -> None:
        candidate = runtime_state.discover(str(binary)).get("runtime") or {}
        if (not candidate.get("supported") or candidate.get("version") != version
                or candidate.get("generation") != major):
            raise ValueError("runtime does not match the planned supported candidate")


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
