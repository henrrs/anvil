"""Ordered, idempotent migrations for Anvil-owned installation metadata."""

from __future__ import annotations

from typing import Any, Callable


CURRENT_INSTALLATION_SCHEMA = 3


def _installation_1_to_2(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["schema_version"] = 2
    if "runtime_major" not in result and type(result.get("generation")) is int:
        result["runtime_major"] = result["generation"]
    return result


def _installation_2_to_3(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["schema_version"] = 3
    major = result.get("runtime_major")
    if type(major) is int and major in (1, 2):
        result.setdefault("runtime_profile", f"opencode-v{major}")
    return result


INSTALLATION_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _installation_1_to_2,
    2: _installation_2_to_3,
}


def migrate_installation(value: Any) -> dict[str, Any]:
    """Transform an Anvil-owned record in memory; the caller owns atomic write."""
    if not isinstance(value, dict):
        raise ValueError("installation record must be a JSON object")
    schema = value.get("schema_version", 1)
    if type(schema) is not int or schema < 1:
        raise ValueError("installation record has an invalid schema version")
    if schema > CURRENT_INSTALLATION_SCHEMA:
        raise ValueError("installation record schema is newer than this checkout")
    result = dict(value)
    while schema < CURRENT_INSTALLATION_SCHEMA:
        result = INSTALLATION_MIGRATIONS[schema](result)
        schema = result["schema_version"]
    return result
