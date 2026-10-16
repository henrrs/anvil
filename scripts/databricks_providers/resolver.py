"""Pure deterministic provider selection for Databricks capabilities."""

from __future__ import annotations

from typing import Any


CAPABILITY_ORDER: dict[str, tuple[str, ...]] = {
    "auth.status": ("cli", "sdk"),
    "auth.profiles": ("cli", "sdk"),
    "workspace.list": ("cli", "sdk"),
    "compute.list": ("cli", "sdk"),
    "compute.get": ("cli", "sdk"),
    "warehouse.list": ("cli", "sdk"),
    "warehouse.get": ("cli", "sdk"),
    "python.execute": ("cli", "sdk", "vscode"),
    "sql.execute": ("cli", "sdk", "sql_connector"),
    "system_tables.query": ("cli", "sdk", "sql_connector"),
    "jobs.list": ("cli", "sdk"),
    "jobs.get": ("cli", "sdk"),
    "pipelines.list": ("cli", "sdk"),
    "pipelines.get": ("cli", "sdk"),
    "spark.develop": ("connect", "vscode"),
    "bundles.run": ("cli", "vscode"),
}

PROVIDER_CAPABILITIES = {
    "cli": set(CAPABILITY_ORDER),
    "sdk": {"auth.status", "auth.profiles", "workspace.list", "compute.list", "compute.get",
            "warehouse.list", "warehouse.get", "python.execute", "sql.execute",
            "system_tables.query", "jobs.list", "jobs.get", "pipelines.list", "pipelines.get"},
    "sql_connector": {"sql.execute", "system_tables.query"},
    "connect": {"spark.develop"},
    "vscode": {"python.execute", "spark.develop", "bundles.run"},
}

PROVIDER_LABELS = {
    "cli": "CLI", "sdk": "SDK", "sql_connector": "SQL Connector",
    "connect": "Databricks Connect", "vscode": "VS Code",
}


def resolve(providers: dict[str, dict[str, Any]], *, auth_valid: bool,
            preferred_provider: str | None = None,
            allowed_providers: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Choose a provider per capability; assisted paths never count as headless."""
    result: dict[str, dict[str, Any]] = {}
    for capability, priority in CAPABILITY_ORDER.items():
        selected = None
        assisted = None
        ordered = tuple(dict.fromkeys(([preferred_provider] if preferred_provider else []) + list(priority)))
        for name in ordered:
            if allowed_providers is not None and name not in allowed_providers:
                continue
            state = providers.get(name, {})
            if capability not in PROVIDER_CAPABILITIES.get(name, set()):
                continue
            if name in {"cli", "sdk", "sql_connector", "connect"}:
                if state.get("status") == "READY" and auth_valid:
                    selected = name
                    break
            elif name == "vscode" and state.get("status") == "AVAILABLE":
                assisted = name
        if selected:
            result[capability] = {"provider": selected, "state": "READY", "headless": True}
        elif assisted:
            result[capability] = {"provider": assisted, "state": "ASSISTED", "headless": False}
        else:
            result[capability] = {"provider": None, "state": "UNAVAILABLE", "headless": False}
    return result


def overall_state(providers: dict[str, dict[str, Any]], capabilities: dict[str, dict[str, Any]], *, auth_valid: bool) -> str:
    if not auth_valid:
        # Provider installation health and workspace authentication are
        # distinct. Until identity is validated the integration is not set up,
        # even if an optional CLI install was blocked.
        return "NOT_CONFIGURED"
    core = ("workspace.list", "compute.list", "warehouse.list", "python.execute", "sql.execute")
    usable = sum(capabilities.get(name, {}).get("state") in {"READY", "ASSISTED"} for name in core)
    if usable == len(core):
        return "READY"
    if usable:
        return "DEGRADED"
    if any(p.get("status") == "BLOCKED" for p in providers.values()):
        return "BLOCKED"
    return "BROKEN"


def resolve_local(providers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Report locally installed providers without asserting workspace auth."""
    result: dict[str, dict[str, Any]] = {}
    for capability, priority in CAPABILITY_ORDER.items():
        selected = next((name for name in priority
                         if name in PROVIDER_CAPABILITIES.get(name, set())
                         and providers.get(name, {}).get("status") == "READY"
                         and name != "vscode"), None)
        assisted = next((name for name in priority
                         if name in PROVIDER_CAPABILITIES.get(name, set())
                         and providers.get(name, {}).get("status") == "AVAILABLE"), None)
        if selected:
            result[capability] = {"provider": selected, "state": "AVAILABLE", "headless": True,
                                  "auth_checked": False}
        elif assisted:
            result[capability] = {"provider": assisted, "state": "ASSISTED", "headless": False,
                                  "auth_checked": False}
        else:
            result[capability] = {"provider": None, "state": "UNAVAILABLE", "headless": False,
                                  "auth_checked": False}
    return result
