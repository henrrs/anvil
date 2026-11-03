from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from scripts.analytics.errors import ValidationError
from scripts.analytics.server import make_server


class StubService:
    def __init__(self, web_root: Path) -> None:
        self.web_root = web_root
        self.calls: list[tuple[str, object]] = []

    def me(self):
        return {"name": "Test user", "profile": "", "workspace": "",
                "status": {"runtime": {"status": "READY", "generation": 2},
                           "local": {"duckdb": "DEGRADED", "storage_bytes": 32}}}

    def runtime_status(self):
        return {"status": "READY", "generation": 2}

    def warehouses(self, *, refresh=False):
        self.calls.append(("warehouses", refresh))
        return {"status": "READY", "warehouses": [{"warehouse_id": "wh-1", "name": "Analytics",
                "state": "RUNNING", "warehouse_type": "PRO"}], "refreshed_at": "now", "error": None}

    def get_warehouse(self, warehouse_id):
        return {"warehouse_id": warehouse_id, "name": "Analytics", "state": "RUNNING"}

    def operations_recent(self, *, limit=50):
        return [{"operation_id": "op-1", "kind": "MATERIALIZATION", "state": "RUNNING"}][:limit]

    def investigations_recent(self, *, limit=20):
        return [{"investigation_id": "inv-1", "title": "Refund trend", "state": "COMPLETED"}][:limit]

    def delete_local_dataset(self, dataset_id):
        self.calls.append(("delete_local_dataset", dataset_id))
        return {"dataset_id": dataset_id, "deleted": True}

    def cancel_materialization(self, operation_id):
        self.calls.append(("cancel_materialization", operation_id))
        return {"operation_id": operation_id, "state": "RUNNING", "phase": "CANCEL_REQUESTED"}

    def retry_materialization(self, operation_id):
        self.calls.append(("retry_materialization", operation_id))
        return {"operation_id": "fresh-operation", "source_name": "main.silver.orders", "state": "PLANNED"}

    def catalogs(self):
        return {"status": "CACHED", "items": []}

    def ask_anvil(self, prompt, *, context=None, deep_investigation=False,
                  event=None, timeout=300):
        self.calls.append((prompt, {"context": context, "deep": deep_investigation, "timeout": timeout}))
        if event:
            event("status", {"state": "thinking", "message": "Working"})
            event("result", {"text": "A safe test answer", "session": "canonical"})
            event("done", {"state": "completed"})
        return {"text": "A safe test answer"}


class AnalyticsHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.web_root = Path(self.temp.name)
        (self.web_root / "index.html").write_text("<main>Analytics test</main>", encoding="utf-8")
        (self.web_root / "app.js").write_text("console.log('local');", encoding="utf-8")
        (self.web_root / "api.js").write_text("window.HttpAnalyticsApi = class {};", encoding="utf-8")
        (self.web_root / "dev").mkdir()
        (self.web_root / "dev" / "mock-api.js").write_text("window.MockAnalyticsApi = class {};", encoding="utf-8")
        (self.web_root / "styles.css").write_text("body { color: white; }", encoding="utf-8")
        self.service = StubService(self.web_root)
        self.server = make_server(self.service, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method: str, path: str, *, body=None, headers=None, host=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        request_headers = dict(headers or {})
        if host:
            request_headers["Host"] = host
        payload = None if body is None else json.dumps(body).encode("utf-8")
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        result = response.read()
        status, response_headers = response.status, response.headers
        connection.close()
        return status, response_headers, result

    def test_serves_local_assets_with_security_headers(self) -> None:
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Analytics test", body)
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(headers.get("Cache-Control"), "no-cache")
        api_status, _, api_body = self.request("GET", "/api.js")
        self.assertEqual(api_status, 200)
        self.assertIn(b"HttpAnalyticsApi", api_body)
        self.assertNotEqual(self.request("GET", "/dev/mock-api.js")[0], 200)

    def test_api_is_same_origin_and_returns_json(self) -> None:
        status, headers, body = self.request("GET", "/api/me")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertEqual(json.loads(body)["name"], "Test user")
        self.assertEqual(self.request("GET", "/api/health")[0], 200)
        self.assertEqual(self.request("GET", "/api/not-a-route")[0], 404)
        method_status, method_headers, _ = self.request("PUT", "/api/me")
        self.assertEqual(method_status, 405)
        self.assertIn("POST", method_headers.get("Allow", ""))
        self.assertIn("DELETE", method_headers.get("Allow", ""))

    def test_delete_local_copy_and_no_body_materialization_actions(self) -> None:
        dataset_id = "a" * 64
        status, _, body = self.request("DELETE", f"/api/datasets/{dataset_id}")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["deleted"])
        self.assertIn(("delete_local_dataset", dataset_id), self.service.calls)
        status, _, body = self.request("POST", "/api/materializations/op-1/cancel")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["phase"], "CANCEL_REQUESTED")
        status, _, body = self.request("POST", "/api/materializations/op-1/retry")
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body)["operation_id"], "fresh-operation")
        self.assertIn(("retry_materialization", "op-1"), self.service.calls)

    def test_warehouse_discovery_and_recent_workspace_routes(self) -> None:
        status, _, body = self.request("GET", "/api/warehouses")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["warehouses"][0]["warehouse_id"], "wh-1")
        status, _, _ = self.request("POST", "/api/warehouses/refresh", body={})
        self.assertEqual(status, 200)
        self.assertIn(("warehouses", True), self.service.calls)
        self.assertEqual(self.request("GET", "/api/warehouses/wh-1")[0], 200)
        status, _, payload = self.request("GET", "/api/operations?limit=5")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["items"][0]["operation_id"], "op-1")
        status, _, payload = self.request("GET", "/api/investigations/recent?limit=5")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["items"][0]["investigation_id"], "inv-1")
        self.assertEqual(self.request("GET", "/api/operations?limit=0")[0], 400)

    def test_rejects_foreign_host_origin_and_path_traversal(self) -> None:
        self.assertEqual(self.request("GET", "/", host="evil.example")[0], 400)
        status, _, payload = self.request("GET", "/api/me", headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 400)
        self.assertIn(b"cross-origin", payload)
        self.assertNotEqual(self.request("GET", "/%2e%2e/secret")[0], 200)

    def test_chat_uses_validated_json_and_streams_server_sent_events(self) -> None:
        status, headers, body = self.request("POST", "/api/anvil/chat",
            body={"prompt": "Summarize this table", "context": {"table": "c.s.t"},
                  "deep_investigation": True, "timeout": 60})
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers.get("Content-Type", ""))
        self.assertIn(b"event: result", body)
        self.assertIn(b"A safe test answer", body)
        self.assertEqual(self.service.calls[0][0], "Summarize this table")

    def test_chat_rejects_invalid_shapes_and_non_json(self) -> None:
        status, _, payload = self.request("POST", "/api/anvil/chat", body={"prompt": 3})
        self.assertEqual(status, 400)
        self.assertIn(b"text prompt", payload)
        status, _, _ = self.request("POST", "/api/anvil/chat", body={"prompt": "hi"},
                                    headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 400)

    def test_binds_loopback_only(self) -> None:
        with self.assertRaises(ValidationError):
            make_server(self.service, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
