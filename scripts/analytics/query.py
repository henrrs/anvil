"""Read-only query routing between exact local coverage and Databricks."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
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
_LOG = logging.getLogger(__name__)


def _query_event(event: str, **details: Any) -> None:
    _LOG.info(json.dumps({"event": event, **details}, sort_keys=True,
                         separators=(",", ":"), default=str))


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
            self.validate_snapshot_schema(connection, snapshot)
            start, end = plan.source_span
            if not (0 <= start < end <= len(plan.sql)):
                raise CoverageError("The local query source could not be resolved safely")
            statement = (plan.sql[:start] + '"_anvil_coverage_snapshot"' + plan.sql[end:])
            statement = rewrite_expression_identifiers(statement)
            # Bound the returned rows without changing aggregate, grouping,
            # ordering, DISTINCT or caller LIMIT semantics inside the query.
            statement = f"SELECT * FROM ({statement}) AS _anvil_bounded_result LIMIT {max_rows + 1}"
            cursor = connection.execute(statement)
            arrow_result = cursor.to_arrow_table()
            columns = list(arrow_result.column_names)
            raw_rows = list(zip(*(column.to_pylist() for column in arrow_result.columns)))
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

    def inspect_snapshot_schema(self, snapshot: dict[str, Any]) -> None:
        """Resolve the CURRENT files through DuckDB without executing user SQL."""
        if self._duckdb is None:
            raise UnavailableError("DuckDB is not installed; local schema cannot be verified",
                                   code=self.failure_code, retryable=False)
        files = [str(path) for path in snapshot.get("files", [])]
        if not files:
            raise CoverageError("The current local snapshot has no readable Parquet files",
                                code="LOCAL_SCHEMA_MISMATCH")
        try:
            connection = self._duckdb.connect(database=":memory:")
            try:
                connection.read_parquet(files).create_view("_anvil_coverage_snapshot", replace=True)
                self.validate_snapshot_schema(connection, snapshot)
            finally:
                connection.close()
        except CoverageError:
            raise
        except Exception as exc:
            raise CoverageError("DuckDB could not validate the CURRENT local schema",
                                code="LOCAL_SCHEMA_MISMATCH") from exc

    @staticmethod
    def validate_snapshot_schema(connection: Any, snapshot: dict[str, Any], *,
                                 physical_columns: list[Any] | None = None) -> None:
        """Compare manifest, independently parsed Parquet schema and DuckDB relation."""
        manifest = snapshot.get("manifest") if isinstance(snapshot, dict) else None
        if not isinstance(manifest, dict):
            return
        declared = manifest.get("columns")
        if not isinstance(declared, list) or any(not isinstance(item, str) for item in declared):
            raise CoverageError("Local snapshot coverage metadata has no valid column inventory",
                                code="LOCAL_SCHEMA_MISMATCH")
        if physical_columns is None:
            try:
                import pyarrow.parquet as parquet
                files = snapshot.get("files") if isinstance(snapshot.get("files"), (list, tuple)) else []
                if not files:
                    raise ValueError("Parquet file list is empty")
                schemas = [[(field.name, str(field.type)) for field in
                            parquet.ParquetFile(str(path)).schema_arrow] for path in files]
                if any([item[0] for item in schema] != [item[0] for item in schemas[0]] or
                       [_local_type(item[1]) for item in schema] !=
                       [_local_type(item[1]) for item in schemas[0]] for schema in schemas[1:]):
                    raise CoverageError("CURRENT Parquet files have inconsistent physical schemas",
                                        code="LOCAL_SCHEMA_MISMATCH")
                physical_columns = list(schemas[0])
            except CoverageError:
                raise
            except Exception as exc:
                raise CoverageError("The physical Parquet schema could not be verified independently",
                                    code="LOCAL_SCHEMA_UNVERIFIED") from exc
        try:
            description = connection.execute(
                'DESCRIBE SELECT * FROM "_anvil_coverage_snapshot"').fetchall()
        except Exception as exc:
            raise CoverageError("DuckDB could not resolve the current Parquet schema",
                                code="LOCAL_SCHEMA_MISMATCH") from exc
        visible = [(str(row[0]), str(row[1]) if len(row) > 1 else "")
                   for row in description if isinstance(row, (list, tuple)) and row]
        physical_schema = [((str(item[0]), str(item[1])) if isinstance(item, (tuple, list)) and len(item) > 1
                            else (str(item), "")) for item in physical_columns]
        declared_names = [name.casefold() for name in declared]
        physical_names = [name.casefold() for name, _type in physical_schema]
        visible_names = [name.casefold() for name, _type in visible]
        type_mismatch = any(_local_type(physical_type) != _local_type(duck_type)
                            for (_physical_name, physical_type), (_duck_name, duck_type)
                            in zip(physical_schema, visible)
                            if physical_type and duck_type)
        if (declared_names != physical_names or physical_names != visible_names or type_mismatch):
            _query_event("local_coverage_inconsistency_detected",
                         declared_columns=len(declared), physical_columns=len(physical_schema),
                         duckdb_columns=len(visible), type_mismatch=type_mismatch)
            raise CoverageError(
                "Local snapshot metadata, physical Parquet schema and DuckDB schema disagree; reconcile the local copy.",
                code="LOCAL_SCHEMA_MISMATCH")

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
        if isinstance(value, (bytes, bytearray, memoryview)):
            return base64.b64encode(bytes(value)).decode("ascii")
        if isinstance(value, dict):
            return {str(key): DuckDBLocalEngine._value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [DuckDBLocalEngine._value(item) for item in value]
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
                timeout: int = 120, workspace_identity: str | None = None,
                remote_schema: list[dict[str, Any]] | None = None,
                source_version: str | None = None) -> dict[str, Any]:
        try:
            route_value = route.value if isinstance(route, QueryRoute) else str(route).upper()
            selected_route = QueryRoute(route_value)
        except ValueError as exc:
            raise ValidationError("Query route must be AUTO, LOCAL or DATABRICKS") from exc
        normalized_sql = ensure_read_only(sql)
        plan = parse_local_query(normalized_sql)
        decision = CoverageDecisionFallback(False, "This SQL shape is not supported by the local coverage checker.")
        snapshot: dict[str, Any] | None = None
        actual_route = QueryRoute.DATABRICKS

        started = time.monotonic()
        status = "FAILED"
        error_code = ""
        result: dict[str, Any]
        try:
            if selected_route != QueryRoute.DATABRICKS and plan:
                with self.coverage.locked_snapshot(plan.source_name, workspace_identity) as locked_snapshot:
                    decision = self.coverage.covers(plan, workspace_identity=workspace_identity,
                                                    remote_schema=remote_schema,
                                                    source_version=source_version)
                    _query_event("local_coverage_evaluated", source_name=plan.source_name,
                                 workspace_identity=workspace_identity or "", covered=decision.covered,
                                 state=decision.state, reasons=decision.reasons)
                    wants_local = selected_route == QueryRoute.LOCAL or decision.covered
                    if selected_route == QueryRoute.LOCAL and not decision.covered:
                        raise CoverageError(decision.reason, code="LOCAL_COVERAGE_MISMATCH")
                    if wants_local and not self.local.available:
                        if selected_route == QueryRoute.LOCAL:
                            raise UnavailableError("DuckDB is not installed; local SQL is unavailable",
                                                   code="LOCAL_ENGINE_MISSING", retryable=False)
                    elif wants_local:
                        if locked_snapshot is None:
                            raise CoverageError("The current local snapshot is unavailable")
                        actual_route = QueryRoute.LOCAL
                        snapshot = locked_snapshot
                        try:
                            result = self.local.query(plan, snapshot)
                        except CoverageError as exc:
                            if exc.code == "LOCAL_SCHEMA_MISMATCH" and hasattr(self.coverage, "mark_invalid"):
                                self.coverage.mark_invalid(snapshot, str(exc))
                            raise
                    else:
                        actual_route = QueryRoute.DATABRICKS
            elif selected_route == QueryRoute.LOCAL:
                raise CoverageError(decision.reason, code="LOCAL_COVERAGE_MISMATCH")
            if actual_route == QueryRoute.DATABRICKS:
                if not self.remote:
                    raise UnavailableError(
                        "Remote execution is required for this query, but Databricks is unavailable.",
                        code="PROVIDER_NOT_CONFIGURED")
                if not warehouse_id:
                    raise UnavailableError("Remote execution is required; choose a running SQL warehouse.",
                                           code="WAREHOUSE_REQUIRED", retryable=False)
                result = self.remote.execute_sql(normalized_sql, warehouse_id, profile=profile, timeout=timeout)
                if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
                    raise UnavailableError("Databricks returned an invalid SQL result", code="SQL_RESULT_INVALID")
                result = _bound_remote_result(result)
            if selected_route == QueryRoute.AUTO:
                _query_event("auto_route_selected", route=actual_route.value,
                             source_name=plan.source_name if plan else "",
                             coverage_state=decision.state,
                             reason_code=(decision.reasons[0] if decision.reasons else ""))
            if actual_route == QueryRoute.LOCAL:
                _query_event("local_dataset_reused", source_name=plan.source_name if plan else "",
                             workspace_identity=workspace_identity or "",
                             snapshot_id=decision.snapshot_id)
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


def _local_type(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value).casefold())
    for prefix, canonical in (
        ("string", "string"), ("large_string", "string"), ("varchar", "string"),
        ("text", "string"), ("utf8", "string"), ("bool", "boolean"),
        ("boolean", "boolean"), ("int8", "tinyint"), ("int16", "smallint"),
        ("int32", "integer"), ("int64", "bigint"), ("uint8", "utinyint"),
        ("uint16", "usmallint"), ("uint32", "uinteger"), ("uint64", "ubigint"),
        ("tinyint", "tinyint"), ("smallint", "smallint"), ("integer", "integer"),
        ("int", "integer"), ("bigint", "bigint"), ("float32", "float"),
        ("float", "float"), ("float64", "double"), ("double", "double"),
        ("date32", "date"), ("date64", "date"), ("date", "date"),
    ):
        if normalized == prefix or normalized.startswith(prefix + "[") or normalized.startswith(prefix + "("):
            return canonical
    if normalized.startswith("timestamp"):
        return "timestamp"
    if normalized.startswith("decimal"):
        match = re.search(r"\((\d+)\s*,\s*(\d+)\)", normalized)
        return "decimal" + (match.group(0) if match else "")
    if normalized.startswith("list") or normalized.endswith("[]"):
        return "list"
    if normalized.startswith("struct"):
        return "struct"
    return normalized


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
