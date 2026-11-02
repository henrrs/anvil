from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from scripts.analytics.api import AnalyticsAPI
from scripts.analytics.coverage import dataset_identity, source_key
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.service import AnalyticsService
from scripts.analytics.store import ContextStore


class AnalyticsLocalDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AnalyticsPaths.from_root(Path(self.temp.name) / ".anvil", create=True)
        self.store = ContextStore(paths=self.paths)
        self.service = AnalyticsService(paths=self.paths, store=self.store)
        self.service._profile_selection = lambda: {
            "name": "anvil-test", "host": "https://workspace.example/"}
        self.addCleanup(self.service.close)
        self.api = AnalyticsAPI(self.service)
        self.source = "main.silver.orders"
        self.workspace = hashlib.sha256(b"https://workspace.example").hexdigest()

    def _publish(self, snapshot_id: str, *, previous: dict | None = None) -> Path:
        root = self.paths.datasets / source_key(self.source, self.workspace)
        snapshot = root / "snapshots" / snapshot_id
        snapshot.mkdir(parents=True, exist_ok=True)
        data = snapshot / "part-00000.parquet"
        data.write_bytes(b"parquet-" + snapshot_id.encode())
        manifest = {"state": "READY", "snapshot_id": snapshot_id,
                    "source_name": self.source, "workspace_identity": self.workspace,
                    "source_version": "version-1", "columns": ["order_id", "status"],
                    "all_columns": True, "columns_mode": "ALL", "rows_mode": "FULL",
                    "predicate": "", "complete": True, "row_count": 10,
                    "bytes": data.stat().st_size, "parquet_bytes": data.stat().st_size,
                    "files": [data.name], "file_bytes": {data.name: data.stat().st_size},
                    "file_sha256": {data.name: hashlib.sha256(data.read_bytes()).hexdigest()},
                    "created_at": "2026-11-02T10:00:00Z", "freshness": "CURRENT"}
        (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.store.materialization_put({
            "materialization_id": snapshot_id,
            "source_name": self.source,
            "source_version": "version-1",
            "columns": manifest["columns"],
            "coverage": manifest,
            "state": "READY",
            "files": [data.name],
            "byte_count": data.stat().st_size,
            "principal": "test",
        })
        return snapshot

    def test_home_lists_one_logical_dataset_and_remove_deletes_generations(self) -> None:
        current_id, previous_id = "a" * 64, "b" * 64
        self._publish(current_id)
        self._publish(previous_id)
        root = self.paths.datasets / source_key(self.source, self.workspace)
        previous_expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86_400))
        (root / "dataset-state.json").write_text(json.dumps({
            "version": 1,
            "current": {"snapshot_id": current_id, "published_at": "2026-11-02T10:00:00Z"},
            "previous": {"snapshot_id": previous_id, "expires_at": previous_expires},
            "staging": [],
        }), encoding="utf-8")
        status, payload = self.api.handle("GET", "/api/datasets", {"limit": ["100"]})
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["source_name"], self.source)
        self.assertEqual(payload["items"][0]["snapshot_id"], current_id)

        dataset_id = dataset_identity(self.workspace, self.source)
        status, removed = self.api.handle("DELETE", f"/api/datasets/{dataset_id}", {})
        self.assertEqual(status, 200)
        self.assertTrue(removed["deleted"])
        self.assertFalse((root / "snapshots" / current_id).exists())
        self.assertFalse((root / "snapshots" / previous_id).exists())
        self.assertEqual(self.api.handle("GET", "/api/datasets", {"limit": ["100"]})[1]["items"], [])

    def test_table_coverage_exposes_local_copy_actions_without_generation_ui(self) -> None:
        snapshot_id = "c" * 64
        self._publish(snapshot_id)
        root = self.paths.datasets / source_key(self.source, self.workspace)
        (root / "dataset-state.json").write_text(json.dumps({
            "version": 1,
            "current": {"snapshot_id": snapshot_id, "published_at": "2026-11-02T10:00:00Z"},
            "previous": None,
            "staging": [],
        }), encoding="utf-8")
        self.service._table_coverage_metadata = lambda _name: (None, "")

        status, coverage = self.api.handle(
            "GET", "/api/tables/" + self.source + "/coverage", {})

        self.assertEqual(status, 200)
        self.assertEqual(coverage["dataset_id"], dataset_identity(self.workspace, self.source))
        self.assertEqual(coverage["updated_at"], "2026-11-02T10:00:00Z")
        self.assertEqual(coverage["columns_mode"], "ALL")
        self.assertEqual(coverage["rows_mode"], "FULL")
        self.assertEqual(coverage["freshness"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
