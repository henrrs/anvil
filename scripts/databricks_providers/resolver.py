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
            allowed_providers: set[str] | None = None,
            provider_failures: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Choose a provider per capability; assisted paths never count as headless."""
    result: dict[str, dict[str, Any]] = {}
    for capability, priority in CAPABILITY_ORDER.items():
        selected = None
        assisted = None
        ordered = tuple(dict.fromkeys(([preferred_provider] if preferred_provider else []) + list(priority)))
        rejected: list[dict[str, str]] = []
        for name in ordered:
            if allowed_providers is not None and name not in allowed_providers:
                if capability in PROVIDER_CAPABILITIES.get(name, set()):
                    rejected.append({"provider": name, "reason": "blocked by selected authentication strategy"})
                continue
            state = providers.get(name, {})
            if capability not in PROVIDER_CAPABILITIES.get(name, set()):
                continue
            if name in {"cli", "sdk", "sql_connector", "connect"}:
                provider_failure = (provider_failures or {}).get(name)
                if state.get("status") == "READY" and auth_valid and not provider_failure:
                    selected = name
                    break
                rejected.append({"provider": name,
                                 "reason": provider_failure or str(state.get("failure") or state.get("status", "unavailable"))})
            elif name == "vscode" and state.get("status") == "AVAILABLE":
                assisted = name
        if selected:
            fallback_reason = (rejected[0]["reason"] if rejected
                               and rejected[0]["provider"] == priority[0] else None)
            result[capability] = {"provider": selected, "state": "READY", "headless": True,
                                  "capability": capability, "selected_provider": selected,
                                  "fallback_reason": fallback_reason,
                                  "rejected_providers": rejected, "blocking_condition": None}
        elif assisted:
            result[capability] = {"provider": assisted, "state": "ASSISTED", "headless": False,
                                  "capability": capability, "selected_provider": assisted,
                                  "fallback_reason": None, "rejected_providers": rejected,
                                  "blocking_condition": None}
        else:
            result[capability] = {"provider": None, "state": "UNAVAILABLE", "headless": False,
                                  "capability": capability, "selected_provider": None,
                                  "fallback_reason": None, "rejected_providers": rejected,
                                  "blocking_condition": (provider_failures or {}).get(
                                      next((name for name in priority if name in (provider_failures or {})), ""))
                                  or (rejected[0]["reason"] if rejected else "no compatible provider installed")}
    return result


def candidates(capability: str, providers: dict[str, dict[str, Any]], *,
               preferred_provider: str | None = None,
               allowed_providers: set[str] | None = None) -> list[str]:
    """Return a deterministic ordered list of installed, capable providers."""
    priority = CAPABILITY_ORDER.get(capability, ())
    ordered = tuple(dict.fromkeys(([preferred_provider] if preferred_provider else []) + list(priority)))
    return [name for name in ordered
            if (allowed_providers is None or name in allowed_providers)
            and capability in PROVIDER_CAPABILITIES.get(name, set())
            and providers.get(name, {}).get("status") == "READY"]


def candidate_rejections(capability: str, providers: dict[str, dict[str, Any]], *,
                         preferred_provider: str | None = None,
                         allowed_providers: set[str] | None = None) -> list[dict[str, str]]:
    """Explain capable providers excluded before any remote call is made."""
    priority = CAPABILITY_ORDER.get(capability, ())
    ordered = tuple(dict.fromkeys(([preferred_provider] if preferred_provider else []) + list(priority)))
    rejected: list[dict[str, str]] = []
    for name in ordered:
        if capability not in PROVIDER_CAPABILITIES.get(name, set()):
            continue
        if allowed_providers is not None and name not in allowed_providers:
            rejected.append({"provider": name, "category": "PROVIDER_BLOCKED",
                             "reason": "not allowed by the selected authentication strategy"})
            continue
        state = providers.get(name, {})
        if state.get("status") == "READY":
            continue
        status = str(state.get("status", "UNKNOWN"))
        category = ("PROVIDER_NOT_INSTALLED" if status in {"NOT_INSTALLED", "UNKNOWN"}
                    else "PROVIDER_BLOCKED" if status == "BLOCKED"
                    else "PROVIDER_UNHEALTHY")
        rejected.append({"provider": name, "category": category,
                         "reason": str(state.get("failure") or status)})
    return rejected


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
