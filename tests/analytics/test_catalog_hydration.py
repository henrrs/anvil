from __future__ import annotations

import threading
import unittest

from scripts.analytics.models import CatalogObject, CatalogObjectType
from scripts.analytics.service import AnalyticsService


class _Store:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = {"": []}
        self.hydration: dict[tuple[str, str], dict] = {}

    def catalog_reconcile(self, parent: str, objects: list[CatalogObject]) -> int:
        self.rows[parent] = [item.as_dict() for item in objects]
        return len(objects)

    def catalog_list(self, *, parent: str = "", object_type=None, limit=500, offset=0):
        return self.rows.get(parent, [])[offset:offset + limit]

    def catalog_hydration_set(self, scope, parent, state, **values):
        self.hydration[(scope, parent)] = {"state": state, **values}

    def catalog_hydration_summary(self):
        return {"catalogs": 1, "schemas": 2, "tables": 2, "views": 1,
                "scope_hydration_states": {"schemas": {"READY": 1}, "tables": {"READY": 1}}}


class _Catalog:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.table_scopes: list[tuple[str, str]] = []
        self.preview_calls = 0

    def catalogs(self, *, refresh, limit):
        self.store.catalog_reconcile("", [CatalogObject("main", CatalogObjectType.CATALOG)])
        return {"status": "READY"}

    def schemas(self, catalog_name, *, refresh, limit):
        schemas = [CatalogObject(f"{catalog_name}.silver", CatalogObjectType.SCHEMA,
                                 parent_name=catalog_name),
                   CatalogObject(f"{catalog_name}.reporting", CatalogObjectType.SCHEMA,
                                 parent_name=catalog_name)]
        self.store.catalog_reconcile(catalog_name, schemas)
        return {"status": "READY", "items": [item.as_dict() for item in schemas]}

    def tables(self, catalog_name, schema_name, *, refresh, limit):
        self.table_scopes.append((catalog_name, schema_name))
        name = "daily" if schema_name == "reporting" else "orders"
        kind = CatalogObjectType.VIEW if schema_name == "reporting" else CatalogObjectType.TABLE
        full_name = f"{catalog_name}.{schema_name}.{name}"
        self.store.catalog_reconcile(f"{catalog_name}.{schema_name}", [
            CatalogObject(full_name, kind, parent_name=f"{catalog_name}.{schema_name}")])
        return {"status": "READY"}


class AnalyticsCatalogHydrationTests(unittest.TestCase):
    def test_tree_hydrates_catalog_schemas_and_table_view_metadata_without_rows(self):
        store = _Store()
        catalog = _Catalog(store)
        service = object.__new__(AnalyticsService)
        service.store = store
        service.catalog = catalog
        service._closed = threading.Event()

        result = service._hydrate_catalog_tree()

        self.assertEqual(result, {"status": "READY", "partial": False})
        self.assertEqual(catalog.table_scopes, [("main", "silver"), ("main", "reporting")])
        self.assertEqual(len(store.rows["main.silver"]), 1)
        self.assertEqual(store.rows["main.reporting"][0]["object_type"], "VIEW")
        progress = store.hydration[("tree", "")]
        self.assertEqual((progress["state"], progress["phase"], progress["progress_current"],
                          progress["progress_total"]), ("READY", "complete", 3, 3))
        self.assertEqual(catalog.preview_calls, 0)

    def test_closed_service_marks_hydration_resumable(self):
        store = _Store()
        catalog = _Catalog(store)
        service = object.__new__(AnalyticsService)
        service.store = store
        service.catalog = catalog
        service._closed = threading.Event()
        service._closed.set()

        result = service._hydrate_catalog_tree()

        self.assertEqual(result["status"], "CANCELLED")
        progress = store.hydration[("tree", "")]
        self.assertEqual(progress["state"], "PENDING")
        self.assertEqual(progress["error_code"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
