"""Optional SQL Connector execution using the official driver's U2M auth."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import owned_config


def execute(*, profile: str, host: str, http_path: str, statement: str,
            parameters: list[dict[str, Any]] | None, timeout: int) -> dict[str, Any]:
    worker = Path(__file__).with_name("sql_connector_worker.py")
    if not profile.startswith("anvil-"):
        raise RuntimeError("SQL Connector requires an Anvil-owned Databricks profile")
    env = owned_config.child_environment(profile=profile)
    request = {"host": host, "http_path": http_path, "statement": statement,
               "parameters": parameters, "timeout": max(5, min(timeout, 600))}
    try:
        result = subprocess.run([sys.executable, str(worker)], input=json.dumps(request), text=True,
                                capture_output=True, timeout=max(15, min(timeout, 600) + 15), env=env, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SQL Connector request timed out") from exc
    if result.returncode:
        raise RuntimeError("Databricks SQL Connector request failed; check Unified Authentication and warehouse access")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SQL Connector returned invalid structured output") from exc
    if not isinstance(value, dict):
        raise RuntimeError("SQL Connector returned an invalid result")
    return value
