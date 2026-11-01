"""Read-only query routing between exact local coverage and Databricks."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from .coverage import CoverageRegistry
from .errors import CoverageError, UnavailableError, ValidationError
from .models import QueryRecord, QueryRoute
from .planner import (QueryPlan, ensure_read_only, parse_local_query,
                      rewrite_expression_identifiers)
from .store import ContextStore

MAX_QUERY_ROWS = 100
MAX_QUERY_BYTES = 1_000_000


class RemoteQueryPort(Protocol):
    def execute_sql(self, statement: str, warehouse_id: str, *,
                    profile: str | None = None, timeout: int = 120) -> dict[str, Any]: ...


class DuckDBLocalEngine:
    def __init__(self) -> None:
        self._duckdb: Any = None
        self.failure_code = "LOCAL_ENGINE_MISSING"
        try:
            import duckdb
            self._duckdb = duckdb
            self.failure_code = ""
        except ImportError:
            pass

    @property
    def available(self) -> bool:
        return self._duckdb is not None

    def query(self, plan: QueryPlan, snapshot: dict[str, Any], *,
              max_rows: int = MAX_QUERY_ROWS, max_bytes: int = MAX_QUERY_BYTES) -> dict[str, Any]:
        if self._duckdb is None:
            raise UnavailableError("DuckDB is not installed; local SQL is unavailable",
                                   code=self.failure_code, retryable=False)
        files = [str(path) for path in snapshot["files"]]
        if not files:
            raise CoverageError("The current local snapshot has no readable Parquet files")
        connection = self._duckdb.connect(database=":memory:")
        try:
            connection.read_parquet(files).create_view("_anvil_coverage_snapshot", replace=True)
            selected = "*" if plan.projection == ("*",) else ", ".join(
                self._quote_identifier(column) for column in plan.projection)
            statement = f"SELECT {selected} FROM \"_anvil_coverage_snapshot\""
            if plan.predicate:
                statement += " WHERE " + rewrite_expression_identifiers(plan.predicate)
            requested_limit = min(plan.limit, max_rows + 1) if plan.limit is not None else max_rows + 1
            statement += f" LIMIT {requested_limit}"
            cursor = connection.execute(statement)
            columns = [str(item[0]) for item in (cursor.description or [])]
            raw_rows = cursor.fetchmany(max_rows + 1)
            truncated = len(raw_rows) > max_rows
            rows: list[list[Any]] = []
            size = 0
            for raw in raw_rows[:max_rows]:
                row = [self._value(value) for value in raw]
                row_size = len(json.dumps(row, ensure_ascii=False, default=str).encode("utf-8"))
                if size + row_size > max_bytes:
                    truncated = True
                    break
                rows.append(row)
                size += row_size
            return {"columns": columns, "rows": rows, "truncated": truncated,
                    "row_count": len(rows), "byte_count": size}
        except CoverageError:
            raise
        except Exception as exc:
            raise UnavailableError("DuckDB could not execute the covered local query",
                                   code="LOCAL_QUERY_FAILED", retryable=False) from exc
        finally:
            connection.close()

    @staticmethod
    def _quote_identifier(value: str) -> str:
        if not value or any(ord(char) < 32 for char in value):
            raise CoverageError("The local query contains an invalid column identifier")
        return '"' + value.replace('"', '""') + '"'

    @staticmethod
    def _value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return str(value)


class QueryRouter:
    def __init__(self, store: ContextStore, coverage: CoverageRegistry,
                 remote: RemoteQueryPort | None, *, local: DuckDBLocalEngine | None = None) -> None:
        self.store = store
        self.coverage = coverage
        self.remote = remote
        self.local = local or DuckDBLocalEngine()

    def execute(self, sql: str, *, route: QueryRoute | str = QueryRoute.AUTO,
                warehouse_id: str | None = None, profile: str | None = None,
                timeout: int = 120) -> dict[str, Any]:
        try:
            route_value = route.value if isinstance(route, QueryRoute) else str(route).upper()
            selected_route = QueryRoute(route_value)
        except ValueError as exc:
            raise ValidationError("Query route must be AUTO, LOCAL or DATABRICKS") from exc
        normalized_sql = ensure_read_only(sql)
        plan = parse_local_query(normalized_sql)
        decision = (self.coverage.covers(plan) if plan else
                    CoverageDecisionFallback(False, "This SQL shape is not supported by the local coverage checker."))
        if selected_route == QueryRoute.LOCAL:
            if not plan or not decision.covered:
                raise CoverageError(decision.reason, code="LOCAL_COVERAGE_MISMATCH")
            if not self.local.available:
                raise UnavailableError("DuckDB is not installed; local SQL is unavailable",
                                       code="LOCAL_ENGINE_MISSING", retryable=False)
            actual_route = QueryRoute.LOCAL
        elif selected_route == QueryRoute.DATABRICKS:
            actual_route = QueryRoute.DATABRICKS
        elif plan and decision.covered and self.local.available:
            actual_route = QueryRoute.LOCAL
        else:
            actual_route = QueryRoute.DATABRICKS

        started = time.monotonic()
        status = "FAILED"
        error_code = ""
        result: dict[str, Any]
        try:
            if actual_route == QueryRoute.LOCAL:
                assert plan is not None
                snapshot = self.coverage.snapshot_for(plan.source_name)
                if snapshot is None:
                    raise CoverageError("The current local snapshot is unavailable")
                result = self.local.query(plan, snapshot)
            else:
                if not self.remote:
                    raise UnavailableError("Databricks SQL is not configured", code="PROVIDER_NOT_CONFIGURED")
                if not warehouse_id:
                    raise UnavailableError("Choose a running SQL warehouse to execute this query",
                                           code="WAREHOUSE_REQUIRED", retryable=False)
                result = self.remote.execute_sql(normalized_sql, warehouse_id, profile=profile, timeout=timeout)
                if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
                    raise UnavailableError("Databricks returned an invalid SQL result", code="SQL_RESULT_INVALID")
                result = _bound_remote_result(result)
            status = "SUCCEEDED"
            return {**result, "route": actual_route.value,
                    "coverage": {"covered": decision.covered, "reason": decision.reason,
                                 "snapshot_id": decision.snapshot_id}}
        except Exception as exc:
            error_code = str(getattr(exc, "code", "QUERY_FAILED"))
            raise
        finally:
            latency = int((time.monotonic() - started) * 1000)
            fingerprint = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
            row_count = len(result.get("rows", [])) if status == "SUCCEEDED" and "result" in locals() else None
            byte_count = result.get("byte_count") if status == "SUCCEEDED" and "result" in locals() else None
            self.store.query_record(QueryRecord(
                normalized_sql, fingerprint, actual_route, status, latency,
                row_count=row_count, byte_count=byte_count, error_code=error_code,
                source_objects=(plan.source_name,) if plan else ()))


@dataclass(frozen=True)
class CoverageDecisionFallback:
    covered: bool
    reason: str
    snapshot_id: str = ""


def _bound_remote_result(result: dict[str, Any]) -> dict[str, Any]:
    columns = result.get("columns", [])
    if not isinstance(columns, list) or any(not isinstance(value, str) for value in columns):
        raise UnavailableError("Databricks returned an invalid SQL schema", code="SQL_RESULT_INVALID")
    source_rows = result["rows"]
    rows: list[list[Any]] = []
    byte_count = 0
    truncated = bool(result.get("truncated")) or len(source_rows) > MAX_QUERY_ROWS
    for row in source_rows[:MAX_QUERY_ROWS]:
        if not isinstance(row, (list, tuple)):
            raise UnavailableError("Databricks returned an invalid SQL row", code="SQL_RESULT_INVALID")
        encoded = json.dumps(row, ensure_ascii=False, default=str).encode("utf-8")
        if byte_count + len(encoded) > MAX_QUERY_BYTES:
            truncated = True
            break
        rows.append(list(row))
        byte_count += len(encoded)
    return {"columns": columns, "rows": rows, "row_count": len(rows),
            "byte_count": byte_count, "truncated": truncated}
