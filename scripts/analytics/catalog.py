"""Progressively hydrated Unity Catalog cache with lazy table descriptions."""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from typing import Any

from .databricks import CatalogMetadataPort
from .errors import AnalyticsError, ProviderError, ValidationError
from .models import CatalogObject, CatalogObjectType
from .store import ContextStore

PAGE_SIZE = 50
MAX_PAGES = 2000
MAX_ROWS = 100_000
RETRIES = 3
MAX_METADATA_CONCURRENCY = 2
_LOG = logging.getLogger(__name__)


def _log_event(level: int, event: str, **details: Any) -> None:
    _LOG.log(level, json.dumps({"event": event, **details}, sort_keys=True, separators=(",", ":")))


class CatalogService:
    def __init__(self, store: ContextStore, provider: CatalogMetadataPort | None) -> None:
        self.store = store
        self.provider = provider
        self._provider_slots = threading.BoundedSemaphore(MAX_METADATA_CONCURRENCY)

    def catalogs(self, *, refresh: bool = False, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if refresh:
            return self._refresh_list("catalogs.list", "catalogs", parent="",
                                      object_type=CatalogObjectType.CATALOG,
                                      limit=limit, offset=offset)
        return self._cached(parent="", object_type=CatalogObjectType.CATALOG,
                            limit=limit, offset=offset)

    def schemas(self, catalog_name: str, *, refresh: bool = False,
                limit: int = 100, offset: int = 0) -> dict[str, Any]:
        self._validate_component(catalog_name, "catalog")
        if refresh:
            return self._refresh_list("schemas.list", "schemas", parent=catalog_name,
                                      object_type=CatalogObjectType.SCHEMA,
                                      catalog_name=catalog_name, limit=limit, offset=offset)
        return self._cached(parent=catalog_name, object_type=CatalogObjectType.SCHEMA,
                            limit=limit, offset=offset)

    def tables(self, catalog_name: str, schema_name: str, *, refresh: bool = False,
               limit: int = 100, offset: int = 0) -> dict[str, Any]:
        self._validate_component(catalog_name, "catalog")
        self._validate_component(schema_name, "schema")
        parent = f"{catalog_name}.{schema_name}"
        if refresh:
            _log_event(logging.INFO, "metadata_refresh_started", scope="tables")
            self.store.catalog_hydration_set("tables", parent, "LOADING")
            try:
                rows = self._fetch_all("tables.list", catalog_name=catalog_name,
                                       schema_name=schema_name)
                objects = [self._table_object(row, catalog_name, schema_name) for row in rows]
                self.store.catalog_reconcile(parent, objects)
                self.store.catalog_hydration_set("tables", parent, "READY" if objects else "EMPTY",
                                                  object_count=len(objects))
                _log_event(logging.INFO, "metadata_refresh_completed", scope="tables",
                           count=len(objects),
                           tables_discovered=sum(item.object_type == CatalogObjectType.TABLE for item in objects),
                           views_discovered=sum(item.object_type == CatalogObjectType.VIEW for item in objects))
                return self._cached(parent=parent, status="READY", limit=limit, offset=offset)
            except AnalyticsError as exc:
                self.store.catalog_hydration_set("tables", parent, "FAILED", error_code=exc.code,
                                                  error_message=str(exc)[:500])
                _log_event(logging.WARNING, "metadata_refresh_failed", scope="tables", reason_code=exc.code)
                return self._cached(parent=parent, status="BROWSE_ONLY", error=exc.code,
                                    limit=limit, offset=offset)
        return self._cached(parent=parent, object_type=None, limit=limit, offset=offset)

    def describe(self, full_name: str, *, refresh: bool = False) -> dict[str, Any]:
        self._validate_full_name(full_name)
        parts = full_name.split(".")
        parent = ".".join(parts[:-1]) if len(parts) > 1 else ""
        cached = next((row for row in self.store.catalog_list(parent=parent, limit=2000)
                       if row["full_name"] == full_name), None)
        if cached and cached["columns"] and not refresh:
            return {"status": "CACHED", "object": cached}
        if not self.provider:
            return {"status": "BROWSE_ONLY", "object": cached, "error": "PROVIDER_NOT_CONFIGURED"}
        try:
            detail = self.provider.page("tables.get", full_name=full_name)
            obj = self._table_object(detail, *parts[:2], full_name_override=full_name)
            self.store.catalog_upsert([obj])
            fresh = next((row for row in self.store.catalog_list(parent=parent, limit=2000)
                          if row["full_name"] == full_name), obj.as_dict())
            return {"status": "READY", "object": fresh}
        except AnalyticsError as exc:
            return {"status": "BROWSE_ONLY", "object": cached, "error": exc.code}

    def preview(self, full_name: str, warehouse_id: str, *, limit: int = 100) -> dict[str, Any]:
        self._validate_full_name(full_name)
        if not self.provider or not hasattr(self.provider, "preview_table"):
            return {"status": "BROWSE_ONLY", "error": "SQL_PROVIDER_NOT_CONFIGURED"}
        try:
            bounded_limit = max(1, min(int(limit), 100))
            result = self.provider.preview_table(full_name, warehouse_id, limit=bounded_limit)
            if not isinstance(result, dict):
                raise ProviderError("Databricks returned an invalid preview response", retryable=False)
            return {"status": "READY", **result}
        except AnalyticsError as exc:
            return {"status": "BROWSE_ONLY", "error": exc.code}

    def refresh_scope(self, scope: str, *, catalog_name: str = "", schema_name: str = "",
                      limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if scope == "catalogs":
            return self.catalogs(refresh=True, limit=limit, offset=offset)
        if scope == "schemas":
            return self.schemas(catalog_name, refresh=True, limit=limit, offset=offset)
        if scope == "tables":
            return self.tables(catalog_name, schema_name, refresh=True, limit=limit, offset=offset)
        raise ValidationError("Metadata refresh scope must be catalogs, schemas or tables")

    def _refresh_list(self, operation: str, key: str, *, parent: str,
                      object_type: CatalogObjectType, limit: int, offset: int,
                      **parameters: str) -> dict[str, Any]:
        scope = key
        _log_event(logging.INFO, "metadata_refresh_started", scope=scope)
        self.store.catalog_hydration_set(scope, parent, "LOADING")
        try:
            rows = self._fetch_all(operation, **parameters)
            objects: list[CatalogObject] = []
            for row in rows:
                name = str(row.get("name") or row.get("catalog_name") or row.get("schema_name") or "")
                if not name:
                    continue
                full_name = str(row.get("full_name") or (f"{parent}.{name}" if parent else name))
                objects.append(CatalogObject(full_name, object_type,
                    workspace_id=str(row.get("workspace_id") or ""), parent_name=parent,
                    comment=str(row.get("comment") or ""),
                    properties=self._properties(row), updated_at=str(row.get("updated_at") or "")))
            self.store.catalog_reconcile(parent, objects)
            self.store.catalog_hydration_set(scope, parent, "READY" if objects else "EMPTY",
                                              object_count=len(objects))
            _log_event(logging.INFO, "metadata_refresh_completed",
                scope=scope, count=len(objects),
                catalogs_discovered=len(objects) if scope == "catalogs" else None,
                schemas_discovered=len(objects) if scope == "schemas" else None,
                tables_discovered=sum(item.object_type == CatalogObjectType.TABLE for item in objects)
                    if scope == "tables" else None,
                views_discovered=sum(item.object_type == CatalogObjectType.VIEW for item in objects)
                    if scope == "tables" else None)
            return self._cached(parent=parent, object_type=object_type, status="READY",
                                limit=limit, offset=offset)
        except AnalyticsError as exc:
            self.store.catalog_hydration_set(scope, parent, "FAILED", error_code=exc.code,
                                              error_message=str(exc)[:500])
            _log_event(logging.WARNING, "metadata_refresh_failed", scope=scope, reason_code=exc.code)
            return self._cached(parent=parent, object_type=object_type,
                                status="BROWSE_ONLY", error=exc.code, limit=limit, offset=offset)

    def _fetch_all(self, operation: str, **parameters: Any) -> list[dict[str, Any]]:
        if not self.provider:
            raise ProviderError("The Databricks metadata provider is not configured",
                                code="PROVIDER_NOT_CONFIGURED", retryable=False)
        collection = operation.split(".", 1)[0]
        values: list[dict[str, Any]] = []
        page_token = None
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            request: dict[str, Any] = {**parameters, "max_results": PAGE_SIZE}
            if operation == "tables.list":
                request.update({"omit_columns": True, "omit_properties": True})
            if page_token:
                request["page_token"] = page_token
            for attempt in range(RETRIES + 1):
                try:
                    with self._provider_slots:
                        result = self.provider.page(operation, **request)
                    break
                except AnalyticsError as exc:
                    if not exc.retryable or attempt == RETRIES:
                        raise
                    time.sleep(min(2.0, 0.2 * (2 ** attempt)) + random.uniform(0, 0.15))
            page_rows = result.get(collection)
            if not isinstance(page_rows, list):
                if operation == "tables.get":
                    return [result]
                raise ProviderError("Databricks returned an invalid catalog page", retryable=False)
            values.extend(row for row in page_rows if isinstance(row, dict))
            if len(values) > MAX_ROWS:
                raise ProviderError("Databricks catalog scope exceeded the safe metadata row limit",
                                    code="CATALOG_ROW_LIMIT", retryable=False)
            next_token = result.get("next_page_token") or result.get("nextPageToken")
            if not next_token:
                return values
            page_token = str(next_token)
            if page_token in seen:
                raise ProviderError("Databricks catalog pagination repeated a page token",
                                    code="CATALOG_PAGINATION_INVALID", retryable=False)
            seen.add(page_token)
        raise ProviderError("Databricks catalog exceeded the safe pagination limit",
                            code="CATALOG_PAGINATION_LIMIT", retryable=False)

    def _cached(self, *, parent: str, object_type: CatalogObjectType | None = None,
                status: str | None = None, error: str | None = None,
                limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 10_000_000:
            raise ValidationError("Catalog page size or offset is invalid")
        rows = self.store.catalog_list(parent=parent, object_type=object_type.value if object_type else None,
                                       limit=limit + 1, offset=offset)
        has_more = len(rows) > limit
        items = rows[:limit]
        scope = "catalogs" if object_type == CatalogObjectType.CATALOG or parent == "" else (
            "schemas" if object_type == CatalogObjectType.SCHEMA or "." not in parent else "tables")
        hydration = self.store.catalog_hydration_get(scope, parent)
        state = str((hydration or {}).get("state") or "NOT_LOADED")
        resolved = status or ("CACHED" if items else state)
        if status is None and state == "FAILED":
            resolved = "BROWSE_ONLY" if (hydration or {}).get("error_code") == "PERMISSION_DENIED" else "FAILED"
        if status == "READY" and not items:
            resolved = "EMPTY"
        if not items and status == "BROWSE_ONLY":
            resolved = "BROWSE_ONLY"
        return {"status": resolved, "items": items,
                "error": error or (hydration or {}).get("error_code") or None,
                "hydration": hydration or {"state": "NOT_LOADED", "scope": scope, "parent_name": parent},
                "has_more": has_more,
                "next_offset": offset + len(items) if has_more else None}

    @staticmethod
    def _properties(row: dict[str, Any]) -> dict[str, Any]:
        allowed = ("table_type", "data_source_format", "owner", "created_at")
        result = {key: row[key] for key in allowed if isinstance(row.get(key), (str, int, float, bool))}
        tags = row.get("tags")
        if isinstance(tags, dict):
            safe_tags = {str(key)[:128]: str(value)[:512] for key, value in tags.items()
                         if not re.search(r"password|secret|token|credential|api.?key", str(key), re.I)}
            if safe_tags:
                result["tags"] = safe_tags
        elif isinstance(tags, list):
            safe_tags = [tag for tag in tags[:100] if isinstance(tag, dict)
                         and not re.search(r"password|secret|token|credential|api.?key", str(tag.get("name", "")), re.I)]
            if safe_tags:
                result["tags"] = safe_tags
        constraints = row.get("constraints")
        if isinstance(constraints, list):
            result["constraints"] = [item for item in constraints[:100] if isinstance(item, dict)]
        return result

    @classmethod
    def _table_object(cls, row: dict[str, Any], catalog_name: str = "",
                      schema_name: str = "", *, full_name_override: str | None = None) -> CatalogObject:
        full_name = full_name_override or str(row.get("full_name") or "")
        if not full_name:
            name = str(row.get("name") or row.get("table_name") or "")
            full_name = ".".join(part for part in (catalog_name, schema_name, name) if part)
        if len(full_name.split(".")) != 3:
            raise ProviderError("Databricks returned a table without a fully qualified name", retryable=False)
        table_type = str(row.get("table_type") or "TABLE").upper()
        object_type = CatalogObjectType.VIEW if table_type in {"VIEW", "MATERIALIZED_VIEW", "STREAMING_TABLE"} else CatalogObjectType.TABLE
        columns = row.get("columns") if isinstance(row.get("columns"), list) else []
        parent = ".".join(full_name.split(".")[:2])
        return CatalogObject(full_name, object_type,
            workspace_id=str(row.get("workspace_id") or ""), parent_name=parent,
            comment=str(row.get("comment") or ""), properties=cls._properties(row),
            columns=tuple({key: column[key] for key in ("name", "type_text", "type_name",
                              "nullable", "comment", "position") if key in column}
                          for column in columns if isinstance(column, dict)),
            updated_at=str(row.get("updated_at") or ""))

    @staticmethod
    def _validate_component(value: str, kind: str) -> None:
        if not value or len(value) > 255 or any(ord(char) < 32 or char in "/\\?" for char in value):
            raise ValidationError(f"A valid {kind} name is required")

    @staticmethod
    def _validate_full_name(value: str) -> None:
        if not value or len(value) > 1024 or any(ord(char) < 32 or char in "/\\?" for char in value):
            raise ValidationError("A valid fully qualified table name is required")
