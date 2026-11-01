"""Bounded local Analytics API client for Anvil's registered tools."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

MAX_INPUT = 1_048_576
MAX_OUTPUT = 1_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _string(value: object, field: str, *, required: bool = True, limit: int = 8192) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise ValueError(f"{field} must be non-empty text under {limit} characters")
    return value


def _query_path(path: str, **values: object) -> str:
    return path + "?" + urllib.parse.urlencode({key: value for key, value in values.items() if value is not None})


def _dispatch(tool: str, payload: dict) -> tuple[str, dict | None]:
    if tool == "search_catalog":
        term = _string(payload.get("query"), "query", limit=256)
        return _query_path("/api/catalog/search", q=term, parent=payload.get("parent", "")), None
    if tool == "get_query_history":
        limit = int(payload.get("limit", 20))
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return _query_path("/api/query/history", limit=limit), None
    if tool == "refresh_metadata":
        scope = payload.get("scope", "catalogs")
        if scope not in {"catalogs", "schemas", "tables"}:
            raise ValueError("scope must be catalogs, schemas or tables")
        return "/api/catalog/refresh", {
            "scope": scope,
            "catalog_name": _string(payload.get("catalog_name", ""), "catalog_name", required=False, limit=255),
            "schema_name": _string(payload.get("schema_name", ""), "schema_name", required=False, limit=255),
        }
    if tool == "refresh_local":
        operation = _string(payload.get("operation_id"), "operation_id", limit=128)
        escaped_operation = urllib.parse.quote(operation, safe="")
        return f"/api/materializations/{escaped_operation}/refresh", {}
    if tool == "run_query":
        body = {"sql": _string(payload.get("sql"), "sql", limit=64_000),
                "route": payload.get("route", "AUTO"),
                "warehouse_id": payload.get("warehouse_id", "")}
        return "/api/query", body
    if tool == "explain_query":
        return "/api/query/explain", {"sql": _string(payload.get("sql"), "sql", limit=64_000)}
    if tool == "compare_remote_local":
        return "/api/query/compare", {
            "sql": _string(payload.get("sql"), "sql", limit=64_000),
            "warehouse_id": _string(payload.get("warehouse_id"), "warehouse_id", limit=256),
        }
    table_field = "source_name" if tool == "materialize" else "full_name"
    table = _string(payload.get(table_field), table_field, limit=1024)
    escaped = urllib.parse.quote(table, safe="")
    if tool == "describe_table":
        return "/api/tables/" + escaped, None
    if tool == "preview_table":
        warehouse = _string(payload.get("warehouse_id"), "warehouse_id", limit=256)
        limit = int(payload.get("limit", 20))
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return _query_path(f"/api/tables/{escaped}/preview", warehouse_id=warehouse, limit=limit), None
    if tool == "profile_table":
        warehouse = _string(payload.get("warehouse_id"), "warehouse_id", limit=256)
        limit = int(payload.get("limit", 100))
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return _query_path(f"/api/tables/{escaped}/profile", warehouse_id=warehouse, limit=limit), None
    if tool == "get_lineage":
        warehouse = _string(payload.get("warehouse_id"), "warehouse_id", limit=256)
        limit = int(payload.get("limit", 100))
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return _query_path(f"/api/tables/{escaped}/lineage", warehouse_id=warehouse, limit=limit), None
    if tool == "get_local_coverage":
        return _query_path(f"/api/tables/{escaped}/coverage", sql=payload.get("sql", "")), None
    if tool == "materialize":
        columns = payload.get("columns")
        if not isinstance(columns, list) or not 1 <= len(columns) <= 100 or any(not isinstance(item, str) for item in columns):
            raise ValueError("columns must be a list of 1 to 100 names")
        return "/api/materializations", {
            "source_name": table, "columns": columns,
            "predicate": _string(payload.get("predicate", ""), "predicate", required=False, limit=16_000),
            "warehouse_id": _string(payload.get("warehouse_id"), "warehouse_id", limit=256),
            "max_rows": int(payload.get("max_rows", 100_000)),
            "max_bytes": int(payload.get("max_bytes", 536_870_912)),
            "full_table_confirmed": payload.get("full_table_confirmed") is True,
            "force_refresh": payload.get("force_refresh") is True,
        }
    raise ValueError("Unknown Analytics tool")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("Analytics tool input exceeded 1 MiB")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Analytics tool input must be a JSON object")
        path, body = _dispatch(args.tool, value)
        port = int(os.environ.get("ANVIL_ANALYTICS_PORT", "8765"))
        if not 1 <= port <= 65535:
            raise ValueError("configured Analytics port is invalid")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if body is not None else None,
            headers={"Host": f"127.0.0.1:{port}", "Accept": "application/json",
                     **({"Content-Type": "application/json"} if body is not None else {})},
            method="POST" if body is not None else "GET",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=300) as response:
                result = response.read(MAX_OUTPUT + 1)
        except urllib.error.HTTPError as exc:
            result = exc.read(16_384)
            exc.close()
            try:
                detail = json.loads(result.decode("utf-8"))
                message = detail.get("error", {}).get("message", "Analytics request failed")
            except (UnicodeError, json.JSONDecodeError, AttributeError):
                message = "Analytics request failed"
            raise RuntimeError(str(message)[:1000]) from None
        if len(result) > MAX_OUTPUT:
            raise RuntimeError("Analytics returned more data than the tool output limit")
        sys.stdout.buffer.write(result + (b"\n" if not result.endswith(b"\n") else b""))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"Analytics tool unavailable: {str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
