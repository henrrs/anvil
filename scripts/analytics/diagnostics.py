"""Shared read-only Analytics readiness snapshot for Anvil commands."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from ..lifecycle_model import DocumentStatus, normalize_analytics_session
except ImportError:  # repository-side scripts import analytics as a top-level package
    from lifecycle_model import DocumentStatus, normalize_analytics_session


def _section(value: Any, *, fallback: str = "INVALID") -> dict[str, Any]:
    """Do not let an untrusted service response become a lifecycle object."""
    if not isinstance(value, dict):
        return {"status": fallback, "reason_code": "INVALID_STATE_SHAPE"}
    result = dict(value)
    if not isinstance(result.get("status"), str):
        result["status"] = fallback
    return result


def _normalized_api(value: dict[str, Any], service: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    for name in ("opencode", "runtime", "canonical_session", "duckdb", "pyarrow", "catalog", "databricks"):
        result[name] = _section(value.get(name), fallback="NOT_CHECKED" if name == "databricks" else "INVALID")
    result["service"] = {**service, "api": "READY"}
    return result


def _api_status(port: int) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/runtime",
            headers={"Host": f"127.0.0.1:{port}", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=1.5) as response:
            value = json.loads(response.read(256 * 1024).decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def collect(config_dir: Path, home: Path, port: int | None = None) -> dict[str, Any]:
    home = home.expanduser().absolute()
    config_dir = config_dir.expanduser().absolute()
    selected_port = port or int(os.environ.get("ANVIL_ANALYTICS_PORT", "8765"))
    systemd_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "systemd" / "user"
    from analytics_service import service_state

    service = service_state(config_dir, home, systemd_dir, selected_port)
    api = _api_status(selected_port)
    if api:
        return _normalized_api(api, service)
    runtime_file = home / ".anvil" / "analytics" / "runtime.json"
    runtime = normalize_analytics_session(runtime_file)
    local_status = ("NOT_CHECKED" if runtime.document.status == DocumentStatus.NOT_PRESENT
                    else "DEGRADED" if runtime.document.status in {DocumentStatus.CURRENT, DocumentStatus.LEGACY}
                    else "INVALID")
    return {
        "service": {**service, "api": "NOT_READY"},
        "opencode": {"status": local_status},
        "runtime": {"status": local_status},
        "canonical_session": {"status": local_status, "state_schema": runtime.document.status.value},
        "duckdb": {"status": "NOT_CHECKED", "reason_code": "SERVICE_UNAVAILABLE"},
        "pyarrow": {"status": "NOT_CHECKED", "reason_code": "SERVICE_UNAVAILABLE"},
        "catalog": {"status": "NOT_CHECKED", "catalogs": 0, "schemas": 0,
                    "tables": 0, "views": 0, "objects": 0},
    }
