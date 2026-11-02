from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.analytics.errors import IntegrityError, ValidationError
from scripts.analytics.models import (CatalogObject, CatalogObjectType,
                                      KnowledgeItem, MaterializationState,
                                      OperationRecord, QueryRecord, QueryRoute)
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.store import ContextStore, SCHEMA_VERSION, migration_rollback_policy


class AnalyticsContextStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / ".anvil"
        self.paths = AnalyticsPaths.from_root(self.root, create=True)
        self.store = ContextStore(paths=self.paths)

    def test_private_paths_are_outside_managed_config_and_sqlite_uses_wal(self) -> None:
        self.assertEqual(self.paths.database, self.root / "analytics" / "context.db")
        self.assertEqual(self.paths.workspace, self.root / "workspaces" / "analytics")
        self.assertNotIn("opencode", self.paths.database.parts)
        self.assertEqual(stat.S_IMODE(self.paths.state.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.paths.database.stat().st_mode), 0o600)
        with self.store._connect() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], SCHEMA_VERSION)

    def test_catalog_hydration_progress_is_persisted_and_bounded(self) -> None:
        self.store.catalog_hydration_set("tree", "", "LOADING", phase="tables",
                                          progress_current=4, progress_total=9)
        progress = self.store.catalog_hydration_get("tree")
        self.assertEqual((progress["state"], progress["phase"], progress["progress_current"],
                          progress["progress_total"]), ("LOADING", "tables", 4, 9))
        summary = self.store.catalog_hydration_summary()
        self.assertEqual(summary["tree_hydration"]["progress_current"], 4)
        self.assertEqual(summary["scope_hydration_states"]["tree"]["LOADING"], 1)
        with self.assertRaises(ValidationError):
            self.store.catalog_hydration_set("tree", "", "LOADING", progress_current=10,
                                              progress_total=9)

    def test_v2_catalog_hydration_schema_migrates_to_v4_and_preserves_rows(self) -> None:
        legacy_paths = AnalyticsPaths.from_root(Path(self.temp.name) / "legacy-anvil", create=True)
        with sqlite3.connect(legacy_paths.database) as db:
            db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(1,'old'),(2,'old')")
            db.execute("CREATE TABLE catalog_hydration(scope TEXT NOT NULL,parent_name TEXT NOT NULL DEFAULT '',state TEXT NOT NULL,error_code TEXT NOT NULL DEFAULT '',error_message TEXT NOT NULL DEFAULT '',attempts INTEGER NOT NULL DEFAULT 0,object_count INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,PRIMARY KEY(scope,parent_name))")
        migrated = ContextStore(paths=legacy_paths)
        with migrated._connect() as db:
            self.assertEqual(db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 4)
            columns = {row[1] for row in db.execute("PRAGMA table_info(catalog_hydration)")}
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"phase", "progress_current", "progress_total"} <= columns)
        self.assertIn("local_datasets", tables)
        self.assertEqual(migration_rollback_policy(3, 4)["policy"], "BACKUP_RESTORE_REQUIRED")

    def test_local_dataset_metadata_is_unique_and_round_trips(self) -> None:
        dataset = {"dataset_id": "a" * 64, "workspace_identity": "workspace-hash",
                   "source_name": "main.silver.orders", "columns_mode": "SELECTED",
                   "selected_columns": ["order_id", "status"], "rows_mode": "FILTERED",
                   "predicate": "status = 'failed'", "schema_identity": "schema-hash",
                   "source_version": "v-10", "freshness": "CURRENT",
                   "state": "LOCAL_CURRENT", "current_generation": "b" * 64,
                   "previous_generation": "c" * 64,
                   "previous_expires_at": "2026-11-03T12:00:00Z", "row_count": 14,
                   "size_bytes": 4096}
        self.store.local_dataset_put(dataset)
        self.store.local_dataset_put({**dataset, "row_count": 15})
        value = self.store.local_dataset_get("a" * 64)
        self.assertEqual(value["selected_columns"], ["order_id", "status"])
        self.assertEqual(value["row_count"], 15)
        self.assertEqual(self.store.local_dataset_recent(workspace_identity="workspace-hash"), [value])
        self.store.local_dataset_delete("a" * 64)
        self.assertIsNone(self.store.local_dataset_get("a" * 64))

    def test_catalog_knowledge_query_and_operations_are_durable(self) -> None:
        self.assertEqual(self.store.catalog_upsert([
            CatalogObject("main.sales.orders", CatalogObjectType.TABLE,
                          workspace_id="ws-test", parent_name="main.sales",
                          comment="orders", columns=({"name": "id", "type": "BIGINT"},))
        ]), 1)
        self.assertEqual(self.store.catalog_list(parent="main.sales")[0]["columns"][0]["name"], "id")

        knowledge = KnowledgeItem("finding", "main.sales.orders", "IDs are unique",
                                  confidence=0.95, tags=("quality",))
        first_id = self.store.knowledge_add(knowledge)
        self.assertEqual(self.store.knowledge_add(knowledge), first_id)
        self.assertEqual(self.store.knowledge_recent(subject="main.sales.orders")[0]["content"],
                         "IDs are unique")

        query_id = self.store.query_record(QueryRecord(
            "select count(*) from main.sales.orders", "fp-1", QueryRoute.LOCAL,
            "SUCCEEDED", latency_ms=11, row_count=5, byte_count=40,
            source_objects=("main.sales.orders",)))
        self.assertGreater(query_id, 0)
        self.assertEqual(self.store.query_recent()[0]["source_objects"], ["main.sales.orders"])

        operation = OperationRecord("op-1", "materialize", MaterializationState.PAUSED,
                                    {"table": "main.sales.orders"}, {"page": 2})
        self.store.operation_put(operation)
        self.assertEqual(self.store.operation_get("op-1"), operation)
        self.assertEqual(self.store.operation_recent()[0]["payload"]["table"], "main.sales.orders")
        self.store.investigation_put("inv-1", "Refund trend", "completed",
                                     "Refunds rose in mobile orders.", "session-1")
        investigation = self.store.investigation_recent()[0]
        self.assertEqual(investigation["state"], "COMPLETED")
        self.assertEqual(investigation["summary"], "Refunds rose in mobile orders.")

        reopened = ContextStore(paths=self.paths)
        self.assertEqual(reopened.knowledge_recent()[0]["id"], first_id)
        self.assertEqual(reopened.query_recent()[0]["id"], query_id)

    def test_catalog_search_reaches_nested_cached_tables_and_bounds_results(self) -> None:
        self.store.catalog_upsert([
            CatalogObject("main", CatalogObjectType.CATALOG),
            CatalogObject("main.sales", CatalogObjectType.SCHEMA, parent_name="main"),
            CatalogObject("main.sales.orders", CatalogObjectType.TABLE, parent_name="main.sales",
                          comment="monthly order facts"),
            CatalogObject("main.sales.orders_archive", CatalogObjectType.TABLE, parent_name="main.sales"),
            CatalogObject("other.sales.orders", CatalogObjectType.TABLE, parent_name="other.sales"),
        ])
        rows, truncated = self.store.catalog_search("orders", limit=1)
        self.assertEqual([row["full_name"] for row in rows], ["main.sales.orders"])
        self.assertTrue(truncated)
        scoped, scoped_truncated = self.store.catalog_search("orders", parent="main", limit=10)
        self.assertEqual({row["full_name"] for row in scoped},
                         {"main.sales.orders", "main.sales.orders_archive"})
        self.assertFalse(scoped_truncated)
        literal, _ = self.store.catalog_search("%", limit=10)
        self.assertEqual(literal, [])

    def test_rejects_symlinked_state_database(self) -> None:
        other = self.root / "analytics" / "outside.db"
        other.write_bytes(b"preserve")
        target = self.root / "analytics" / "linked.db"
        target.symlink_to(other)
        with self.assertRaises(IntegrityError):
            ContextStore(database=target, paths=self.paths)
        self.assertEqual(other.read_bytes(), b"preserve")

        outside = self.root / "analytics" / "outside-wal"
        outside.write_bytes(b"keep")
        (self.paths.database.parent / "context.db-wal").symlink_to(outside)
        with self.assertRaises(IntegrityError):
            ContextStore(paths=self.paths)
        self.assertEqual(outside.read_bytes(), b"keep")

    def test_validation_bounds_and_json_values(self) -> None:
        with self.assertRaises(ValidationError):
            self.store.catalog_list(limit=0)
        with self.assertRaises(ValidationError):
            self.store.knowledge_add(KnowledgeItem("finding", "subject", "fact", confidence=1.5))
        with self.assertRaises(ValidationError):
            self.store.knowledge_add(KnowledgeItem("finding", "subject", "fact", tags=(object(),)))

    def test_failed_migration_rolls_back_all_schema_changes(self) -> None:
        database = self.root / "analytics" / "migration-fail.db"
        store = ContextStore.__new__(ContextStore)
        store.paths = self.paths
        store.database = database
        original = store._migration_1

        def fail_after_schema(db):
            original(db)
            raise RuntimeError("injected migration failure")

        store._migration_1 = fail_after_schema
        with self.assertRaises(RuntimeError):
            store._migrate()
        with store._connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, set())


if __name__ == "__main__":
    unittest.main()
