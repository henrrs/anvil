"""Single evaluator for Databricks configuration and runtime readiness."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


STAGES = (
    "CONFIGURED",
    "AUTHENTICATED",
    "WORKSPACE_VALIDATED",
    "PROVIDER_VALIDATED",
    "CAPABILITIES_DISCOVERED",
    "READY",
)
CORE_CAPABILITIES = ("compute.list", "warehouse.list")
READINESS_TTL_SECONDS = 900


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_stale(value: Mapping[str, Any], *, max_age_seconds: int = READINESS_TTL_SECONDS,
             current_time: datetime | None = None) -> bool:
    checked = value.get("validated_at")
    if not isinstance(checked, str):
        return True
    try:
        stamp = datetime.fromisoformat(checked.replace("Z", "+00:00"))
    except ValueError:
        return True
    reference = current_time or datetime.now(timezone.utc)
    age = (reference - stamp).total_seconds()
    return age > max_age_seconds or age < -300


def evaluate(*, configured: bool, authentication: Mapping[str, Any],
             workspace: Mapping[str, Any], provider: Mapping[str, Any],
             capabilities: Mapping[str, Mapping[str, Any]],
             blockers: list[dict[str, Any]] | None = None,
             checked_at: str | None = None) -> dict[str, Any]:
    """Advance only through checks that have explicit successful evidence."""
    auth_ok = authentication.get("status") == "READY"
    workspace_ok = workspace.get("status") == "READY"
    provider_ok = provider.get("status") == "READY"
    attempted_core = all(name in capabilities and capabilities[name].get("checked") for name in CORE_CAPABILITIES)
    core_success = [name for name in CORE_CAPABILITIES
                    if capabilities.get(name, {}).get("verified") is True]
    stage = "CONFIGURED" if configured else "NOT_CONFIGURED"
    if configured and auth_ok:
        stage = "AUTHENTICATED"
    if stage == "AUTHENTICATED" and workspace_ok:
        stage = "WORKSPACE_VALIDATED"
    if stage == "WORKSPACE_VALIDATED" and provider_ok:
        stage = "PROVIDER_VALIDATED"
    if stage == "PROVIDER_VALIDATED" and attempted_core:
        stage = "CAPABILITIES_DISCOVERED"
    if stage == "CAPABILITIES_DISCOVERED" and len(core_success) == len(CORE_CAPABILITIES):
        stage = "READY"

    if not configured:
        overall = "NOT_CONFIGURED"
    elif not auth_ok or not workspace_ok:
        overall = "NOT_READY"
    elif not provider_ok:
        overall = "DEGRADED" if core_success else "NOT_READY"
    elif len(core_success) == len(CORE_CAPABILITIES):
        overall = "READY"
    elif core_success:
        # Partial permission is diagnosable and useful, but READY requires both
        # core read-only metadata paths to have been verified.
        overall = "DEGRADED"
    else:
        overall = "NOT_READY"

    return {
        "state": stage,
        "overall": overall,
        "validated_at": checked_at or now(),
        "stale_after_seconds": READINESS_TTL_SECONDS,
        "configuration": {"status": "READY" if configured else "NOT_CONFIGURED"},
        "authentication": dict(authentication),
        "workspace": dict(workspace),
        "provider": dict(provider),
        "capabilities": {key: dict(value) for key, value in capabilities.items()},
        "core_capabilities": list(CORE_CAPABILITIES),
        "verified_core_capabilities": core_success,
        "blockers": list(blockers or []),
    }
