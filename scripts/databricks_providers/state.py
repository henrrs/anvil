"""Atomic, non-secret Databricks provider state."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
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


def load_state() -> dict[str, Any]:
    try:
        value = json.loads(state_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": SCHEMA_VERSION, "selected_profile": None, "workspace_host": None,
                "providers": {}, "capabilities": {}, "authentication": None}
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
    if not isinstance(result["providers"], dict) or not isinstance(result["capabilities"], dict):
        raise ValueError("Anvil Databricks provider state has invalid provider records")
    authentication = result["authentication"]
    if authentication is not None:
        if (not isinstance(authentication, dict)
                or authentication.get("strategy") not in {"databricks-cli-u2m", "azure-cli-session"}
                or authentication.get("provider") not in {"cli", "sdk"}
                or authentication.get("cloud") not in {"azure", "aws", "gcp", "unknown"}):
            raise ValueError("Anvil Databricks provider state has invalid authentication metadata")
    return result


def save_state(value: dict[str, Any]) -> Path:
    if not isinstance(value, dict):
        raise ValueError("Anvil Databricks provider state must be a JSON object")
    result = dict(value)
    result["schema_version"] = SCHEMA_VERSION
    result["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _validate_secret_free(result)
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
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path
