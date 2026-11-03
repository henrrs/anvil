from __future__ import annotations

import contextlib
import concurrent.futures
import io
import json
import sys
import threading
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from scripts.analytics.catalog import CatalogService
from scripts.analytics.databricks import SharedDatabricksCatalogClient, _shared_module
from scripts.analytics.errors import ProviderError, ValidationError
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.store import ContextStore
from scripts.databricks_providers import resolver, sdk_worker


class FakeCatalogProvider:
    def __init__(self):
        self.calls = []
        self.preview_calls = []
        self.repeat_token = False

    def page(self, operation, **parameters):
        self.calls.append((operation, dict(parameters)))
        token = parameters.get("page_token")
        if operation == "catalogs.list":
            if token:
                return {"catalogs": [{"name": "sandbox"}],
                        "next_page_token": "page-1" if self.repeat_token else None}
            return {"catalogs": [{"name": "main", "comment": "Primary catalog"}],
                    "next_page_token": "page-1"}
        if operation == "schemas.list":
            return {"schemas": [{"name": "silver", "comment": "Curated"}]}
        if operation == "tables.list":
            return {"tables": [{"name": "orders", "full_name": "main.silver.orders",
                                 "table_type": "MANAGED", "comment": "Order facts"}]}
        if operation == "tables.get":
            return {"full_name": "main.silver.orders", "table_type": "MANAGED",
                    "comment": "Order facts", "owner": "analytics",
                    "properties": {"api_secret": "must-not-be-cached"},
                    "columns": [{"name": "order_id", "type_text": "BIGINT", "nullable": False,
                                 "comment": "Stable order key", "position": 0,
                                 "default_expression": "must-not-be-cached"}]}
        raise AssertionError(operation)

    def preview_table(self, full_name, warehouse_id, *, limit=100, **_kwargs):
        self.preview_calls.append((full_name, warehouse_id, limit))
        return {"columns": ["order_id"], "rows": [[1]], "truncated": False}


class AnalyticsCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        paths = AnalyticsPaths.from_root(Path(self.temp.name) / ".anvil", create=True)
        self.store = ContextStore(paths=paths)
        self.provider = FakeCatalogProvider()
        self.catalog = CatalogService(self.store, self.provider)

    def test_catalog_hydration_is_scoped_lazy_paginated_and_cached(self):
        self.assertEqual(self.catalog.catalogs()["status"], "NOT_LOADED")
        self.assertEqual(self.provider.calls, [])

        refreshed = self.catalog.catalogs(refresh=True)
        self.assertEqual(refreshed["status"], "READY")
        self.assertEqual([item["full_name"] for item in refreshed["items"]], ["main", "sandbox"])
        self.assertEqual(len([c for c in self.provider.calls if c[0] == "catalogs.list"]), 2)
        self.catalog.catalogs()
        self.assertEqual(len(self.provider.calls), 2)

        schemas = self.catalog.schemas("main", refresh=True)
        self.assertEqual(schemas["items"][0]["full_name"], "main.silver")
        tables = self.catalog.tables("main", "silver", refresh=True)
        table = tables["items"][0]
        self.assertEqual(table["full_name"], "main.silver.orders")
        self.assertEqual(table["columns"], [])
        self.assertNotIn("tables.get", [call[0] for call in self.provider.calls])
        table_requests = [parameters for operation, parameters in self.provider.calls if operation == "tables.list"]
        self.assertTrue(table_requests and all(item["max_results"] <= 50 for item in table_requests))
        self.assertTrue(all(item["omit_columns"] and item["omit_properties"] for item in table_requests))

        described = self.catalog.describe("main.silver.orders")
        self.assertEqual(described["status"], "READY")
        self.assertEqual(described["object"]["columns"][0]["name"], "order_id")
        self.assertEqual(described["object"]["columns"][0]["comment"], "Stable order key")
        self.assertNotIn("api_secret", described["object"]["properties"])
        self.assertNotIn("default_expression", described["object"]["columns"][0])
        self.assertEqual([call[0] for call in self.provider.calls].count("tables.get"), 1)

    def test_failed_refresh_keeps_cached_metadata_and_reports_browse_only(self):
        self.catalog.catalogs(refresh=True)

        class BrokenProvider:
            def page(self, *_args, **_kwargs):
                raise ProviderError("offline", code="WORKSPACE_NETWORK_TIMEOUT")

        failed = CatalogService(self.store, BrokenProvider()).catalogs(refresh=True)
        self.assertEqual(failed["status"], "BROWSE_ONLY")
        self.assertEqual(len(failed["items"]), 2)
        self.assertEqual(failed["error"], "WORKSPACE_NETWORK_TIMEOUT")

    def test_repeated_page_token_fails_without_publishing_partial_cache(self):
        self.provider.repeat_token = True
        result = self.catalog.catalogs(refresh=True)
        self.assertEqual(result["status"], "BROWSE_ONLY")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["error"], "CATALOG_PAGINATION_INVALID")
        self.assertGreater(len(self.provider.calls), 1)

    def test_provider_metadata_concurrency_is_bounded_for_large_metastores(self):
        guard = threading.Lock()
        active = 0
        maximum = 0

        class SlowProvider:
            def page(_self, operation, **_parameters):
                nonlocal active, maximum
                with guard:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(.03)
                with guard:
                    active -= 1
                return {"schemas": []}

        catalog = CatalogService(self.store, SlowProvider())
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: catalog._fetch_all("schemas.list", catalog_name="main"), range(8)))
        self.assertEqual(results, [[] for _ in range(8)])
        self.assertLessEqual(maximum, 2)
        self.assertEqual(maximum, 2)

    def test_more_than_fifty_catalogs_are_fully_paginated_and_persisted(self):
        names = [f"catalog_{index:02d}" for index in range(53)]

        class ManyCatalogs:
            def page(_self, operation, **parameters):
                self.assertEqual(operation, "catalogs.list")
                self.assertLessEqual(parameters["max_results"], 50)
                offset = 50 if parameters.get("page_token") else 0
                page_names = names[offset:offset + 50]
                return {"catalogs": [{"name": name} for name in page_names],
                        "next_page_token": "page-2" if not offset else None}

        result = CatalogService(self.store, ManyCatalogs()).catalogs(refresh=True, limit=100)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(self.store.catalog_list(object_type="CATALOG", limit=100)), 53)
        self.assertTrue(result["hydration"]["state"] == "READY")

    def test_confirmed_empty_permission_error_and_unloaded_are_distinct(self):
        self.assertEqual(self.catalog.schemas("main")["status"], "NOT_LOADED")

        class EmptyProvider:
            def page(self, operation, **_kwargs):
                return {"schemas": []} if operation == "schemas.list" else {"catalogs": []}

        empty = CatalogService(self.store, EmptyProvider()).schemas("main", refresh=True)
        self.assertEqual(empty["status"], "EMPTY")

        class DeniedProvider:
            def page(self, *_args, **_kwargs):
                raise ProviderError("denied", code="PERMISSION_DENIED", retryable=False)

        denied = CatalogService(self.store, DeniedProvider()).schemas("private", refresh=True)
        self.assertEqual(denied["status"], "BROWSE_ONLY")
        self.assertEqual(denied["error"], "PERMISSION_DENIED")

    def test_catalog_parameters_reject_unsafe_names(self):
        with self.assertRaises(ValidationError):
            self.catalog.schemas("../system", refresh=True)
        with self.assertRaises(ValidationError):
            self.catalog.describe("main/silver/orders")
        with self.assertRaises(ValidationError):
            self.catalog.refresh_scope("all")

    def test_missing_provider_uses_cached_browse_state(self):
        self.catalog.catalogs(refresh=True)
        service = CatalogService(self.store, None)
        result = service.catalogs()
        self.assertEqual(result["status"], "CACHED")
        self.assertEqual(len(result["items"]), 2)

    def test_table_preview_runs_only_after_explicit_request_and_is_bounded(self):
        self.assertEqual(self.provider.preview_calls, [])
        result = self.catalog.preview("main.silver.orders", "wh-test", limit=10000)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(self.provider.preview_calls, [("main.silver.orders", "wh-test", 100)])

    def test_shared_capability_routes_through_selected_provider_and_encodes_page(self):
        shared = _shared_module()
        calls = []
        old_resolve = shared.resolve_profile
        old_call = shared._call_provider
        old_record = shared._record_runtime_outcome
        try:
            shared.resolve_profile = lambda profile: (profile or "anvil-test", "https://example.invalid", [])

            def invoke(capability, operation, arguments, **kwargs):
                calls.append((capability, operation, arguments, kwargs))
                return {"value": {"catalogs": []}, "provider": "sdk"}

            shared._call_provider = invoke
            shared._record_runtime_outcome = lambda *_args, **_kwargs: None
            value = shared.unity_catalog_page("catalogs.list", profile="anvil-test",
                                              page_token="next/page", max_results=25)
        finally:
            shared.resolve_profile = old_resolve
            shared._call_provider = old_call
            shared._record_runtime_outcome = old_record
        self.assertEqual(value, {"catalogs": []})
        capability, operation, args, kwargs = calls[0]
        self.assertEqual((capability, operation), ("catalog.read", "catalogs.list"))
        self.assertIn("/api/2.1/unity-catalog/catalogs?", args[2])
        self.assertIn("page_token=next%2Fpage", args[2])
        self.assertEqual(kwargs["payload"]["query"]["max_results"], "25")
        self.assertEqual(resolver.candidates("catalog.read", {
            "cli": {"status": "READY"}, "sdk": {"status": "READY"}}), ["cli", "sdk"])

    def test_statement_transfer_uses_bounded_external_arrow_and_shared_provider_route(self):
        shared = _shared_module()
        calls = []
        old_resolve = shared.resolve_profile
        old_warehouses = shared.discover_warehouses
        old_call = shared._call_provider
        old_record = shared._record_runtime_outcome
        try:
            shared.resolve_profile = lambda profile: (profile or "anvil-test", "https://example.invalid", [])
            shared.discover_warehouses = lambda _profile: {
                "running": [{"warehouse_id": "wh-test", "state": "RUNNING"}],
                "warehouses": [{"warehouse_id": "wh-test", "state": "RUNNING"}]}

            def invoke(capability, operation, arguments, **kwargs):
                calls.append((capability, operation, arguments, kwargs))
                if operation == "sql.transfer.submit":
                    value = {"statement_id": "statement-1", "status": {"state": "PENDING"}}
                elif operation == "sql.transfer.get":
                    value = {"statement_id": "statement-1", "status": {"state": "SUCCEEDED"}}
                elif operation == "sql.transfer.chunk":
                    value = {"external_links": [{"chunk_index": 0, "external_link": "https://storage.invalid/signed"}]}
                else:
                    value = {"cancelled": True}
                return {"value": value, "provider": "sdk"}

            shared._call_provider = invoke
            shared._record_runtime_outcome = lambda *_args, **_kwargs: None
            submitted = shared.start_sql_transfer("SELECT order_id FROM main.silver.orders", "wh-test",
                                                   profile="anvil-test", max_rows=20, max_bytes=2_000_000)
            status = shared.sql_transfer_status(submitted["statement_id"], "wh-test", profile="anvil-test")
            chunk = shared.sql_transfer_chunk(submitted["statement_id"], 0, "wh-test", profile="anvil-test")
            cancelled = shared.cancel_sql_transfer(submitted["statement_id"], profile="anvil-test")
        finally:
            shared.resolve_profile = old_resolve
            shared.discover_warehouses = old_warehouses
            shared._call_provider = old_call
            shared._record_runtime_outcome = old_record
        body = calls[0][3]["cli_body"]
        self.assertEqual((body["disposition"], body["format"]), ("EXTERNAL_LINKS", "ARROW_STREAM"))
        self.assertEqual((body["row_limit"], body["byte_limit"]), (20, 2_000_000))
        self.assertEqual(submitted["statement_id"], status["statement_id"])
        self.assertEqual(chunk["external_links"][0]["chunk_index"], 0)
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual({call[0] for call in calls}, {"sql.execute"})

    def test_explicit_transfer_starts_a_stopped_warehouse(self):
        shared = _shared_module()
        calls = []
        old_resolve = shared.resolve_profile
        old_warehouses = shared.discover_warehouses
        old_ensure = shared.ensure_warehouse_running
        old_call = shared._call_provider
        old_record = shared._record_runtime_outcome
        try:
            shared.resolve_profile = lambda profile: (profile or "anvil-test", "https://example.invalid", [])
            stopped = {"warehouse_id": "wh-stopped", "name": "BI", "state": "STOPPED"}
            shared.discover_warehouses = lambda _profile: {"warehouses": [stopped], "running": [], "stopped": [stopped]}

            def ensure(warehouse, profile):
                calls.append(("ensure", warehouse["state"], profile))
                return {**warehouse, "state": "RUNNING"}

            shared.ensure_warehouse_running = ensure
            def submit(*_args, **kwargs):
                calls.append(("submit", kwargs["cli_body"]))
                return {"value": {"statement_id": "statement-stopped"}, "provider": "sdk"}
            shared._call_provider = submit
            shared._record_runtime_outcome = lambda *_args, **_kwargs: None
            result = shared.start_sql_transfer("SELECT order_id FROM main.silver.orders", "wh-stopped",
                                               profile="anvil-test",
                                               on_warehouse_ready=lambda: calls.append(("ready",)))
        finally:
            shared.resolve_profile = old_resolve
            shared.discover_warehouses = old_warehouses
            shared.ensure_warehouse_running = old_ensure
            shared._call_provider = old_call
            shared._record_runtime_outcome = old_record
        self.assertEqual(calls[0], ("ensure", "STOPPED", "anvil-test"))
        self.assertEqual(calls[1], ("ready",))
        self.assertEqual(calls[2][0], "submit")
        self.assertNotIn("row_limit", calls[2][1])
        self.assertNotIn("byte_limit", calls[2][1])
        self.assertEqual(result["statement_id"], "statement-stopped")

    def test_sdk_worker_submits_external_arrow_with_existing_workspace_client(self):
        calls = {}

        class StatementAPI:
            def execute_statement(self, **kwargs):
                calls["statement"] = kwargs
                return {"statement_id": "statement-2", "status": {"state": "SUCCEEDED"},
                        "result": {"external_links": [{"chunk_index": 0,
                                                       "external_link": "https://storage.invalid/temporary"}]}}

        class Workspace:
            def __init__(self, *, config):
                calls["config"] = config
                self.statement_execution = StatementAPI()

        databricks = types.ModuleType("databricks")
        databricks.__path__ = []
        sdk = types.ModuleType("databricks.sdk")
        sdk.WorkspaceClient = Workspace
        core = types.ModuleType("databricks.sdk.core")
        core.Config = lambda **kwargs: kwargs
        service = types.ModuleType("databricks.sdk.service")
        service.__path__ = []
        service.compute = types.ModuleType("databricks.sdk.service.compute")
        service.sql = types.ModuleType("databricks.sdk.service.sql")
        service.sql.ExecuteStatementRequestOnWaitTimeout = types.SimpleNamespace(CONTINUE="CONTINUE")
        service.sql.Disposition = types.SimpleNamespace(EXTERNAL_LINKS="EXTERNAL_LINKS")
        service.sql.Format = types.SimpleNamespace(ARROW_STREAM="ARROW_STREAM")
        modules = {"databricks": databricks, "databricks.sdk": sdk,
                   "databricks.sdk.core": core, "databricks.sdk.service": service}
        request = {"operation": "sql.transfer.submit", "profile": "anvil-test", "timeout": 30,
                   "payload": {"statement": "SELECT 1", "warehouse_id": "wh-test",
                               "row_limit": 100, "byte_limit": 2_000_000}}
        with mock.patch.dict(sys.modules, modules), \
             mock.patch.dict("os.environ", {"DATABRICKS_CONFIG_FILE": "/tmp/anvil-test.cfg"}), \
             mock.patch("sys.stdin", io.StringIO(json.dumps(request))), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            status = sdk_worker.main()
        self.assertEqual(status, 0)
        self.assertEqual(calls["statement"]["disposition"], "EXTERNAL_LINKS")
        self.assertEqual(calls["statement"]["format"], "ARROW_STREAM")
        result = json.loads(output.getvalue())
        self.assertEqual(result["statement_id"], "statement-2")

    def test_cli_provider_body_uses_private_temporary_file_not_process_argument(self):
        shared = _shared_module()
        observed = {}
        old_candidates = shared.resolver.candidates
        old_rejections = shared.resolver.candidate_rejections
        old_auth = shared._auth_route
        old_run = shared.run_cli
        try:
            shared.resolver.candidates = lambda *_args, **_kwargs: ["cli"]
            shared.resolver.candidate_rejections = lambda *_args, **_kwargs: []
            shared._auth_route = lambda *_args, **_kwargs: (None, None)

            def run_cli(args, **kwargs):
                observed["args"] = list(args)
                body_arg = next(arg for arg in args if arg.startswith("@"))
                body_path = Path(body_arg[1:])
                observed["body_path"] = body_path
                observed["body"] = json.loads(body_path.read_text())
                observed["mode"] = body_path.stat().st_mode & 0o777
                return '{"statement_id":"statement-cli"}'

            shared.run_cli = run_cli
            result = shared._call_provider("sql.execute", "sql.transfer.submit",
                ["api", "post", "/api/2.0/sql/statements"], profile="anvil-test",
                payload={"statement": "select 1"},
                cli_body={"statement": "select 1", "disposition": "EXTERNAL_LINKS"},
                providers={"cli": {"status": "READY"}})
        finally:
            shared.resolver.candidates = old_candidates
            shared.resolver.candidate_rejections = old_rejections
            shared._auth_route = old_auth
            shared.run_cli = old_run
        self.assertEqual(result["provider"], "cli")
        self.assertEqual(observed["body"]["disposition"], "EXTERNAL_LINKS")
        self.assertEqual(observed["mode"], 0o600)
        self.assertFalse(observed["body_path"].exists())

    def test_sdk_provider_uses_authenticated_api_client_for_catalog_requests(self):
        calls = {}

        class Workspace:
            def __init__(self, *, config):
                calls["config"] = config
                self.api_client = self

            def do(self, *, method, path, query):
                calls["request"] = (method, path, query)
                return {"tables": [{"name": "orders"}]}

        databricks = types.ModuleType("databricks")
        databricks.__path__ = []
        sdk = types.ModuleType("databricks.sdk")
        sdk.WorkspaceClient = Workspace
        core = types.ModuleType("databricks.sdk.core")
        core.Config = lambda **kwargs: kwargs
        service = types.ModuleType("databricks.sdk.service")
        service.__path__ = []
        service.compute = types.ModuleType("databricks.sdk.service.compute")
        service.sql = types.ModuleType("databricks.sdk.service.sql")
        modules = {"databricks": databricks, "databricks.sdk": sdk,
                   "databricks.sdk.core": core, "databricks.sdk.service": service}
        request = {"operation": "catalog.read", "profile": "anvil-test", "timeout": 30,
                   "payload": {"path": "/api/2.1/unity-catalog/tables",
                               "query": {"catalog_name": "main", "schema_name": "silver"}}}
        with mock.patch.dict(sys.modules, modules), \
             mock.patch.dict("os.environ", {"DATABRICKS_CONFIG_FILE": "/tmp/anvil-test.cfg"}), \
             mock.patch("sys.stdin", io.StringIO(json.dumps(request))), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            status = sdk_worker.main()
        self.assertEqual(status, 0)
        self.assertEqual(calls["request"], ("GET", "/api/2.1/unity-catalog/tables",
                                             {"catalog_name": "main", "schema_name": "silver"}))
        self.assertEqual(json.loads(output.getvalue())["tables"][0]["name"], "orders")


if __name__ == "__main__":
    unittest.main()
