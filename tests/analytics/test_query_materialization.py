from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.analytics.coverage import CoverageRegistry, source_key
from scripts.analytics.errors import (CoverageError, IntegrityError, ReadOnlyError,
                                      UnavailableError, ValidationError)
from scripts.analytics.materialization import MaterializationService
from scripts.analytics.models import QueryRoute
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.planner import (ensure_read_only, parse_local_query,
                                       plan_materialization)
from scripts.analytics.query import QueryRouter
from scripts.analytics.store import ContextStore
from scripts.analytics.transfer import ChunkStats, MaterializationTransfer


class FakeLocalEngine:
    available = True

    def __init__(self):
        self.calls = []

    def query(self, plan, snapshot, **kwargs):
        self.calls.append((plan, snapshot, kwargs))
        return {"columns": list(plan.projection), "rows": [[7]],
                "row_count": 1, "byte_count": 4, "truncated": False}


class MissingLocalEngine:
    available = False
    failure_code = "LOCAL_ENGINE_MISSING"


class FakeRemote:
    def __init__(self):
        self.calls = []
        self.result = {"columns": ["order_id"], "rows": [[7]], "truncated": False}

    def execute_sql(self, statement, warehouse_id, **kwargs):
        self.calls.append((statement, warehouse_id, kwargs))
        return self.result


class FakeTransferProvider:
    def __init__(self):
        self.submit_count = 0
        self.chunk_requests = []
        self.cancel_count = 0

    def transfer_submit(self, statement, warehouse_id, **kwargs):
        self.submit_count += 1
        return self.success_response(include_first_link=True)

    def transfer_status(self, statement_id, warehouse_id, **kwargs):
        return self.success_response(include_first_link=True)

    def transfer_chunk(self, statement_id, chunk_index, warehouse_id, **kwargs):
        self.chunk_requests.append(chunk_index)
        return {"result": {"external_links": [{"chunk_index": chunk_index,
                                                  "external_link": f"https://storage.example/chunk-{chunk_index}?sig=secret",
                                                  "byte_count": 7}]}}

    def transfer_cancel(self, statement_id, **kwargs):
        self.cancel_count += 1
        return {"cancelled": True}

    @staticmethod
    def success_response(*, include_first_link):
        links = ([{"chunk_index": 0, "external_link": "https://storage.example/chunk-0?sig=secret",
                   "byte_count": 7}] if include_first_link else [])
        return {"statement_id": "stmt-123", "status": {"state": "SUCCEEDED"},
                "manifest": {"format": "ARROW_STREAM", "total_chunk_count": 2,
                             "total_row_count": 3, "total_byte_count": 14,
                             "truncated": False,
                             "schema": {"columns": [{"name": "order_id"}, {"name": "status"}]}},
                "result": {"external_links": links}}


class FakeDownloader:
    def __init__(self, *, fail_url_once=""):
        self.calls = []
        self.fail_url_once = fail_url_once
        self.failed = False

    def download(self, url, destination, *, max_bytes, timeout=120):
        self.calls.append(url)
        if self.fail_url_once and url == self.fail_url_once and not self.failed:
            self.failed = True
            raise UnavailableError("transfer down", code="TRANSFER_NETWORK_FAILED", retryable=True)
        payload = b"chunk-0" if "chunk-0" in url else b"chunk-1"
        destination.write_bytes(payload)
        import hashlib
        return len(payload), hashlib.sha256(payload).hexdigest()


class FakeCodec:
    available = True

    def write_parquet(self, arrow_file, parquet_file):
        payload = arrow_file.read_bytes()
        parquet_file.write_bytes(b"parquet:" + payload)
        rows = 2 if payload == b"chunk-0" else 1
        return ChunkStats(rows, ("order_id", "status"), "schema-v1")

    def write_empty(self, schema, parquet_file):
        parquet_file.write_bytes(b"empty-parquet")
        return ChunkStats(0, tuple(item["name"] for item in schema.get("columns", [])), "schema-empty")


class QueryCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AnalyticsPaths.from_root(Path(self.temp.name) / ".anvil", create=True)
        self.store = ContextStore(paths=self.paths)
        self.coverage = CoverageRegistry(self.paths, self.store)
        self.source = "main.silver.orders"

    def publish(self, *, columns=("order_id", "status"), predicate="", complete=True,
                snapshot_id="a" * 64):
        root = self.paths.datasets / source_key(self.source)
        snapshot = root / "snapshots" / snapshot_id
        snapshot.mkdir(parents=True, mode=0o700)
        data = snapshot / "part-00000.parquet"
        data.write_bytes(b"parquet-fixture")
        manifest = {"state": "READY", "snapshot_id": snapshot_id,
                    "source_name": self.source, "source_version": "version-1",
                    "columns": list(columns), "all_columns": columns == ("*",),
                    "predicate": predicate, "complete": complete, "row_count": 10,
                    "bytes": data.stat().st_size, "files": [data.name],
                    "file_bytes": {data.name: data.stat().st_size}}
        (snapshot / "manifest.json").write_text(json.dumps(manifest))
        pointer = root / "current.json"
        pointer.write_text(json.dumps({"snapshot_id": snapshot_id}))
        with self.store.transaction() as db:
            db.execute("""INSERT OR REPLACE INTO materializations(
                materialization_id,source_name,source_version,filters_json,columns_json,
                coverage_json,state,files_json,byte_count,principal,created_at,updated_at,error_code)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, self.source, "version-1", "[]", json.dumps(columns),
                 json.dumps(manifest), "READY", json.dumps([data.name]), data.stat().st_size,
                 "test", "now", "now", ""))
        return snapshot

    def test_coverage_requires_exact_filter_and_all_projected_columns(self):
        self.publish(predicate="status = 'failed'")
        exact = parse_local_query("SELECT order_id FROM main.silver.orders WHERE status = 'failed'")
        self.assertTrue(self.coverage.covers(exact).covered)

        wrong_filter = parse_local_query("SELECT order_id FROM main.silver.orders WHERE status = 'ok'")
        self.assertFalse(self.coverage.covers(wrong_filter).covered)
        wrong_projection = parse_local_query("SELECT amount FROM main.silver.orders WHERE status = 'failed'")
        decision = self.coverage.covers(wrong_projection)
        self.assertFalse(decision.covered)
        self.assertEqual(decision.missing_columns, ("amount",))

    def test_partial_snapshot_is_never_claimed_as_complete_local_coverage(self):
        self.publish(columns=("order_id",), complete=False)
        plan = parse_local_query("SELECT order_id FROM main.silver.orders LIMIT 5")
        decision = self.coverage.covers(plan)
        self.assertFalse(decision.covered)
        self.assertIn("partial", decision.reason)

    def test_pointer_manifest_and_parquet_files_are_validated(self):
        snapshot = self.publish()
        current = self.coverage.current(self.source)
        self.assertEqual(current["snapshot_dir"], snapshot)
        self.assertEqual(len(current["files"]), 1)

        file_path = current["files"][0]
        file_path.write_bytes(b"tampered")
        with self.assertRaises(IntegrityError):
            self.coverage.current(self.source)

    def test_local_routing_needs_proven_coverage_and_never_calls_remote(self):
        self.publish()
        local = FakeLocalEngine()
        remote = FakeRemote()
        router = QueryRouter(self.store, self.coverage, remote, local=local)
        result = router.execute("SELECT order_id FROM main.silver.orders", route=QueryRoute.AUTO)
        self.assertEqual(result["route"], "LOCAL")
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(remote.calls, [])

        with self.assertRaises(CoverageError):
            router.execute("SELECT amount FROM main.silver.orders", route="LOCAL")
        self.assertEqual(remote.calls, [])

    def test_auto_falls_back_to_remote_for_mismatch_or_missing_duckdb(self):
        self.publish()
        remote = FakeRemote()
        router = QueryRouter(self.store, self.coverage, remote, local=MissingLocalEngine())
        result = router.execute("SELECT amount FROM main.silver.orders", route="AUTO",
                                warehouse_id="wh-test")
        self.assertEqual(result["route"], "DATABRICKS")
        self.assertEqual(len(remote.calls), 1)
        self.assertEqual(self.store.query_recent(limit=1)[0]["route"], "DATABRICKS")

    def test_remote_results_are_bounded_even_when_adapter_returns_too_much(self):
        remote = FakeRemote()
        remote.result = {"columns": ["value"], "rows": [[index] for index in range(150)],
                         "truncated": False}
        router = QueryRouter(self.store, self.coverage, remote, local=MissingLocalEngine())
        result = router.execute("SELECT value FROM main.silver.orders", route="DATABRICKS",
                                warehouse_id="wh-test")
        self.assertEqual(len(result["rows"]), 100)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["row_count"], 100)

    def test_mutations_and_multiple_statements_are_rejected_before_provider_calls(self):
        remote = FakeRemote()
        router = QueryRouter(self.store, self.coverage, remote, local=FakeLocalEngine())
        for sql in ("DELETE FROM main.silver.orders", "SELECT 1; DROP TABLE x",
                    "SELECT 1 -- hidden statement"):
            with self.subTest(sql=sql), self.assertRaises(ReadOnlyError):
                router.execute(sql, warehouse_id="wh-test")
        self.assertEqual(remote.calls, [])
        self.assertEqual(len(self.store.query_recent()), 0)

    def test_explicit_remote_route_records_the_actual_route(self):
        remote = FakeRemote()
        router = QueryRouter(self.store, self.coverage, remote, local=FakeLocalEngine())
        result = router.execute("SELECT count(*) FROM main.silver.orders", route="DATABRICKS",
                                warehouse_id="wh-test")
        self.assertEqual(result["route"], "DATABRICKS")
        self.assertEqual(self.store.query_recent(limit=1)[0]["source_objects"], [])

    def test_local_parser_accepts_simple_select_but_defers_joins_and_ctes(self):
        plan = parse_local_query("SELECT `order_id`, status FROM main.silver.orders WHERE status = 'failed' LIMIT 20")
        self.assertEqual(plan.source_name, self.source)
        self.assertEqual(plan.projection, ("order_id", "status"))
        self.assertEqual(plan.limit, 20)
        self.assertIsNone(parse_local_query("SELECT o.order_id FROM main.silver.orders o JOIN main.silver.users u ON o.id=u.id"))
        self.assertIsNone(parse_local_query("WITH recent AS (SELECT 1) SELECT * FROM recent"))

    def test_materialization_plan_is_minimum_sufficient_and_bounded(self):
        plan = plan_materialization(workspace_identity="workspace-hash", source_name=self.source,
            projection=["order_id", "status"], predicate="status = 'failed'",
            source_version="v-10", max_rows=500, max_bytes=10_000_000,
            estimated_bytes=2_000_000)
        self.assertEqual(plan.source_version, "v-10")
        self.assertEqual(plan.projection, ("order_id", "status"))
        self.assertIn("LIMIT 500", plan.statement())
        self.assertNotIn("SELECT *", plan.statement())
        self.assertEqual(plan.max_rows, 500)

        filtered = plan_materialization(workspace_identity="w", source_name=self.source,
            projection=["order_id"], predicate="status = 'failed'", source_version="v-10")
        self.assertEqual(filtered.projection, ("order_id", "status"))

    def test_full_table_and_unsafe_materialization_plans_require_confirmation_or_fail(self):
        with self.assertRaises(ValidationError):
            plan_materialization(workspace_identity="w", source_name=self.source, projection=["*"])
        with self.assertRaises(ValidationError):
            plan_materialization(workspace_identity="w", source_name=self.source,
                                 projection=["order_id; DROP TABLE x"])
        with self.assertRaises(ValidationError):
            plan_materialization(workspace_identity="w", source_name=self.source,
                                 projection=["order_id"], predicate="status = 'x'; DROP TABLE t")
        confirmed = plan_materialization(workspace_identity="w", source_name=self.source,
            projection=["*"], full_table_confirmed=True)
        self.assertEqual(confirmed.projection, ("*",))

    def make_transfer_plan(self):
        return plan_materialization(workspace_identity="workspace-hash", source_name=self.source,
            projection=["order_id", "status"], source_version="version-1", max_rows=10,
            max_bytes=1_048_576)

    def test_materialization_downloads_arrow_chunks_and_atomically_publishes_parquet(self):
        provider = FakeTransferProvider()
        downloader = FakeDownloader()
        service = MaterializationTransfer(self.paths, self.store, provider,
                                          downloader=downloader, codec=FakeCodec(), sleep=lambda _: None)
        plan = self.make_transfer_plan()
        result = service.run(plan, "warehouse-1", profile="anvil-prod", principal="user@example.com")
        self.assertEqual(result["state"], "READY")
        self.assertEqual(result["rows"], 3)
        self.assertEqual(provider.submit_count, 1)
        self.assertEqual(provider.chunk_requests, [1])
        self.assertEqual(self.coverage.current(self.source)["manifest"]["operation_id"], plan.operation_id)
        self.assertTrue(self.coverage.covers(parse_local_query(
            "SELECT order_id FROM main.silver.orders")).covered)
        record = self.store.operation_get(plan.operation_id)
        self.assertEqual(record.state.value, "READY")
        self.assertNotIn("sig=secret", json.dumps(record.as_dict() if hasattr(record, "as_dict") else record.checkpoint))
        self.assertNotIn("sig=secret", json.dumps(self.store.materialization_recent()))
        again = service.run(plan, "warehouse-1", profile="anvil-prod")
        self.assertTrue(again["reused"])
        self.assertEqual(provider.submit_count, 1)

    def test_interrupted_materialization_resumes_checkpoint_without_duplicate_query(self):
        provider = FakeTransferProvider()
        downloader = FakeDownloader(fail_url_once="https://storage.example/chunk-1?sig=secret")
        service = MaterializationTransfer(self.paths, self.store, provider,
                                          downloader=downloader, codec=FakeCodec(), sleep=lambda _: None)
        plan = self.make_transfer_plan()
        with self.assertRaises(UnavailableError):
            service.run(plan, "warehouse-1")
        paused = self.store.operation_get(plan.operation_id)
        self.assertEqual(paused.state.value, "PAUSED")
        self.assertEqual([item["index"] for item in paused.checkpoint["chunks"]], [0])
        result = service.run(plan, "warehouse-1")
        self.assertEqual(result["state"], "READY")
        self.assertEqual(provider.submit_count, 1)
        self.assertEqual(downloader.calls.count("https://storage.example/chunk-0?sig=secret"), 1)
        self.assertEqual(downloader.calls.count("https://storage.example/chunk-1?sig=secret"), 2)

    def test_failed_refresh_keeps_the_previous_current_snapshot(self):
        self.publish()
        before = self.coverage.current(self.source)["snapshot_id"]
        provider = FakeTransferProvider()
        downloader = FakeDownloader(fail_url_once="https://storage.example/chunk-0?sig=secret")
        service = MaterializationTransfer(self.paths, self.store, provider,
                                          downloader=downloader, codec=FakeCodec(), sleep=lambda _: None)
        plan = self.make_transfer_plan()
        with self.assertRaises(UnavailableError):
            service.run(plan, "warehouse-1")
        self.assertEqual(self.coverage.current(self.source)["snapshot_id"], before)

    def test_missing_pyarrow_degrades_before_remote_query(self):
        provider = FakeTransferProvider()
        service = MaterializationTransfer(self.paths, self.store, provider,
                                          downloader=FakeDownloader(), codec=type("MissingCodec", (), {"available": False})())
        with self.assertRaises(UnavailableError) as caught:
            service.run(self.make_transfer_plan(), "warehouse-1")
        self.assertEqual(caught.exception.code, "PYARROW_MISSING")
        self.assertEqual(provider.submit_count, 0)

    def test_materialization_service_uses_shared_plan_and_hides_provider_checkpoint_details(self):
        provider = FakeTransferProvider()
        transfer = MaterializationTransfer(self.paths, self.store, provider,
                                           downloader=FakeDownloader(), codec=FakeCodec(), sleep=lambda _: None)
        service = MaterializationService(self.paths, self.store, provider, transfer=transfer)
        plan = service.plan(workspace_identity="workspace-hash", source_name=self.source,
                            projection=["order_id", "status"], source_version="version-1",
                            max_rows=10, max_bytes=1_048_576)
        service.run(plan, "warehouse-1", profile="anvil-prod")
        visible = service.status(plan.operation_id)
        self.assertEqual(visible["state"], "READY")
        self.assertNotIn("statement_id", visible)
        self.assertNotIn("sig=secret", json.dumps(visible))
        self.assertEqual(service.recent(limit=5)[0]["operation_id"], plan.operation_id)


if __name__ == "__main__":
    unittest.main()
