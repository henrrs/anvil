from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from scripts.analytics.errors import ValidationError
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.service import AnalyticsService
from scripts.analytics.store import ContextStore
from scripts.analytics import tool_cli


class ToolHTTPHandler(BaseHTTPRequestHandler):
    received: list[tuple[str, str, dict | None]] = []

    def log_message(self, *_args):
        pass

    def _reply(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size)) if size else None
        ToolHTTPHandler.received.append((self.command, self.path, body))
        raw = json.dumps({"status": "READY", "ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _reply
    do_POST = _reply


class AnalyticsToolBridgeTests(unittest.TestCase):
    def test_tool_dispatch_covers_all_registered_actions(self):
        cases = {
            "search_catalog": {"query": "invoice"},
            "describe_table": {"full_name": "main.finance.invoices"},
            "preview_table": {"full_name": "main.finance.invoices", "warehouse_id": "wh-1"},
            "run_query": {"sql": "SELECT id FROM main.finance.invoices"},
            "explain_query": {"sql": "SELECT id FROM main.finance.invoices"},
            "get_local_coverage": {"full_name": "main.finance.invoices"},
            "materialize": {"source_name": "main.finance.invoices", "columns": ["id"],
                            "warehouse_id": "wh-1"},
            "refresh_metadata": {},
            "refresh_local": {"operation_id": "op/1"},
            "profile_table": {"full_name": "main.finance.invoices", "warehouse_id": "wh-1"},
            "get_lineage": {"full_name": "main.finance.invoices", "warehouse_id": "wh-1"},
            "get_query_history": {},
            "compare_remote_local": {"sql": "SELECT id FROM main.finance.invoices", "warehouse_id": "wh-1"},
        }
        for action, payload in cases.items():
            with self.subTest(action=action):
                path, body = tool_cli._dispatch(action, payload)
                self.assertTrue(path.startswith("/api/"))
                if action in {"run_query", "materialize", "refresh_metadata", "refresh_local"}:
                    self.assertIsInstance(body, dict)

    def test_dispatch_bounds_user_inputs_and_requires_full_table_confirmation_only_explicitly(self):
        with self.assertRaises(ValueError):
            tool_cli._dispatch("preview_table", {"full_name": "c.s.t", "warehouse_id": "wh", "limit": 101})
        with self.assertRaises(ValueError):
            tool_cli._dispatch("search_catalog", {"query": "x" * 257})
        _, body = tool_cli._dispatch("materialize", {
            "source_name": "c.s.t", "columns": ["id"], "warehouse_id": "wh"})
        self.assertFalse(body["full_table_confirmed"])

    def test_cli_forwards_only_to_loopback_bff_and_returns_bounded_json(self):
        ToolHTTPHandler.received = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), ToolHTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            old_env = os.environ.get("ANVIL_ANALYTICS_PORT")
            os.environ["ANVIL_ANALYTICS_PORT"] = str(server.server_port)
            stdin, stdout, stderr = io.BytesIO(b'{"query":"sales","parent":"main"}'), io.BytesIO(), io.StringIO()
            try:
                with patch("sys.stdin", type("Input", (), {"buffer": stdin})()), \
                     patch("sys.stdout", type("Output", (), {"buffer": stdout})()), \
                     redirect_stderr(stderr):
                    code = tool_cli.main(["--tool", "search_catalog"])
            finally:
                if old_env is None:
                    os.environ.pop("ANVIL_ANALYTICS_PORT", None)
                else:
                    os.environ["ANVIL_ANALYTICS_PORT"] = old_env
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue()), {"status": "READY", "ok": True})
            method, path, body = ToolHTTPHandler.received[0]
            self.assertEqual(method, "GET")
            self.assertIn("/api/catalog/search?", path)
            self.assertIn("q=sales", path)
            self.assertIsNone(body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_cli_does_not_contact_service_for_invalid_or_oversized_input(self):
        for raw, action in ((b"{}", "unknown"), (b"x" * (tool_cli.MAX_INPUT + 1), "search_catalog")):
            stdin = io.BytesIO(raw)
            stderr = io.StringIO()
            with patch("sys.stdin", type("Input", (), {"buffer": stdin})()), redirect_stderr(stderr):
                code = tool_cli.main(["--tool", action])
            self.assertEqual(code, 1)
            self.assertIn("Analytics tool unavailable", stderr.getvalue())

    def test_plugin_registers_all_shared_bff_tools_without_direct_runtime_or_credentials(self):
        plugin = Path(__file__).resolve().parents[2] / "config/plugins/anvil-core/index.ts"
        source = plugin.read_text(encoding="utf-8")
        for action in ("search_catalog", "describe_table", "preview_table", "run_query",
                       "explain_query", "get_local_coverage", "materialize", "refresh_metadata",
                       "refresh_local", "profile_table", "get_lineage", "get_query_history",
                       "compare_remote_local"):
            self.assertIn(f'action: "{action}"', source)
        self.assertIn('new URL("../../scripts/analytics/tool_cli.py"', source)
        self.assertIn("child.stdin.end(JSON.stringify(input))", source)
        self.assertNotIn("OPENCODE_SERVER_PASSWORD", source)
        self.assertNotIn("access_token", source)

        v1_plugin = Path(__file__).resolve().parents[2] / "config/plugins-v1/anvil-core.ts"
        v1_source = v1_plugin.read_text(encoding="utf-8")
        self.assertIn('from "@opencode-ai/plugin"', v1_source)
        self.assertIn("export const AnvilCorePlugin", v1_source)
        self.assertIn("tool: {", v1_source)
        self.assertIn("anvil_memory_search", v1_source)
        for action in ("search_catalog", "describe_table", "preview_table", "run_query",
                       "explain_query", "get_local_coverage", "materialize", "refresh_metadata",
                       "refresh_local", "profile_table", "get_lineage", "get_query_history",
                       "compare_remote_local"):
            self.assertIn(f'action: "{action}"', v1_source)


class AnalyticsServiceExtendedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AnalyticsPaths.from_root(Path(self.temp.name) / ".anvil", create=True)
        self.store = ContextStore(paths=self.paths)
        self.service = AnalyticsService(paths=self.paths, store=self.store, web_root=Path(self.temp.name))
        self.addCleanup(self.service.close)

    def test_profile_is_bounded_and_never_returns_raw_sample_rows(self):
        self.service.preview = lambda *_args, **_kwargs: {
            "status": "READY", "columns": ["amount", "state"],
            "rows": [[None, "new"], [3, "paid"], [5, "paid"]], "truncated": True,
        }
        result = self.service.profile_table("main.sales.orders", "wh", limit=1000)
        self.assertEqual(result["sample_rows"], 3)
        self.assertTrue(result["sample_truncated"])
        self.assertEqual(result["columns"][0]["null_count"], 1)
        self.assertEqual(result["columns"][0]["min"], 3)
        self.assertEqual(result["columns"][0]["max"], 5)
        self.assertNotIn("rows", result)
        self.assertNotIn("preview", result)

    def test_lineage_escapes_literals_and_caps_rows_on_shared_query_router(self):
        calls = []
        self.service.run_query = lambda sql, **kwargs: calls.append((sql, kwargs)) or {"rows": []}
        result = self.service.get_lineage("main.sales.customer's", "wh", limit=10_000)
        sql, options = calls[0]
        self.assertIn("customer''s", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertIn("system.access.table_lineage", sql)
        self.assertEqual(options["route"], "DATABRICKS")
        self.assertEqual(result["status"], "READY")
        with self.assertRaises(ValidationError):
            self.service.get_lineage("main.sales.orders", "")

    def test_compare_requires_complete_matching_result_sets(self):
        results = iter([
            {"columns": ["id"], "rows": [[1], [1], [2]], "truncated": False},
            {"columns": ["ID"], "rows": [[1], [2], [2]], "truncated": False},
            {"columns": ["id"], "rows": [[1]], "truncated": True},
            {"columns": ["id"], "rows": [[1]], "truncated": False},
        ])
        self.service.run_query = lambda *_args, **_kwargs: next(results)
        comparable = self.service.compare_remote_local("SELECT id FROM c.s.t", "wh")
        self.assertFalse(comparable["equivalent"])
        self.assertEqual(comparable["different_rows"], 2)
        inconclusive = self.service.compare_remote_local("SELECT id FROM c.s.t", "wh")
        self.assertIsNone(inconclusive["equivalent"])
        self.assertEqual(inconclusive["status"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
