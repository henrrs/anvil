"""Real Parquet certification for a previous-release LocalDataset."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.analytics.coverage import dataset_state, source_key
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.service import AnalyticsService
from scripts.analytics.store import ContextStore


class LegacyPhysicalTests(unittest.TestCase):
    def test_legacy_37_column_snapshot_migrates_and_serves_local_queries(self) -> None:
        try:
            import duckdb  # noqa: F401
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("Run this physical certification with the pinned DuckDB/PyArrow environment")
        count = 468_684
        source = "main.silver.ied_compute_adf"
        workspace = "https://adb-example.azuredatabricks.net"
        workspace_id = hashlib.sha256(workspace.encode()).hexdigest()
        snapshot_id = "b" * 64
        with tempfile.TemporaryDirectory() as temporary:
            paths = AnalyticsPaths.from_root(Path(temporary) / ".anvil", create=True)
            store = ContextStore(paths=paths)
            root = paths.datasets / source_key(source)  # previous-release table-only key
            snapshot = root / "snapshots" / snapshot_id
            snapshot.mkdir(parents=True)
            names = ["row_id", "business_key"] + [f"field_{index:02d}" for index in range(35)]
            fields = [pa.field("row_id", pa.int64()), pa.field("business_key", pa.string())] + [
                pa.field(name, pa.int32()) for name in names[2:]]
            schema = pa.schema(fields)
            table = pa.Table.from_arrays([
                pa.array(range(count), type=pa.int64()),
                pa.array((f"key-{index:07d}" for index in range(count)), type=pa.string()),
                *[pa.nulls(count, type=pa.int32()) for _ in names[2:]],
            ], schema=schema)
            file_path = snapshot / "chunk-000000.parquet"
            pq.write_table(table, file_path, compression="zstd")
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            manifest = {"state": "READY", "snapshot_id": snapshot_id, "source_name": source,
                        "workspace_identity": workspace_id, "source_version": "old-release",
                        "columns": names, "all_columns": True, "predicate": "", "complete": True,
                        "row_count": count, "bytes": file_path.stat().st_size,
                        "parquet_bytes": file_path.stat().st_size, "files": [file_path.name],
                        "file_bytes": {file_path.name: file_path.stat().st_size},
                        "file_sha256": {file_path.name: digest}}
            (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "current.json").write_text(json.dumps({"snapshot_id": snapshot_id}), encoding="utf-8")
            malformed = paths.datasets / ("a" * 64)
            malformed.mkdir()
            (malformed / "dataset-state.json").write_text("[]", encoding="utf-8")
            with patch.object(AnalyticsService, "_profile_selection", return_value={
                "name": "anvil-prod", "host": workspace}):
                service = AnalyticsService(paths=paths, store=store, web_root=Path(temporary))
                try:
                    service._reconciliation_future.result(timeout=30)
                    migrated = dataset_state(root)
                    self.assertEqual(migrated["schema_version"], 2)
                    self.assertTrue((root / "dataset-state.json").is_file())
                    self.assertEqual(migrated["physical_schema"]["snapshot_id"], snapshot_id)
                    self.assertEqual(len(migrated["physical_schema"]["columns"]), 37)
                    self.assertEqual(migrated["physical_schema"]["columns"][0],
                                     {"name": "row_id", "type": "int64", "nullable": True})
                    with patch("pyarrow.parquet.ParquetFile", wraps=pq.ParquetFile) as footer:
                        rows = service.run_query(f"SELECT * FROM {source} LIMIT 100", route="LOCAL")
                        unbounded = service.run_query(f"SELECT * FROM {source}", route="LOCAL")
                        aggregate = service.run_query(f"SELECT count(*) FROM {source}", route="LOCAL")
                    self.assertEqual(footer.call_count, 1,
                                     "unchanged generation schema should be read once per query engine")
                    self.assertEqual(rows["route"], "LOCAL")
                    self.assertEqual(len(rows["columns"]), 37)
                    self.assertEqual(len(rows["rows"]), 100)
                    self.assertEqual(unbounded["route"], "LOCAL")
                    self.assertTrue(unbounded["truncated"])  # query response bound, not acquisition loss
                    self.assertEqual(aggregate["route"], "LOCAL")
                    self.assertEqual(aggregate["rows"][0][0], count)
                    self.assertEqual(store.local_dataset_recent(workspace_identity=workspace_id)[0]["state"], "LOCAL_CURRENT")
                finally:
                    service.close()
