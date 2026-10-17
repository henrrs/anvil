"""Optional SQL Connector execution using the official driver's U2M auth."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import errors, owned_config, process, timeouts


def execute(*, profile: str, host: str, http_path: str, statement: str,
            parameters: list[dict[str, Any]] | None, timeout: int,
            config_path: str | None = None) -> dict[str, Any]:
    worker = Path(__file__).with_name("sql_connector_worker.py")
    if not profile.startswith("anvil-"):
        raise RuntimeError("SQL Connector requires an Anvil-owned Databricks profile")
    env = owned_config.child_environment(profile=profile,
                                         path=Path(config_path) if config_path else None)
    request = {"host": host, "http_path": http_path, "statement": statement,
               "parameters": parameters, "timeout": max(5, min(timeout, 600))}
    try:
        result = process.run([sys.executable, str(worker)], input_text=json.dumps(request),
                             timeout=min(timeouts.seconds_for("long_operation_max"),
                                         max(15, min(timeout, 600) + timeouts.seconds_for("worker_overhead"))),
                             env=env)
    except process.ProcessFailure as exc:
        category = "SQL_CONNECTOR_PROCESS_TIMEOUT" if exc.category == "CLI_PROCESS_TIMEOUT" else exc.category
        raise errors.DatabricksError(category, "Databricks SQL Connector operation did not complete within its bounded process",
                                     provider="sql_connector", operation="sql.execute", profile=profile,
                                     timeout_seconds=timeout, elapsed_ms=exc.elapsed_ms) from exc
    if result.returncode:
        try:
            error = json.loads(result.stderr or "{}").get("error", {})
        except (json.JSONDecodeError, AttributeError):
            error = {}
        category = error.get("category") if isinstance(error, dict) else None
        if category not in errors.POLICIES:
            category = "PROVIDER_UNHEALTHY"
        raise errors.DatabricksError(category, "Databricks SQL Connector operation failed",
                                     provider="sql_connector", operation="sql.execute", profile=profile)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise errors.DatabricksError("PROVIDER_OUTPUT_INVALID", "SQL Connector returned invalid structured output",
                                     provider="sql_connector", operation="sql.execute", profile=profile) from exc
    if not isinstance(value, dict):
        raise errors.DatabricksError("PROVIDER_OUTPUT_INVALID", "SQL Connector returned an invalid result",
                                     provider="sql_connector", operation="sql.execute", profile=profile)
    return value
