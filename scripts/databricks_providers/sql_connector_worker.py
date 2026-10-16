"""One-shot SQL Connector query worker; credentials stay in Unified Auth."""

from __future__ import annotations

import json
import sys
from urllib.parse import urlsplit


def main() -> int:
    try:
        request = json.load(sys.stdin)
        host = urlsplit(str(request["host"]))
        if host.scheme != "https" or not host.hostname or not request.get("http_path"):
            raise ValueError("invalid workspace or warehouse connection metadata")
        from databricks import sql
        connection = sql.connect(server_hostname=host.hostname, http_path=request["http_path"],
                                 auth_type="databricks-oauth", http_timeout=request.get("timeout", 120),
                                 use_cloud_fetch=False)
        try:
            cursor = connection.cursor()
            try:
                parameters = request.get("parameters") or []
                bound = {item["name"]: item.get("value") for item in parameters
                         if isinstance(item, dict) and item.get("name")}
                cursor.execute(request["statement"], bound if bound else None)
                columns = [item[0] for item in (cursor.description or [])]
                output = {"state": "SUCCEEDED", "columns": columns, "rows": [], "truncated": False, "row_count": 0}
                for _ in range(101):
                    row = cursor.fetchone()
                    if row is None:
                        break
                    if output["row_count"] >= 100:
                        output["truncated"] = True
                        break
                    candidate = output["rows"] + [row]
                    encoded = json.dumps({**output, "rows": candidate}, ensure_ascii=False, separators=(",", ":"))
                    if len(encoded.encode("utf-8")) > 1_000_000:
                        output["truncated"] = True
                        break
                    output["rows"].append(row)
                    output["row_count"] += 1
                encoded = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
                print(encoded)
                return 0
            finally:
                cursor.close()
        finally:
            connection.close()
    except Exception as exc:
        category = type(exc).__name__
        print(json.dumps({"error": category + ": SQL query failed; check permissions, authentication, and network access"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
