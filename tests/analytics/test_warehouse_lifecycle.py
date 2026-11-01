from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.analytics.databricks import _shared_module


class AnalyticsWarehouseLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dbx = _shared_module()

    def _run(self, initial: str, states: list[str], *, permission: bool = False, timeout: bool = False):
        old_get = self.dbx.get_warehouse
        old_start = self.dbx.start_warehouse
        calls = []
        iterator = iter(states)

        def get(_warehouse_id, _profile, **_kwargs):
            try:
                state = next(iterator)
            except StopIteration:
                state = states[-1]
            return {"warehouse_id": "wh-test", "name": "Analytics", "state": state}

        def start(warehouse_id, profile, **_kwargs):
            calls.append((warehouse_id, profile))
            if permission:
                raise self.dbx.DatabricksError("PERMISSION_DENIED", "private provider error")
            return {}

        self.dbx.get_warehouse = get
        self.dbx.start_warehouse = start
        try:
            if timeout:
                ticks = iter([0])
                with patch("scripts.databricks.time.monotonic", side_effect=lambda: next(ticks, 31)), \
                     patch("scripts.databricks.time.sleep", return_value=None):
                    return self.dbx.ensure_warehouse_running(
                        {"warehouse_id": "wh-test", "name": "Analytics", "state": initial},
                        "anvil-test", start_timeout=30), calls
            with patch("scripts.databricks.time.sleep", return_value=None):
                return self.dbx.ensure_warehouse_running(
                    {"warehouse_id": "wh-test", "name": "Analytics", "state": initial},
                    "anvil-test", start_timeout=30), calls
        finally:
            self.dbx.get_warehouse = old_get
            self.dbx.start_warehouse = old_start

    def test_stopped_warehouse_starts_once_and_waits_until_running(self) -> None:
        result, calls = self._run("STOPPED", ["STARTING", "RUNNING"])
        self.assertEqual(result["state"], "RUNNING")
        self.assertEqual(len(calls), 1)

    def test_starting_warehouse_is_polled_without_duplicate_start(self) -> None:
        result, calls = self._run("STARTING", ["STARTING", "RUNNING"])
        self.assertEqual(result["state"], "RUNNING")
        self.assertEqual(calls, [])

    def test_stopping_warehouse_waits_for_stopped_before_start(self) -> None:
        result, calls = self._run("STOPPING", ["STOPPED", "STARTING", "RUNNING"])
        self.assertEqual(result["state"], "RUNNING")
        self.assertEqual(len(calls), 1)

    def test_permission_failure_is_actionable_and_timeout_is_explicit(self) -> None:
        with self.assertRaises(self.dbx.DatabricksError) as denied:
            self._run("STOPPED", [], permission=True)
        self.assertEqual(denied.exception.category, "WAREHOUSE_START_PERMISSION_DENIED")
        self.assertIn("select another running warehouse", str(denied.exception))
        with self.assertRaises(self.dbx.DatabricksError) as timed_out:
            self._run("STARTING", ["STARTING"], timeout=True)
        self.assertEqual(timed_out.exception.category, "WAREHOUSE_START_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
