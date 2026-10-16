"""Process boundary for the isolated official Databricks Python SDK."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .discovery import discover_sdk


def call(operation: str, *, profile: str | None = None, timeout: int = 120, **payload: Any) -> Any:
    state = {"providers": {}}
    provider = discover_sdk(state)
    override = os.environ.get("ANVIL_DATABRICKS_SDK_PYTHON")
    python = override or provider.get("python")
    if not python:
        raise RuntimeError("SDK provider is not installed")
    worker = Path(__file__).with_name("sdk_worker.py")
    request = {"operation": operation, "profile": None if profile == "__ANVIL_DEFAULT__" else profile,
               "timeout": timeout, "payload": payload}
    try:
        result = subprocess.run([str(python), str(worker)], input=json.dumps(request), text=True,
                                capture_output=True, timeout=max(15, timeout + 15), check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SDK request timed out") from exc
    if result.returncode:
        try:
            message = json.loads(result.stderr or "{}")
        except json.JSONDecodeError:
            message = {}
        raise RuntimeError(str(message.get("error", "SDK request failed"))[:240])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SDK returned invalid structured output") from exc
