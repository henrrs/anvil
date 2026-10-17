"""Atomic, non-secret Databricks provider state."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3
FORBIDDEN_KEYS = {
    "token", "access_token", "refresh_token", "password", "client_secret",
    "secret", "credential", "credentials", "signed_url", "signedurl",
}


def config_root() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def state_path() -> Path:
    return config_root() / "anvil" / "databricks.json"


def data_root() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "anvil" / "databricks"


def _validate_secret_free(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            folded = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).casefold().replace("-", "_")
            fields = set(filter(None, re.split(r"[^a-z0-9]+", folded)))
            if (folded in FORBIDDEN_KEYS or fields.intersection({"token", "password", "secret", "credential", "credentials", "authorization", "cookie"})
                    or folded.endswith("_token") or folded.endswith("_secret")):
                raise ValueError("Databricks provider state must not contain credential fields")
            _validate_secret_free(child)
    elif isinstance(value, list):
        for child in value:
            _validate_secret_free(child)


def _validate_readiness(readiness: Any) -> None:
    stages = {"NOT_CONFIGURED", "CONFIGURED", "AUTHENTICATED", "WORKSPACE_VALIDATED",
              "PROVIDER_VALIDATED", "CAPABILITIES_DISCOVERED", "READY"}
    overall = {"NOT_CONFIGURED", "NOT_READY", "DEGRADED", "READY", "STALE"}
    if (not isinstance(readiness, dict)
            or readiness.get("state") not in stages
            or readiness.get("overall") not in overall
            or not isinstance(readiness.get("validated_at"), str)
            or not isinstance(readiness.get("authentication"), dict)
            or not isinstance(readiness.get("workspace"), dict)
            or not isinstance(readiness.get("provider"), dict)
            or not isinstance(readiness.get("capabilities"), dict)):
        raise ValueError("Anvil Databricks provider state has invalid readiness metadata")
    if readiness.get("overall") == "READY":
        provider_record = readiness["provider"]
        capabilities = readiness["capabilities"]
        verified = all(
            isinstance(capabilities.get(name), dict)
            and capabilities[name].get("checked") is True
            and capabilities[name].get("verified") is True
            and isinstance(capabilities[name].get("provider"), str)
            and isinstance(capabilities[name].get("validated_at"), str)
            for name in ("compute.list", "warehouse.list")
        )
        if (readiness.get("state") != "READY"
                or readiness.get("authentication", {}).get("status") != "READY"
                or readiness.get("workspace", {}).get("status") != "READY"
                or provider_record.get("status") != "READY"
                or provider_record.get("selected") not in {"cli", "sdk"}
                or not isinstance(provider_record.get("validation_probe"), str)
                or not isinstance(provider_record.get("validated_at"), str)
                or not verified):
            raise ValueError("READY Databricks state requires fresh provider and core capability validation evidence")


def load_state() -> dict[str, Any]:
    try:
        value = json.loads(state_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": SCHEMA_VERSION, "selected_profile": None, "workspace_host": None,
                "providers": {}, "capabilities": {}, "authentication": None,
                "profile": None, "workspace": None, "readiness": None}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Anvil Databricks provider state cannot be read") from exc
    if not isinstance(value, dict):
        raise ValueError("Anvil Databricks provider state must be a JSON object")
    _validate_secret_free(value)
    version = value.get("schema_version", 1)
    if not isinstance(version, int) or version < 1 or version > SCHEMA_VERSION:
        raise ValueError("Anvil Databricks provider state has an unsupported schema version")
    # Version 1 was the 2.2 profile-only preference record. Keep its fields and
    # add provider records lazily; no authentication is rewritten or migrated.
    result = dict(value)
    result["schema_version"] = SCHEMA_VERSION
    result.setdefault("selected_profile", None)
    result.setdefault("workspace_host", None)
    result.setdefault("providers", {})
    result.setdefault("capabilities", {})
    result.setdefault("authentication", None)
    result.setdefault("profile", None)
    result.setdefault("workspace", None)
    result.setdefault("readiness", None)
    if not isinstance(result["providers"], dict) or not isinstance(result["capabilities"], dict):
        raise ValueError("Anvil Databricks provider state has invalid provider records")
    authentication = result["authentication"]
    if authentication is not None:
        if (not isinstance(authentication, dict)
                or authentication.get("strategy") not in {"databricks-cli-u2m", "azure-cli-session",
                                                           "azure-cli-device-code", "azure-cli-interactive",
                                                           "unified-auth"}
                or authentication.get("provider") not in {"cli", "sdk"}
                or authentication.get("cloud") not in {"azure", "aws", "gcp", "unknown"}):
            raise ValueError("Anvil Databricks provider state has invalid authentication metadata")
    profile = result["profile"]
    if profile is not None:
        if (not isinstance(profile, dict) or profile.get("ownership") != "anvil"
                or not isinstance(profile.get("name"), str)
                or not profile["name"].startswith("anvil-")
                or not isinstance(profile.get("config_file"), str)):
            raise ValueError("Anvil Databricks provider state has invalid profile ownership metadata")
    workspace = result["workspace"]
    if workspace is not None:
        if (not isinstance(workspace, dict) or not isinstance(workspace.get("host"), str)
                or not isinstance(workspace.get("environment"), str)):
            raise ValueError("Anvil Databricks provider state has invalid workspace metadata")
    readiness = result["readiness"]
    if readiness is not None:
        _validate_readiness(readiness)
    return result


def save_state(value: dict[str, Any]) -> Path:
    if not isinstance(value, dict):
        raise ValueError("Anvil Databricks provider state must be a JSON object")
    result = dict(value)
    result["schema_version"] = SCHEMA_VERSION
    result["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _validate_secret_free(result)
    if result.get("readiness") is not None:
        _validate_readiness(result["readiness"])
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".databricks.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path
