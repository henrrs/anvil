"""Small same-origin API router for the local Analytics BFF."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from .errors import NotFoundError, ValidationError
from .service import AnalyticsService


class AnalyticsAPI:
    def __init__(self, service: AnalyticsService) -> None:
        self.service = service

    def handle(self, method: str, path: str, query: dict[str, list[str]],
               body: dict[str, Any] | None = None) -> tuple[int, Any]:
        body = body or {}
        if method == "GET" and path == "/api/health":
            return 200, {"status": "OK", "service": "anvil-analytics"}
        if method == "GET" and path == "/api/me":
            return 200, self.service.me()
        if method == "GET" and path == "/api/runtime":
            return 200, self.service.runtime_status()
        if method == "GET" and path == "/api/warehouses":
            return 200, self.service.warehouses()
        if method == "POST" and path == "/api/warehouses/refresh":
            return 200, self.service.warehouses(refresh=True)
        if method == "GET" and path.startswith("/api/warehouses/"):
            warehouse_id = unquote(path.removeprefix("/api/warehouses/"))
            if "/" in warehouse_id or "\\" in warehouse_id:
                raise ValidationError("SQL warehouse path is invalid")
            return 200, self.service.get_warehouse(warehouse_id)
        if method == "GET" and path == "/api/catalog":
            return 200, self.service.catalogs(
                limit=self._int_query(query, "limit", 100, 1, 200),
                offset=self._int_query(query, "offset", 0, 0, 10_000_000))
        if method == "GET" and path == "/api/catalog/search":
            return 200, self.service.search_catalog(self._one(query, "q"),
                parent=self._one(query, "parent", default=""),
                limit=self._int_query(query, "limit", 100, 1, 200))
        if method == "GET" and path.startswith("/api/catalog/"):
            parts = [unquote(part) for part in path.removeprefix("/api/catalog/").split("/")]
            if len(parts) == 2 and parts[1] == "schemas":
                return 200, self.service.schemas(parts[0],
                    limit=self._int_query(query, "limit", 100, 1, 200),
                    offset=self._int_query(query, "offset", 0, 0, 10_000_000))
            if len(parts) == 3 and parts[2] == "tables":
                return 200, self.service.tables(parts[0], parts[1],
                    limit=self._int_query(query, "limit", 100, 1, 200),
                    offset=self._int_query(query, "offset", 0, 0, 10_000_000))
        if method == "POST" and path == "/api/catalog/refresh":
            return 200, self.service.refresh_catalog(scope=str(body.get("scope") or ""),
                catalog_name=str(body.get("catalog_name") or ""),
                schema_name=str(body.get("schema_name") or ""),
                limit=self._int_body(body, "limit", 100, 1, 200),
                offset=self._int_body(body, "offset", 0, 0, 10_000_000))
        if method == "GET" and path.startswith("/api/tables/"):
            suffix = path.removeprefix("/api/tables/")
            if suffix.endswith("/preview"):
                full_name = unquote(suffix.removesuffix("/preview"))
                warehouse_id = self._one(query, "warehouse_id")
                return 200, self.service.preview(full_name, warehouse_id,
                    limit=self._int_query(query, "limit", 10, 1, 100),
                    profile=self._one(query, "profile", default="") or None)
            if suffix.endswith("/coverage"):
                full_name = unquote(suffix.removesuffix("/coverage"))
                return 200, self.service.local_coverage(full_name,
                    sql=self._one(query, "sql", default=""))
            if suffix.endswith("/profile"):
                full_name = unquote(suffix.removesuffix("/profile"))
                return 200, self.service.profile_table(full_name, self._one(query, "warehouse_id"),
                    limit=self._int_query(query, "limit", 100, 1, 100))
            if suffix.endswith("/lineage"):
                full_name = unquote(suffix.removesuffix("/lineage"))
                return 200, self.service.get_lineage(full_name, self._one(query, "warehouse_id"),
                    limit=self._int_query(query, "limit", 100, 1, 100))
            full_name = unquote(suffix)
            if "/" in full_name or "\\" in full_name:
                raise ValidationError("Table path is invalid")
            result = self.service.table(full_name, refresh=self._bool_query(query, "refresh"))
            result["coverage"] = self.service.local_coverage(full_name)
            return 200, result
        if method == "POST" and path == "/api/query":
            return 200, self.service.run_query(
                str(body.get("sql") or ""), route=str(body.get("route") or "AUTO"),
                warehouse_id=str(body.get("warehouse_id") or ""),
                profile=(str(body.get("profile")) if body.get("profile") else None),
                timeout=self._int_body(body, "timeout", 120, 5, 600))
        if method == "POST" and path == "/api/query/explain":
            return 200, self.service.query_explain(str(body.get("sql") or ""))
        if method == "POST" and path == "/api/query/compare":
            return 200, self.service.compare_remote_local(
                str(body.get("sql") or ""), str(body.get("warehouse_id") or ""),
                profile=(str(body.get("profile")) if body.get("profile") else None))
        if method == "GET" and path == "/api/query/history":
            return 200, {"items": self.service.query_history(
                limit=self._int_query(query, "limit", 50, 1, 100))}
        if method == "GET" and path == "/api/materializations":
            return 200, {"items": self.service.materializations_recent(
                limit=self._int_query(query, "limit", 50, 1, 100))}
        if method == "GET" and path == "/api/datasets":
            return 200, {"items": self.service.local_datasets(
                limit=self._int_query(query, "limit", 100, 1, 500))}
        if method == "DELETE" and path.startswith("/api/datasets/"):
            dataset_id = unquote(path.removeprefix("/api/datasets/"))
            if "/" in dataset_id or "\\" in dataset_id:
                raise ValidationError("Local dataset path is invalid")
            return 200, self.service.delete_local_dataset(dataset_id)
        if method == "GET" and path == "/api/operations":
            return 200, {"items": self.service.operations_recent(
                limit=self._int_query(query, "limit", 50, 1, 100))}
        if method == "GET" and path == "/api/investigations/recent":
            return 200, {"items": self.service.investigations_recent(
                limit=self._int_query(query, "limit", 20, 1, 100))}
        if method == "POST" and path == "/api/materializations":
            return 202, self.service.submit_materialization(body)
        if path.startswith("/api/materializations/"):
            suffix = path.removeprefix("/api/materializations/")
            if suffix.endswith("/cancel") and method == "POST":
                return 200, self.service.cancel_materialization(unquote(suffix.removesuffix("/cancel")))
            if suffix.endswith("/refresh") and method == "POST":
                return 202, self.service.resume_materialization(unquote(suffix.removesuffix("/refresh")))
            if method == "GET" and "/" not in suffix:
                return 200, self.service.materialization(unquote(suffix))
        if method == "POST" and path == "/api/anvil/chat":
            raise ValidationError("Ask Anvil uses the streaming endpoint")
        raise NotFoundError("Analytics API route was not found")

    @staticmethod
    def _one(query: dict[str, list[str]], key: str, *, default: str | None = None) -> str:
        values = query.get(key)
        if not values:
            if default is not None:
                return default
            raise ValidationError(f"Missing required query parameter: {key}")
        value = values[0]
        if len(value) > 8192:
            raise ValidationError(f"Query parameter {key} exceeds its size limit")
        return value

    @classmethod
    def _int_query(cls, query: dict[str, list[str]], key: str, default: int,
                   minimum: int, maximum: int) -> int:
        raw = cls._one(query, key, default=str(default))
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValidationError(f"Query parameter {key} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise ValidationError(f"Query parameter {key} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _bool_query(query: dict[str, list[str]], key: str) -> bool:
        value = query.get(key, ["false"])[0].casefold()
        if value not in {"true", "false", "1", "0"}:
            raise ValidationError(f"Query parameter {key} must be true or false")
        return value in {"true", "1"}

    @staticmethod
    def _int_body(body: dict[str, Any], key: str, default: int,
                  minimum: int, maximum: int) -> int:
        value = body.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValidationError(f"Request field {key} must be between {minimum} and {maximum}")
        return value
