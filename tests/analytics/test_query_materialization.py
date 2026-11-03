from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.analytics.coverage import (CoverageRegistry, dataset_lock, predicates_cover,
                                        schema_identity, source_key)
from scripts.analytics.errors import (ConflictError, CoverageError, IntegrityError, ReadOnlyError,
                                      UnavailableError, ValidationError)
from scripts.analytics.materialization import MaterializationService
from scripts.analytics.models import MaterializationState, OperationRecord, QueryRoute
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.planner import (ensure_read_only, parse_local_query,
                                       plan_materialization)
from scripts.analytics.query import DuckDBLocalEngine, QueryRouter
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


class _FakeArrowColumn:
    def to_pylist(self):
        return [3]


class _FakeArrowResult:
    column_names = ["count_star()"]
    columns = [_FakeArrowColumn()]


class _FakeDuckDBCursor:
    def to_arrow_table(self):
        return _FakeArrowResult()

    def fetchall(self):
        return [("order_id", "BIGINT")]


class _FakeDuckDBRelation:
    def create_view(self, *_args, **_kwargs):
        return self


class _FakeDuckDBConnection:
    def __init__(self):
        self.statement = ""

    def read_parquet(self, _files):
        return _FakeDuckDBRelation()

    def execute(self, statement):
        self.statement = statement
        return _FakeDuckDBCursor()

    def close(self):
        pass


class _FakeDuckDBModule:
    def __init__(self):
        self.connection = _FakeDuckDBConnection()

    def connect(self, **_kwargs):
        return self.connection


