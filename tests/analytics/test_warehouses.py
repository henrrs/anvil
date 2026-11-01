from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.analytics.errors import ProviderError
from scripts.analytics.models import MaterializationState, OperationRecord
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.service import AnalyticsService
from scripts.analytics.store import ContextStore


class FakeCompute:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False
        self.items = [
            {"warehouse_id": "wh-running", "name": "Engineering", "state": "RUNNING",
             "warehouse_type": "PRO", "size": "Small", "http_path": "/sql/1.0/warehouses/x",
             "token": "must-not-leak"},
            {"warehouse_id": "wh-stopped", "name": "BI Shared", "state": "STOPPED",
             "warehouse_type": "CLASSIC", "size": "Medium"},
        ]

    def list_sql_warehouses(self, *, profile=None):
        self.calls += 1
        if self.fail:
            raise ProviderError("private provider detail", code="WORKSPACE_UNREACHABLE")
        return {"warehouses": self.items}

    def get_sql_warehouse(self, warehouse_id, *, profile=None):
        return next(item for item in self.items if item["warehouse_id"] == warehouse_id)


class AnalyticsWarehouseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        paths = AnalyticsPaths.from_root(Path(self.temp.name) / ".anvil", create=True)
        self.compute = FakeCompute()
        self.service = AnalyticsService(paths=paths, store=ContextStore(paths=paths), compute=self.compute)
        self.addCleanup(self.service.close)

    def test_warehouse_inventory_is_safe_cached_and_refreshable(self) -> None:
        first = self.service.warehouses()
        second = self.service.warehouses()
        self.assertEqual(self.compute.calls, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "READY")
        self.assertEqual([item["state"] for item in first["warehouses"]], ["RUNNING", "STOPPED"])
        encoded = json.dumps(first)
        self.assertNotIn("http_path", encoded)
        self.assertNotIn("must-not-leak", encoded)
        refreshed = self.service.warehouses(refresh=True)
        self.assertEqual(self.compute.calls, 2)
        self.assertEqual(refreshed["status"], "READY")

    def test_provider_failure_returns_cached_stale_inventory_without_raw_error(self) -> None:
        self.service.warehouses()
        self.compute.fail = True
        result = self.service.warehouses(refresh=True)
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(len(result["warehouses"]), 2)
        self.assertEqual(result["error"]["code"], "WORKSPACE_UNREACHABLE")
        self.assertNotIn("private provider detail", json.dumps(result))

    def test_provider_failure_without_cache_is_degraded_and_local_friendly(self) -> None:
        self.compute.fail = True
        result = self.service.warehouses(refresh=True)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["warehouses"], [])
        self.assertIn("local datasets and catalog remain available", result["error"]["message"])

    def test_single_warehouse_metadata_is_sanitized(self) -> None:
        result = self.service.get_warehouse("wh-running")
        self.assertEqual(result["warehouse_id"], "wh-running")
        self.assertNotIn("http_path", result)
        self.assertNotIn("token", result)

    def test_home_operation_projection_omits_provider_and_profile_payload(self) -> None:
        self.service.store.operation_put(OperationRecord(
            "op-safe", "MATERIALIZATION", MaterializationState.RUNNING,
            {"profile": "private-profile", "warehouse_id": "private-id",
             "plan": {"source_name": "main.finance.transactions"}}, {"phase": "RUNNING"}))
        result = self.service.operations_recent()
        self.assertEqual(result[0]["source_name"], "main.finance.transactions")
        self.assertNotIn("payload", result[0])
        self.assertNotIn("private-profile", json.dumps(result))
        self.assertNotIn("private-id", json.dumps(result))

    def test_home_operation_projection_omits_provider_and_profile_payload(self) -> None:
        self.service.store.operation_put(OperationRecord(
            "op-safe", "MATERIALIZATION", MaterializationState.RUNNING,
            {"profile": "private-profile", "warehouse_id": "private-id",
             "plan": {"source_name": "main.finance.transactions"}}, {"phase": "RUNNING"}))
        result = self.service.operations_recent()
        self.assertEqual(result[0]["source_name"], "main.finance.transactions")
        self.assertNotIn("payload", result[0])
        self.assertNotIn("private-profile", json.dumps(result))
        self.assertNotIn("private-id", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
