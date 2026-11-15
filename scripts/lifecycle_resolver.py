"""Resolve local lifecycle facts and optional Databricks inventory."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import lifecycle_state
from lifecycle_contributors import DatabricksContributor, OpenCodeContributor
from lifecycle_model import PersistedState, resolve_persisted


@dataclass(frozen=True)
class CurrentState:
    """Read-only lifecycle snapshot used by projections and plans."""

    persisted: PersistedState
    lifecycle: dict[str, Any]
    active_runtime: dict[str, Any]
    databricks: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve(*, include_databricks: bool = True) -> CurrentState:
    paths = lifecycle_state.paths()
    persisted = resolve_persisted(paths["home"], paths["config"].parent, paths["data"].parent)
    active = OpenCodeContributor().inspect()
    lifecycle = lifecycle_state.evaluate(active, persisted)
    databricks: dict[str, Any] = {}
    if include_databricks:
        try:
            databricks = DatabricksContributor().inspect()
        except (OSError, ValueError, RuntimeError) as exc:
            databricks = {"overall": "INVALID", "auth_checked": False, "workspace_checked": False,
                          "reason": type(exc).__name__}
    return CurrentState(persisted, lifecycle, active, databricks)


def health(observation: CurrentState) -> dict[str, Any]:
    """Summarize local Anvil health without remote probes or state changes."""
    life = observation.lifecycle
    status = life["lifecycle"]
    if status in {"READY", "INSTALLED"}:
        overall = "READY"
    elif status in {"RECOVERABLE", "MIGRATION_REQUIRED", "STALE", "DEGRADED"}:
        overall = "RECOVERABLE"
    elif status in {"REPOSITORY_ONLY", "PARTIALLY_INSTALLED"}:
        overall = "NOT_CONFIGURED"
    else:
        overall = "FAILED"
    return {"overall": overall, "installation": status,
            "databricks_local": observation.databricks.get("overall", "NOT_CHECKED"),
            "remote_health": "NOT_CHECKED", "recovery": life.get("recovery")}


if __name__ == "__main__":
    import argparse
    from public_errors import run_public

    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--format", choices=("json",), default="json")
        parser.add_argument("--core-only", action="store_true")
        args = parser.parse_args()
        snapshot = resolve(include_databricks=not args.core_only)
        print(json.dumps({"schema_version": 1, "current": snapshot.as_dict(),
                          "health": health(snapshot)}, indent=2))
        return 0

    raise SystemExit(run_public(main, command="Anvil lifecycle observation"))
