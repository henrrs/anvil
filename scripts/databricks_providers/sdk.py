"""Process boundary for the isolated official Databricks Python SDK."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import errors, owned_config, process, state as provider_state, timeouts
from .discovery import discover_sdk


def call(operation: str, *, profile: str | None = None, timeout: int = 120,
         config_path: str | None = None, python: str | None = None,
         **payload: Any) -> Any:
    if not python:
        try:
            provider = discover_sdk(provider_state.load_state())
        except (OSError, ValueError):
            provider = discover_sdk({"providers": {}})
        python = provider.get("python")
    if not python:
        raise errors.DatabricksError("PROVIDER_NOT_INSTALLED", "Databricks SDK provider is unavailable",
                                     provider="sdk", operation=operation, profile=profile)
    worker = Path(__file__).with_name("sdk_worker.py")
    request = {"operation": operation, "profile": profile, "timeout": timeout, "payload": payload}
    env = owned_config.child_environment(profile=profile, path=Path(config_path) if config_path else None)
    try:
        result = process.run([str(python), str(worker)], input_text=json.dumps(request),
                             timeout=min(600, max(15, timeout + timeouts.seconds_for("worker_overhead"))),
                             env=env)
    except process.ProcessFailure as exc:
        category = "SDK_PROCESS_TIMEOUT" if exc.category == "CLI_PROCESS_TIMEOUT" else exc.category
        raise errors.DatabricksError(category, f"Databricks SDK {operation} operation did not complete within its bounded process",
                                     provider="sdk", operation=operation, profile=profile, executable=str(python),
                                     timeout_seconds=timeout, elapsed_ms=exc.elapsed_ms) from exc
    except ValueError as exc:
        raise errors.DatabricksError("CLI_ARGUMENT_ERROR", "Databricks SDK request arguments are invalid",
                                     provider="sdk", operation=operation, profile=profile) from exc
    if result.returncode:
        try:
            message = json.loads(result.stderr or "{}")
        except json.JSONDecodeError:
            message = {}
        record = message.get("error", {}) if isinstance(message, dict) else {}
        category = record.get("category") if isinstance(record, dict) else None
        if category not in errors.POLICIES:
            category = "PROVIDER_UNHEALTHY"
        diagnostics = errors.safe_diagnostics(record)
        diagnostics.setdefault("operation", operation)
        raise errors.DatabricksError(category, f"Databricks SDK {operation} operation failed",
                                     provider="sdk", operation=operation, profile=profile, executable=str(python),
                                     diagnostics=diagnostics)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise errors.DatabricksError("PROVIDER_OUTPUT_INVALID", "Databricks SDK returned invalid structured output",
                                     provider="sdk", operation=operation, profile=profile, executable=str(python)) from exc
