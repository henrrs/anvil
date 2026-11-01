"""Shared read-only Analytics readiness snapshot for Anvil commands."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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
        return {**api, "service": {**service, "api": "READY"}}
    runtime_file = home / ".anvil" / "analytics" / "runtime.json"
    runtime: dict[str, Any] = {}
    try:
        value = json.loads(runtime_file.read_text(encoding="utf-8"))
        runtime = value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return {
        "service": {**service, "api": "NOT_READY"},
        "opencode": {"status": "NOT_CHECKED" if not runtime else "DEGRADED"},
        "runtime": {"status": "NOT_CHECKED" if not runtime else "DEGRADED"},
        "canonical_session": {"status": "NOT_CHECKED" if not runtime else "DEGRADED"},
        "duckdb": {"status": "NOT_CHECKED", "reason_code": "SERVICE_UNAVAILABLE"},
        "pyarrow": {"status": "NOT_CHECKED", "reason_code": "SERVICE_UNAVAILABLE"},
        "catalog": {"status": "NOT_CHECKED", "catalogs": 0, "schemas": 0,
                    "tables": 0, "views": 0, "objects": 0},
    }
