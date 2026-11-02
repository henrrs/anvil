"""One local fact resolver for lifecycle observers and planners.

Remote Databricks health is intentionally outside this local snapshot. A caller
may request a separate live probe, but must label it as such in its output.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import lifecycle_state
from lifecycle_contributors import AnalyticsContributor, DatabricksContributor, OpenCodeContributor
from lifecycle_model import PersistedState, resolve_persisted


@dataclass(frozen=True)
class CurrentState:
    """The resolved, read-only lifecycle snapshot used by projections and plans."""

    persisted: PersistedState
    lifecycle: dict[str, Any]
    active_runtime: dict[str, Any]
    analytics: dict[str, Any]
    databricks: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve(*, include_analytics: bool = True, include_databricks: bool = True) -> CurrentState:
    paths = lifecycle_state.paths()
    persisted = resolve_persisted(paths["home"], paths["config"].parent, paths["data"].parent)
    active = OpenCodeContributor().inspect()
    lifecycle = lifecycle_state.evaluate(active, persisted)
    analytics: dict[str, Any] = {}
    if include_analytics:
        try:
            analytics = AnalyticsContributor().inspect(paths["config"], paths["home"])
        except (OSError, ValueError) as exc:
            analytics = {"status": "INVALID", "reason": type(exc).__name__}
    databricks: dict[str, Any] = {}
    if include_databricks:
        try:
            databricks = DatabricksContributor().inspect()
        except (OSError, ValueError, RuntimeError) as exc:
            databricks = {"overall": "INVALID", "auth_checked": False, "workspace_checked": False,
                          "reason": type(exc).__name__}
    return CurrentState(persisted, lifecycle, active, analytics, databricks)


def health(observation: CurrentState) -> dict[str, Any]:
    """Summarize local health without reaching a remote provider or changing state."""
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
    analytics = observation.analytics
    service = analytics.get("service") if isinstance(analytics.get("service"), dict) else {}
    deps = {name: (analytics.get(name) or {}).get("status", "NOT_CHECKED")
            if isinstance(analytics.get(name), dict) else "INVALID"
            for name in ("duckdb", "pyarrow")}
    if overall == "READY" and service.get("status") not in {"READY", "NOT_INSTALLED", None}:
        overall = "DEGRADED"
    if overall == "READY" and any(value in {"MISSING", "INVALID", "DEGRADED"} for value in deps.values()):
        overall = "DEGRADED"
    return {"overall": overall, "installation": status,
            "analytics_service": service.get("status", "NOT_CHECKED"),
            "analytics_dependencies": deps,
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
        snapshot = resolve(include_analytics=not args.core_only, include_databricks=not args.core_only)
        print(json.dumps({"schema_version": 1, "current": snapshot.as_dict(),
                          "health": health(snapshot)}, indent=2))
        return 0

    raise SystemExit(run_public(main, command="Anvil lifecycle observation"))
