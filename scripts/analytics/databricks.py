"""Thin Analytics adapter over the existing Anvil Databricks capability."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Protocol

from .errors import ProviderError

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
SHARED_MODULE_PATH = SCRIPT_ROOT / "databricks.py"
_SHARED_MODULE: Any = None


class CatalogMetadataPort(Protocol):
    def page(self, operation: str, **parameters: Any) -> dict[str, Any]: ...


class ComputePort(Protocol):
    """Small shared-capability boundary for SQL warehouse discovery."""

    def list_sql_warehouses(self, *, profile: str | None = None) -> dict[str, Any]: ...

    def get_sql_warehouse(self, warehouse_id: str, *, profile: str | None = None) -> dict[str, Any]: ...


def _shared_module() -> Any:
    global _SHARED_MODULE
    if _SHARED_MODULE is not None:
        return _SHARED_MODULE
    scripts_dir = str(SCRIPT_ROOT)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("_anvil_shared_databricks", SHARED_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ProviderError("The shared Anvil Databricks capability is unavailable", retryable=False)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError) as exc:
        sys.modules.pop(spec.name, None)
        raise ProviderError("The shared Anvil Databricks capability could not be loaded", retryable=False) from exc
    _SHARED_MODULE = module
    return module


class SharedDatabricksCatalogClient:
    """Delegates metadata, compute discovery, auth and provider choice to Anvil."""

    def __init__(self, page_call: Callable[..., dict[str, Any]] | None = None) -> None:
        self._page_call = page_call

    def current_identity(self, *, profile: str) -> dict[str, str]:
        """Use the selected Anvil profile's existing CLI/SDK auth capability."""
        try:
            response = _shared_module().json_from_cli(["current-user", "me"], profile=profile,
                                                       timeout=15)
        except Exception as exc:
            raise ProviderError("Databricks identity is temporarily unavailable",
                                code=str(getattr(exc, "category", "IDENTITY_UNAVAILABLE")),
                                retryable=True) from exc
        identity = response.get("identity") if isinstance(response, dict) and isinstance(response.get("identity"), dict) else response
        if not isinstance(identity, dict):
            raise ProviderError("Databricks returned an invalid identity", code="IDENTITY_INVALID")
        principal = str(identity.get("userName") or identity.get("user_name") or
                        identity.get("applicationId") or identity.get("id") or "")
        if not principal:
            raise ProviderError("Databricks returned an identity without a principal", code="IDENTITY_INVALID")
        kind = ("service_principal" if identity.get("applicationId") or identity.get("servicePrincipalName")
                else "user")
        return {"display_name": str(identity.get("displayName") or identity.get("display_name") or principal),
                "user_name": principal, "identity_type": kind}

    def page(self, operation: str, **parameters: Any) -> dict[str, Any]:
        try:
            call = self._page_call or _shared_module().unity_catalog_page
            return call(operation, **parameters)
        except Exception as exc:
            category = getattr(exc, "category", "PROVIDER_UNHEALTHY")
            if category not in {"PROVIDER_NOT_INSTALLED", "AUTH_REQUIRED", "AUTH_INVALID",
                                "PERMISSION_DENIED", "WORKSPACE_NETWORK_TIMEOUT",
                                "WORKSPACE_UNREACHABLE", "PROVIDER_UNHEALTHY",
                                "CLI_PROCESS_TIMEOUT", "SDK_PROCESS_TIMEOUT"}:
                category = "PROVIDER_UNHEALTHY"
            raise ProviderError("The shared Databricks metadata capability is unavailable",
                                code=category,
                                retryable=category in {"WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE",
                                                       "CLI_PROCESS_TIMEOUT", "SDK_PROCESS_TIMEOUT"}) from exc

    def list_sql_warehouses(self, *, profile: str | None = None) -> dict[str, Any]:
        try:
            result = _shared_module().discover_warehouses(profile)
            warehouses = result.get("warehouses")
            if not isinstance(warehouses, list):
                warehouses = [*result.get("running", []), *result.get("stopped", [])]
            return {"warehouses": [item for item in warehouses if isinstance(item, dict)]}
        except Exception as exc:
            category = getattr(exc, "category", getattr(exc, "code", "PROVIDER_UNHEALTHY"))
            allowed = {"PROVIDER_NOT_INSTALLED", "AUTH_REQUIRED", "AUTH_INVALID",
                       "PERMISSION_DENIED", "WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE",
                       "PROVIDER_UNHEALTHY", "CLI_PROCESS_TIMEOUT", "SDK_PROCESS_TIMEOUT",
                       "WORKSPACE_NOT_CONFIGURED", "PROFILE_NOT_CONFIGURED"}
            if category not in allowed:
                category = "PROVIDER_UNHEALTHY"
            raise ProviderError("The shared Anvil SQL warehouse capability is unavailable",
                                code=category,
                                retryable=category in {"WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE",
                                                       "CLI_PROCESS_TIMEOUT", "SDK_PROCESS_TIMEOUT"}) from exc

    def get_sql_warehouse(self, warehouse_id: str, *, profile: str | None = None) -> dict[str, Any]:
        if not isinstance(warehouse_id, str) or not warehouse_id or len(warehouse_id) > 256 \
                or any(ord(char) < 32 for char in warehouse_id):
            raise ProviderError("A valid SQL warehouse ID is required", code="INVALID_INPUT", retryable=False)
        try:
            value = _shared_module().get_warehouse(warehouse_id, profile)
            if not isinstance(value, dict):
                raise ProviderError("The shared Databricks capability returned invalid warehouse metadata",
                                    code="API_RESPONSE_INVALID", retryable=False)
            return value
        except ProviderError:
            raise
        except Exception as exc:
            category = getattr(exc, "category", getattr(exc, "code", "PROVIDER_UNHEALTHY"))
            if category not in {"PERMISSION_DENIED", "AUTH_REQUIRED", "AUTH_INVALID", "WAREHOUSE_NOT_FOUND",
                                "WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE", "PROVIDER_UNHEALTHY",
                                "WORKSPACE_NOT_CONFIGURED", "PROFILE_NOT_CONFIGURED"}:
                category = "PROVIDER_UNHEALTHY"
            raise ProviderError("The shared Anvil SQL warehouse capability could not read this warehouse",
                                code=category,
                                retryable=category in {"WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE"}) from exc

    def preview_table(self, full_name: str, warehouse_id: str, *, limit: int = 100,
                      profile: str | None = None, timeout: int = 120) -> dict[str, Any]:
        parts = full_name.split(".")
        if len(parts) != 3 or any(not part or any(ord(char) < 32 or char in "/\\" for char in part)
                                   for part in parts):
            raise ProviderError("A safe fully qualified table name is required", code="INVALID_INPUT",
                                retryable=False)
        if not warehouse_id or len(warehouse_id) > 256 or any(ord(char) < 32 for char in warehouse_id):
            raise ProviderError("A valid SQL warehouse selection is required", code="INVALID_INPUT",
                                retryable=False)
        bounded_limit = max(1, min(int(limit), 100))
        statement = "SELECT * FROM " + ".".join("`" + part.replace("`", "``") + "`" for part in parts)
        statement += f" LIMIT {bounded_limit}"
        try:
            return _shared_module().execute_sql(statement, warehouse_id, profile, timeout=timeout)
        except Exception as exc:
            category = getattr(exc, "category", "PROVIDER_UNHEALTHY")
            raise ProviderError("The shared Databricks SQL capability could not preview the table",
                                code=category) from exc

    def execute_sql(self, statement: str, warehouse_id: str, *,
                    profile: str | None = None, timeout: int = 120) -> dict[str, Any]:
        try:
            result = _shared_module().execute_sql(statement, warehouse_id, profile, timeout=timeout)
            if not isinstance(result, dict):
                raise ProviderError("The shared Databricks SQL capability returned invalid data")
            return result
        except ProviderError:
            raise
        except Exception as exc:
            category = getattr(exc, "category", "PROVIDER_UNHEALTHY")
            if str(category).startswith("WAREHOUSE_START_") or category in {"WAREHOUSE_UNAVAILABLE", "WAREHOUSE_NOT_FOUND"}:
                raise ProviderError(str(exc), code=str(category), retryable=False) from exc
            raise ProviderError("The shared Databricks SQL capability is unavailable",
                                code=category,
                                retryable=category in {"WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE",
                                                       "CLI_PROCESS_TIMEOUT", "SDK_PROCESS_TIMEOUT"}) from exc

    def transfer_submit(self, statement: str, warehouse_id: str, *, profile: str | None = None,
                        max_rows: int | None = None, max_bytes: int | None = None,
                        timeout: int = 120,
                        on_warehouse_ready: Any | None = None) -> dict[str, Any]:
        return self._transfer_call("start_sql_transfer", statement, warehouse_id,
                                   profile=profile, max_rows=max_rows,
                                   max_bytes=max_bytes, timeout=timeout,
                                   on_warehouse_ready=on_warehouse_ready)

    def transfer_status(self, statement_id: str, warehouse_id: str, *,
                        profile: str | None = None, timeout: int = 120) -> dict[str, Any]:
        return self._transfer_call("sql_transfer_status", statement_id, warehouse_id,
                                   profile=profile, timeout=timeout)

    def transfer_chunk(self, statement_id: str, chunk_index: int, warehouse_id: str, *,
                       profile: str | None = None, timeout: int = 60) -> dict[str, Any]:
        return self._transfer_call("sql_transfer_chunk", statement_id, chunk_index, warehouse_id,
                                   profile=profile, timeout=timeout)

    def transfer_cancel(self, statement_id: str, *, profile: str | None = None,
                        timeout: int = 30) -> dict[str, Any]:
        return self._transfer_call("cancel_sql_transfer", statement_id,
                                   profile=profile, timeout=timeout)

    @staticmethod
    def _transfer_call(function_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            result = getattr(_shared_module(), function_name)(*args, **kwargs)
            if not isinstance(result, dict):
                raise ProviderError("The shared Databricks transfer capability returned invalid data")
            return result
        except ProviderError:
            raise
        except Exception as exc:
            category = getattr(exc, "category", "PROVIDER_UNHEALTHY")
            raise ProviderError("The shared Databricks transfer capability is unavailable",
                                code=category,
                                retryable=category in {"WORKSPACE_NETWORK_TIMEOUT", "WORKSPACE_UNREACHABLE",
                                                       "CLI_PROCESS_TIMEOUT", "SDK_PROCESS_TIMEOUT"}) from exc