class FakeTransferProvider:
    def __init__(self):
        self.submit_count = 0
        self.chunk_requests = []
        self.cancel_count = 0
        self.status_state = "SUCCEEDED"

    def transfer_submit(self, statement, warehouse_id, **kwargs):
        self.submit_count += 1
        return self.success_response(include_first_link=True)

    def transfer_status(self, statement_id, warehouse_id, **kwargs):
        result = self.success_response(include_first_link=True)
        result["status"]["state"] = self.status_state
        return result

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
    def __init__(self, *, fail_url_once="", fail_url_always=""):
        self.calls = []
        self.fail_url_once = fail_url_once
        self.fail_url_always = fail_url_always
        self.failed = False

    def download(self, url, destination, *, max_bytes, timeout=120):
        self.calls.append(url)
        if url == self.fail_url_always or (self.fail_url_once and url == self.fail_url_once and not self.failed):
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
                snapshot_id="a" * 64, workspace_identity=None, manifest_workspace_identity=None,
                all_columns=False):
        root = self.paths.datasets / source_key(self.source, workspace_identity)
        snapshot = root / "snapshots" / snapshot_id
        snapshot.mkdir(parents=True, mode=0o700)
        data = snapshot / "part-00000.parquet"
        data.write_bytes(b"parquet-fixture")
        manifest = {"state": "READY", "snapshot_id": snapshot_id,
                    "source_name": self.source, "source_version": "version-1",
                    "workspace_identity": manifest_workspace_identity or workspace_identity or "",
                    "columns": list(columns), "all_columns": all_columns or columns == ("*",),
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

    def test_coverage_is_scoped_to_the_workspace_and_predicate_subsets_are_proven(self):
        self.publish(columns=("order_id", "status", "event_date"),
                     workspace_identity="workspace-a",
                     predicate="event_date >= DATE '2026-01-01'")
        plan = parse_local_query("SELECT order_id FROM main.silver.orders WHERE event_date >= DATE '2026-02-01'")
        self.assertTrue(self.coverage.covers(plan, workspace_identity="workspace-a").covered)
        self.assertFalse(self.coverage.covers(plan, workspace_identity="workspace-b").covered)
        self.assertFalse(predicates_cover("status = 'failed'", "status = 'failed' OR status = 'queued'"))
        self.assertTrue(predicates_cover("amount >= 10 AND amount < 20", "amount = 12"))
        self.assertFalse(predicates_cover("amount >= 10", "amount >= 9"))

    def test_materialization_planner_reuses_broad_copy_and_expands_partial_copy(self):
        self.publish(columns=("order_id", "status", "amount"), all_columns=True,
                     workspace_identity="workspace-a")
        narrow = self.coverage.plan_materialization(workspace_identity="workspace-a",
            source_name=self.source, projection=("order_id", "status"),
            source_version="version-1", rows_mode="FULL")
        self.assertEqual(narrow.action, "REUSE_WITH_PROJECTION")
        self.assertFalse(narrow.remote_transfer_required)

        self.publish(columns=("order_id", "status"), workspace_identity="workspace-b",
                     snapshot_id="d" * 64)
        expanded = self.coverage.plan_materialization(workspace_identity="workspace-b",
            source_name=self.source, projection=("*",), source_version="version-1",
            rows_mode="FULL")
        self.assertEqual(expanded.action, "REMATERIALIZE")
        self.assertTrue(expanded.remote_transfer_required)

    def test_legacy_duplicate_reconciliation_selects_the_broadest_verified_generation(self):
        self.publish(columns=("order_id",), snapshot_id="e" * 64,
                     workspace_identity="workspace-a")
        self.publish(columns=("order_id", "status", "amount"), all_columns=True,
                     snapshot_id="f" * 64, manifest_workspace_identity="workspace-a")
        current = self.coverage.current(self.source, "workspace-a")
        self.assertEqual(current["snapshot_id"], "f" * 64)
        local_rows = self.coverage.list_local_datasets("workspace-a")
        self.assertEqual(len(local_rows), 1)
        self.assertEqual(local_rows[0]["snapshot_id"], "f" * 64)

    def test_legacy_dataset_state_is_normalized_to_current_schema_version(self):
        from scripts.analytics.coverage import dataset_state
        self.publish(workspace_identity="workspace-a")
        root = self.coverage.dataset_root(self.source, "workspace-a")
        old = dataset_state(root)
        self.assertEqual(old["schema_version"], 2)
        self.assertEqual(old["current_generation"], old["current"]["snapshot_id"])

    def test_selected_intent_survives_an_unrequested_new_remote_column(self):
        self.publish(columns=("order_id", "status"), workspace_identity="workspace-a")
        current = self.coverage.current(self.source, "workspace-a")
        old_schema = [{"name": "order_id", "type_text": "BIGINT"},
                      {"name": "status", "type_text": "STRING"},
                      {"name": "amount", "type_text": "DECIMAL(18,2)"}]
        selected_schema = old_schema[:2]
        manifest_path = current["snapshot_dir"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.update({"columns_mode": "SELECTED", "selected_columns": ["order_id", "status"],
                         "source_schema_identity": schema_identity(old_schema),
                         "selected_schema_identity": schema_identity(selected_schema),
                         "source_version": "old-version"})
        manifest_path.write_text(json.dumps(manifest))
        remote_schema = old_schema + [{"name": "new_note", "type_text": "STRING"}]
        plan = parse_local_query("SELECT order_id FROM main.silver.orders")

        decision = self.coverage.covers(plan, workspace_identity="workspace-a",
                                        remote_schema=remote_schema, source_version="new-version")
        self.assertTrue(decision.covered)
        self.assertEqual(decision.state, "UNKNOWN")
        materialization = self.coverage.plan_materialization(
            workspace_identity="workspace-a", source_name=self.source,
            projection=("order_id",), source_version="new-version",
            remote_schema=remote_schema, rows_mode="FULL")
        self.assertFalse(materialization.remote_transfer_required)

    def test_all_intent_and_selected_type_changes_are_stale_schema(self):
        old_schema = [{"name": "order_id", "type_text": "BIGINT"},
                      {"name": "status", "type_text": "STRING"}]
        new_schema = old_schema + [{"name": "created_at", "type_text": "TIMESTAMP"}]
        self.publish(columns=("order_id", "status"), workspace_identity="workspace-a",
                     all_columns=True)
        current = self.coverage.current(self.source, "workspace-a")
        manifest_path = current["snapshot_dir"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.update({"columns_mode": "ALL", "all_columns": True,
                         "source_schema_identity": schema_identity(old_schema),
                         "schema_identity": schema_identity(old_schema)})
        manifest_path.write_text(json.dumps(manifest))
        query = parse_local_query("SELECT order_id FROM main.silver.orders")
        decision = self.coverage.covers(query, workspace_identity="workspace-a",
                                        remote_schema=new_schema, source_version="version-1")
        self.assertFalse(decision.covered)
        self.assertEqual(decision.state, "STALE")
        self.assertIn("schema_changed", decision.reasons)

        self.publish(columns=("order_id", "status"), workspace_identity="workspace-b",
                     snapshot_id="c" * 64)
        current = self.coverage.current(self.source, "workspace-b")
        manifest_path = current["snapshot_dir"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.update({"columns_mode": "SELECTED", "all_columns": False,
                         "selected_columns": ["order_id", "status"],
                         "source_schema_identity": schema_identity(old_schema),
                         "selected_schema_identity": schema_identity(old_schema)})
        manifest_path.write_text(json.dumps(manifest))
        changed_type = [{"name": "order_id", "type_text": "BIGINT"},
                        {"name": "status", "type_text": "BOOLEAN"}]
        decision = self.coverage.covers(query, workspace_identity="workspace-b",
                                        remote_schema=changed_type, source_version="version-1")
        self.assertFalse(decision.covered)
        self.assertEqual(decision.state, "STALE")
        self.assertIn("schema_changed", decision.reasons)

    def test_local_coverage_requires_filter_columns_for_duckdb_execution(self):
        self.publish(columns=("order_id",), workspace_identity="workspace-a")
        query = parse_local_query(
            "SELECT order_id FROM main.silver.orders WHERE status = 'failed'")
        decision = self.coverage.covers(query, workspace_identity="workspace-a")
        self.assertFalse(decision.covered)
        self.assertEqual(decision.missing_columns, ("status",))

    def test_shared_snapshot_reader_lock_blocks_exclusive_generation_cleanup(self):
        self.publish(workspace_identity="workspace-a")
        root = self.coverage.dataset_root(self.source, "workspace-a")
        with self.coverage.locked_snapshot(self.source, "workspace-a") as snapshot:
            self.assertIsNotNone(snapshot)
            with self.assertRaises(BlockingIOError):
                with dataset_lock(root, exclusive=True, blocking=False):
                    pass

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

    def test_count_star_is_covered_by_full_rows_without_required_columns(self):
        self.publish(columns=("order_id", "status"), all_columns=False)
        plan = parse_local_query("SELECT count(*) FROM main.silver.orders")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.requirements.required_columns, ())
        self.assertFalse(plan.requirements.requires_all_columns)
        self.assertTrue(plan.requirements.requires_full_row_population)
        decision = self.coverage.covers(plan, source_version="version-1")
        self.assertTrue(decision.covered, decision.reason)

        local, remote = FakeLocalEngine(), FakeRemote()
        result = QueryRouter(self.store, self.coverage, remote, local=local).execute(
            "SELECT count(*) FROM main.silver.orders", route="LOCAL",
            source_version="version-1")
        self.assertEqual(result["route"], "LOCAL")
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(remote.calls, [])

    def test_local_engine_runs_original_aggregate_against_local_snapshot(self):
        fake_duckdb = _FakeDuckDBModule()
        with patch.dict(sys.modules, {"duckdb": fake_duckdb}):
            engine = DuckDBLocalEngine()
        plan = parse_local_query("SELECT count(*) FROM `main`.`silver`.`orders`")
        result = engine.query(plan, {"files": [Path("/tmp/orders.parquet")]})
        self.assertEqual(result["rows"], [[3]])
        self.assertIn("count(*)", fake_duckdb.connection.statement)
        self.assertIn('FROM "_anvil_coverage_snapshot"', fake_duckdb.connection.statement)
        self.assertNotIn("main", fake_duckdb.connection.statement)

    def test_local_engine_rejects_coverage_that_disagrees_with_duckdb_schema(self):
        with self.assertRaisesRegex(CoverageError, "disagree") as raised:
            DuckDBLocalEngine.validate_snapshot_schema(
                _FakeDuckDBConnection(), {"manifest": {"columns": ["order_id", "status"]}},
                physical_columns=["order_id", "status"])
        self.assertEqual(raised.exception.code, "LOCAL_SCHEMA_MISMATCH")

    def test_local_schema_is_not_claimed_ready_without_independent_parquet_reader(self):
        with self.assertRaises(CoverageError) as raised:
            DuckDBLocalEngine.validate_snapshot_schema(
                _FakeDuckDBConnection(),
                {"manifest": {"columns": ["order_id"]},
                 "files": [Path("/path/that/does/not/exist.parquet")]})
        self.assertEqual(raised.exception.code, "LOCAL_SCHEMA_UNVERIFIED")

    def test_local_type_normalizer_executes_without_name_error(self):
        from scripts.analytics.query import _local_type
        self.assertEqual(_local_type("string"), "string")
        self.assertEqual(_local_type("decimal(18, 2)"), "decimal(18,2)")

    def test_internal_schema_verifier_failure_is_not_physical_corruption(self):
        from unittest.mock import patch
        with patch("scripts.analytics.query._local_type", side_effect=NameError("verifier bug")):
            with self.assertRaises(CoverageError) as raised:
                DuckDBLocalEngine.validate_snapshot_schema(
                    _FakeDuckDBConnection(), {"manifest": {"columns": ["order_id", "status"]}},
                    physical_columns=[("order_id", "string"), ("status", "string")])
        self.assertEqual(raised.exception.code, "INTERNAL_SCHEMA_VALIDATION_ERROR")

    def test_auto_uses_local_for_covered_aggregate_without_remote_or_warehouse(self):
        self.publish(columns=("order_id", "status"), all_columns=False)
        local, remote = FakeLocalEngine(), FakeRemote()
        router = QueryRouter(self.store, self.coverage, remote, local=local)
        for sql in (
            "SELECT count(*) FROM main.silver.orders",
            "SELECT count(status) FROM main.silver.orders",
            "SELECT status, count(*) FROM main.silver.orders GROUP BY status ORDER BY status LIMIT 20",
            "SELECT DISTINCT status FROM main.silver.orders ORDER BY status",
        ):
            with self.subTest(sql=sql):
                result = router.execute(sql, route="AUTO", source_version="version-1")
                self.assertEqual(result["route"], "LOCAL")
        self.assertEqual(len(local.calls), 4)
        self.assertEqual(remote.calls, [])

    def test_local_aggregate_reports_missing_column_and_never_falls_back(self):
        self.publish(columns=("order_id", "status"), all_columns=False)
        local, remote = FakeLocalEngine(), FakeRemote()
        router = QueryRouter(self.store, self.coverage, remote, local=local)
        with self.assertRaisesRegex(CoverageError, "amount"):
            router.execute("SELECT sum(amount) FROM main.silver.orders", route="LOCAL",
                           source_version="version-1")
        self.assertEqual(local.calls, [])
        self.assertEqual(remote.calls, [])

    def test_auto_reports_remote_unavailable_when_local_coverage_is_insufficient(self):
        self.publish(columns=("order_id", "status"), all_columns=False)
        local = FakeLocalEngine()
        router = QueryRouter(self.store, self.coverage, None, local=local)
        with self.assertRaisesRegex(UnavailableError, "Remote execution is required") as raised:
            router.execute("SELECT amount FROM main.silver.orders", route="AUTO",
                           source_version="version-1")
        self.assertEqual(raised.exception.code, "PROVIDER_NOT_CONFIGURED")
        self.assertEqual(local.calls, [])

    def test_auto_route_uses_only_the_selected_workspace_local_copy(self):
        self.publish(workspace_identity="workspace-a")
        remote = FakeRemote()
        local = FakeLocalEngine()
        router = QueryRouter(self.store, self.coverage, remote, local=local)
        sql = "SELECT order_id FROM main.silver.orders"
        local_result = router.execute(sql, route="AUTO", workspace_identity="workspace-a")
        remote_result = router.execute(sql, route="AUTO", workspace_identity="workspace-b",
                                        warehouse_id="wh-test")
        self.assertEqual(local_result["route"], "LOCAL")
        self.assertEqual(remote_result["route"], "DATABRICKS")
        self.assertEqual(len(remote.calls), 1)

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
        self.assertEqual(self.store.query_recent(limit=1)[0]["source_objects"], [self.source])

    def test_local_parser_extracts_query_requirements_but_defers_joins_and_ctes(self):
        plan = parse_local_query("SELECT `order_id`, status FROM main.silver.orders WHERE status = 'failed' LIMIT 20")
        self.assertEqual(plan.source_name, self.source)
        self.assertEqual(plan.projection, ("order_id", "status"))
        self.assertEqual(plan.limit, 20)
        self.assertEqual(plan.requirements.required_columns, ("order_id", "status"))
        aggregate = parse_local_query(
            "SELECT status, count(*) FROM main.silver.orders GROUP BY status ORDER BY status LIMIT 10")
        self.assertEqual(aggregate.requirements.aggregates, ("COUNT",))
        self.assertEqual(aggregate.requirements.grouping, ("status",))
        self.assertEqual(aggregate.requirements.ordering, ("status",))
        self.assertEqual(aggregate.requirements.required_columns, ("status",))
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

    def test_all_rows_plan_has_no_implicit_remote_or_sql_limit(self):
        plan = plan_materialization(workspace_identity="workspace-hash", source_name=self.source,
                                    projection=["*"], full_table_confirmed=True)
        self.assertIsNone(plan.max_rows)
        self.assertIsNone(plan.max_bytes)
        self.assertNotIn(" LIMIT ", plan.statement().upper())

    def test_full_table_projection_needs_no_generic_confirmation_but_unsafe_plans_fail(self):
        with self.assertRaises(ValidationError):
            plan_materialization(workspace_identity="w", source_name=self.source,
                                 projection=["order_id; DROP TABLE x"])
        with self.assertRaises(ValidationError):
            plan_materialization(workspace_identity="w", source_name=self.source,
                                 projection=["order_id"], predicate="status = 'x'; DROP TABLE t")
        full_table = plan_materialization(workspace_identity="w", source_name=self.source,
            projection=["*"])
        self.assertEqual(full_table.projection, ("*",))

    def make_transfer_plan(self):
        return plan_materialization(workspace_identity="workspace-hash", source_name=self.source,
            projection=["order_id", "status"], source_version="version-1")

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
        self.assertEqual(self.coverage.current(self.source, "workspace-hash")["manifest"]["operation_id"], plan.operation_id)
        self.assertTrue(self.coverage.covers(parse_local_query(
            "SELECT order_id FROM main.silver.orders"), workspace_identity="workspace-hash").covered)
        rows = self.coverage.list_local_datasets("workspace-hash")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_name"], self.source)
        record = self.store.operation_get(plan.operation_id)
        self.assertEqual(record.state.value, "READY")
        self.assertNotIn("sig=secret", json.dumps(record.as_dict() if hasattr(record, "as_dict") else record.checkpoint))
        self.assertNotIn("sig=secret", json.dumps(self.store.materialization_recent()))
        again = service.run(plan, "warehouse-1", profile="anvil-prod")
        self.assertTrue(again["reused"])
        self.assertEqual(provider.submit_count, 1)

    def test_failed_materialization_retains_checkpoint_and_resumes(self):
        provider = FakeTransferProvider()
        downloader = FakeDownloader(fail_url_always="https://storage.example/chunk-1?sig=secret")
        transfer = MaterializationTransfer(self.paths, self.store, provider,
                                           downloader=downloader, codec=FakeCodec(), sleep=lambda _: None)
        plan = self.make_transfer_plan()
        with self.assertRaises(UnavailableError):
            transfer.run(plan, "warehouse-1")
        failed = self.store.operation_get(plan.operation_id)
        self.assertEqual(failed.state.value, "FAILED")
        self.assertEqual(failed.checkpoint["failure_reason"], "TRANSFER_ERROR")
        self.assertEqual([item["index"] for item in failed.checkpoint["chunks"]], [0])
        staging = self.coverage.dataset_root(self.source, "workspace-hash") / "snapshots" / (
            "." + plan.operation_id + ".partial")
        self.assertTrue(staging.exists())
        self.coverage.list_local_datasets("workspace-hash")
        self.assertTrue(staging.exists(), "Home inventory must preserve resumable chunks")
        with self.assertRaisesRegex(ConflictError, "new materialization"):
            transfer.run(plan, "warehouse-1")

        downloader.fail_url_always = ""
        service = MaterializationService(self.paths, self.store, provider, transfer=transfer)
        result = service.retry(plan.operation_id)
        self.assertEqual(result["state"], "READY")
        self.assertEqual(result["operation_id"], plan.operation_id)
        self.assertEqual(provider.submit_count, 1)
        self.assertEqual(downloader.calls.count("https://storage.example/chunk-0?sig=secret"), 1)

    def test_transient_chunk_failure_retries_only_the_failed_chunk(self):
        provider = FakeTransferProvider()
        downloader = FakeDownloader(fail_url_once="https://storage.example/chunk-1?sig=secret")
        transfer = MaterializationTransfer(self.paths, self.store, provider,
                                           downloader=downloader, codec=FakeCodec(), sleep=lambda _: None)
        result = transfer.run(self.make_transfer_plan(), "warehouse-1")
        self.assertEqual(result["state"], "READY")
        self.assertEqual(downloader.calls.count("https://storage.example/chunk-0?sig=secret"), 1)
        self.assertEqual(downloader.calls.count("https://storage.example/chunk-1?sig=secret"), 2)

    def test_full_4_7m_row_result_and_network_reset_after_seven_chunks(self):
        class LargeProvider(FakeTransferProvider):
            @staticmethod
            def success_response(*, include_first_link):
                result = FakeTransferProvider.success_response(include_first_link=include_first_link)
                result["manifest"].update({"total_chunk_count": 8,
                                           "total_row_count": 4_714_788,
                                           "total_byte_count": 56})
                return result

        class LargeCodec(FakeCodec):
            def write_parquet(self, arrow_file, parquet_file):
                parquet_file.write_bytes(b"parquet:" + arrow_file.read_bytes())
                index = int(arrow_file.stem.split("-")[-1])
                rows = 90_112 if index < 7 else 4_084_004
                return ChunkStats(rows, ("order_id", "status"), "schema-v1")

        provider = LargeProvider()
        downloader = FakeDownloader(fail_url_once="https://storage.example/chunk-7?sig=secret")
        transfer = MaterializationTransfer(self.paths, self.store, provider,
                                           downloader=downloader, codec=LargeCodec(), sleep=lambda _: None)
        plan = plan_materialization(workspace_identity="workspace-hash", source_name=self.source,
                                    projection=["*"], source_version="version-1")
        self.assertIsNone(plan.max_rows)
        self.assertNotIn("LIMIT", plan.statement())
        result = transfer.run(plan, "warehouse-1")
        self.assertEqual(result["rows"], 4_714_788)
        self.assertEqual(self.coverage.current(self.source, "workspace-hash")["manifest"]["rows_mode"], "FULL")
        for index in range(7):
            self.assertEqual(downloader.calls.count(f"https://storage.example/chunk-{index}?sig=secret"), 1)
        self.assertEqual(downloader.calls.count("https://storage.example/chunk-7?sig=secret"), 2)

    def test_expired_remote_result_starts_clean_generation(self):
        provider = FakeTransferProvider()
        downloader = FakeDownloader(fail_url_always="https://storage.example/chunk-1?sig=secret")
        transfer = MaterializationTransfer(self.paths, self.store, provider,
                                           downloader=downloader, codec=FakeCodec(), sleep=lambda _: None)
        plan = self.make_transfer_plan()
        with self.assertRaises(UnavailableError):
            transfer.run(plan, "warehouse-1")
        service = MaterializationService(self.paths, self.store, provider, transfer=transfer)
        provider.status_state = "CLOSED"
        downloader.fail_url_always = ""
        result = service.retry(plan.operation_id)
        self.assertEqual(result["state"], "READY")
        self.assertNotEqual(result["operation_id"], plan.operation_id)
        self.assertEqual(provider.submit_count, 2)
        self.assertEqual(downloader.calls.count("https://storage.example/chunk-0?sig=secret"), 2)

    def test_missing_remote_result_starts_clean_generation(self):
        provider = FakeTransferProvider()
        downloader = FakeDownloader(fail_url_always="https://storage.example/chunk-1?sig=secret")
        transfer = MaterializationTransfer(self.paths, self.store, provider,
                                           downloader=downloader, codec=FakeCodec(), sleep=lambda _: None)
        plan = self.make_transfer_plan()
        with self.assertRaises(UnavailableError):
            transfer.run(plan, "warehouse-1")
        provider.transfer_status = lambda *args, **kwargs: (_ for _ in ()).throw(
            UnavailableError("remote result expired", code="REMOTE_RESULT_EXPIRED"))
        downloader.fail_url_always = ""
        service = MaterializationService(self.paths, self.store, provider, transfer=transfer)
        retry_plan, _payload, _checkpoint = service.prepare_retry(plan.operation_id)
        self.assertNotEqual(retry_plan.operation_id, plan.operation_id)
        stage = self.coverage.dataset_root(self.source, "workspace-hash") / "snapshots" / (
            "." + plan.operation_id + ".partial")
        self.assertFalse(stage.exists())
        self.assertFalse(service.status(plan.operation_id)["resume_available"])

    def test_progress_uses_verified_rows_and_omits_unknown_percentage(self):
        provider = FakeTransferProvider()
        service = MaterializationService(self.paths, self.store, provider)
        plan = self.make_transfer_plan()
        chunks = [{"index": index, "rows": 90_112, "bytes": 21_314_285}
                  for index in range(7)]
        payload = {"plan": plan.as_dict(), "warehouse_id": "warehouse-1"}
        self.store.operation_put(OperationRecord(plan.operation_id, "MATERIALIZATION",
            MaterializationState.RUNNING, payload,
            {"phase": "DOWNLOADING_ARROW", "chunks": chunks,
             "planned_rows": 4_714_788, "total_chunks": 52}, ""))
        status = service.status(plan.operation_id)
        self.assertEqual(status["rows"], 630_784)
        self.assertEqual(status["completed_chunks"], 7)
        self.assertEqual(status["percent"], 13.4)
        self.store.operation_checkpoint_update(plan.operation_id, {"planned_rows": None})
        unknown = service.status(plan.operation_id)
        self.assertIsNone(unknown["percent"])
        self.assertEqual(unknown["rows"], 630_784)

    def test_failed_refresh_keeps_the_previous_current_snapshot(self):
        self.publish(workspace_identity="workspace-hash")
        before = self.coverage.current(self.source, "workspace-hash")["snapshot_id"]
        provider = FakeTransferProvider()
        downloader = FakeDownloader(fail_url_always="https://storage.example/chunk-0?sig=secret")
        service = MaterializationTransfer(self.paths, self.store, provider,
                                          downloader=downloader, codec=FakeCodec(), sleep=lambda _: None)
        plan = self.make_transfer_plan()
        with self.assertRaises(UnavailableError):
            service.run(plan, "warehouse-1")
        self.assertEqual(self.coverage.current(self.source, "workspace-hash")["snapshot_id"], before)

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

    def test_startup_reconciles_every_nonterminal_phase_and_preserves_current(self):
        self.publish(workspace_identity="workspace-hash")
        current_id = self.coverage.current(self.source, "workspace-hash")["snapshot_id"]
        phases = ("QUEUED", "PREPARING", "FETCHING", "WRITING_PARQUET",
                  "VALIDATING", "ACTIVATING")
        root = self.coverage.dataset_root(self.source, "workspace-hash")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        operation_ids = []
        staging_ids = []
        for index, phase in enumerate(phases, start=1):
            operation_id = f"{index:x}" * 64
            plan = self.make_transfer_plan().as_dict()
            plan["operation_id"] = operation_id
            self.store.operation_put(OperationRecord(
                operation_id, "MATERIALIZATION", MaterializationState.RUNNING,
                {"plan": plan, "warehouse_id": "warehouse-1"},
                {"phase": phase, "chunks": [], "worker_instance_id": "old-worker",
                 "worker_pid": 123, "heartbeat_at": now}, ""))
            stage_id = root / "snapshots" / ("." + operation_id + ".partial")
            stage_id.mkdir(parents=True)
            (stage_id / "partial.chunk").write_text("incomplete")
            operation_ids.append(operation_id)
            staging_ids.append(operation_id)
        (root / "dataset-state.json").write_text(json.dumps({
            "version": 1, "current": {"snapshot_id": current_id},
            "previous": None, "staging": staging_ids}))

        MaterializationService(self.paths, self.store, FakeTransferProvider(),
                               transfer=MaterializationTransfer(
                                   self.paths, self.store, FakeTransferProvider(),
                                   downloader=FakeDownloader(), codec=FakeCodec()))

        for operation_id in operation_ids:
            operation = self.store.operation_get(operation_id)
            self.assertEqual(operation.state, MaterializationState.FAILED)
            self.assertEqual(operation.error_code, "SERVICE_RESTARTED")
            self.assertEqual(operation.checkpoint["failure_reason"], "SERVICE_RESTARTED")
            self.assertFalse((root / "snapshots" / ("." + operation_id + ".partial")).exists())
        self.assertEqual(self.coverage.current(self.source, "workspace-hash")["snapshot_id"], current_id)
        self.assertEqual(json.loads((root / "dataset-state.json").read_text())["staging"], [])

    def test_persisted_table_lock_prevents_duplicate_mutations(self):
        provider = FakeTransferProvider()
        service = MaterializationService(self.paths, self.store, provider)
        plan = self.make_transfer_plan()
        first = service.claim_table(plan)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(service.claim_table(plan))
        finally:
            service.release_table(first)
        second = service.claim_table(plan)
        self.assertIsNotNone(second)
        service.release_table(second)


if __name__ == "__main__":
    unittest.main()
