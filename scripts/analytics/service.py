"""Application services shared by the loopback API and offline contracts."""

from __future__ import annotations

import getpass
import json
import logging
import os
import re
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .catalog import CatalogService
from .context import ContextResolver
from .coverage import CoverageRegistry, dataset_identity, schema_identity
from .databricks import ComputePort, SharedDatabricksCatalogClient, _shared_module
from .errors import (AnalyticsError, ConflictError, CoverageError, ProviderError,
                     UnavailableError, ValidationError)
from .materialization import MaterializationService
from .models import MaterializationState, OperationRecord, QueryRoute
from .opencode import create_adapter
from .paths import AnalyticsPaths
from .planner import QueryPlan, ensure_read_only, parse_local_query
from .query import DuckDBLocalEngine, QueryRouter
from .runtime import AnalyticsRuntimeManager
from .sessions import AnalyticsSessionManager
from .store import ContextStore

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_CHAT_CHARS = 16_000
MAX_ACTIVE_CONTEXT_CHARS = 10_000
WAREHOUSE_CACHE_TTL_SECONDS = 60
WAREHOUSE_STATES = {"RUNNING", "STOPPED", "STARTING", "STOPPING", "DELETED", "UNAVAILABLE", "UNKNOWN"}
@dataclass(frozen=True)
class AnalyticsModelPolicy:
    logical_model: str = "anvil-analytics"
    display_name: str = "GPT 6 Luna"
    provider_id: str = "opencode"
    model_id: str = "gpt-6-luna"
    fallback: str = "NONE"

    def selector(self) -> dict[str, str]:
        return {"providerID": self.provider_id, "modelID": self.model_id}

    def as_dict(self) -> dict[str, str]:
        return {"logical_model": self.logical_model, "display_name": self.display_name,
                **self.selector(), "fallback": self.fallback}


ANALYTICS_MODEL_POLICY = AnalyticsModelPolicy()
_LOG = logging.getLogger(__name__)


def _analytics_event(level: int, event: str, **details: Any) -> None:
    _LOG.log(level, json.dumps({"event": event, **details}, sort_keys=True,
                               separators=(",", ":"), default=str))


class AnalyticsService:
    """Feature-level composition; the traditional Anvil core does not import it."""

    def __init__(self, *, paths: AnalyticsPaths | None = None,
                 store: ContextStore | None = None,
                 databricks: SharedDatabricksCatalogClient | None = None,
                 compute: ComputePort | None = None,
                 catalog: CatalogService | None = None,
                 coverage: CoverageRegistry | None = None,
                 query: QueryRouter | None = None,
                 runtime: AnalyticsRuntimeManager | None = None,
                 sessions: AnalyticsSessionManager | None = None,
                 materializations: MaterializationService | None = None,
                 identity: Callable[[], dict[str, Any]] | None = None,
                 host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 web_root: Path | None = None,
                 max_workers: int = 2) -> None:
        self.paths = paths or AnalyticsPaths.discover(create=True)
        self.store = store or ContextStore(paths=self.paths)
        self.databricks = databricks or SharedDatabricksCatalogClient()
        self.compute = compute or (self.databricks if hasattr(self.databricks, "list_sql_warehouses") else None)
        self.catalog = catalog or CatalogService(self.store, self.databricks)
        self.coverage = coverage or CoverageRegistry(self.paths, self.store)
        self.query = query or QueryRouter(self.store, self.coverage, self.databricks)
        self.runtime = runtime or AnalyticsRuntimeManager(self.paths)
        self.sessions = sessions or AnalyticsSessionManager(self.runtime, self.store, paths=self.paths)
        self.materializations = materializations or MaterializationService(
            self.paths, self.store, self.databricks)
        self.identity = identity
        self.host = host
        self.port = int(port)
        self.web_root = Path(web_root) if web_root else self._default_web_root()
        self._executor = ThreadPoolExecutor(max_workers=max(1, min(max_workers, 4)),
                                            thread_name_prefix="anvil-analytics")
        self._jobs: dict[str, Future[Any]] = {}
        self._job_guard = threading.Lock()
        self._chat_lock = threading.Lock()
        self._runtime_start_lock = threading.Lock()
        self._runtime_start_state = "NOT_STARTED"
        self._runtime_start_error: dict[str, str] | None = None
        self._warehouse_guard = threading.Lock()
        self._warehouse_cache: list[dict[str, Any]] = []
        self._warehouse_cache_at = 0.0
        self._warehouse_cache_refreshed_at: str | None = None
        self._catalog_hydration_future: Future[Any] | None = None
        self._catalog_hydration_guard = threading.Lock()
        self._closed = threading.Event()

    @staticmethod
    def _default_web_root() -> Path:
        return Path(__file__).resolve().parents[2] / "web" / "analytics"

    @property
    def url(self) -> str:
        return f"http://anvil.localhost:{self.port}"

    def close(self) -> None:
        self._closed.set()
        self._executor.shutdown(wait=False, cancel_futures=False)

    def initialize_runtime(self) -> dict[str, Any]:
        """Warm the dedicated runtime and canonical session without blocking UI startup."""
        if not self._runtime_start_lock.acquire(blocking=False):
            return self.status()
        self._runtime_start_state = "STARTING"
        self._runtime_start_error = None
        try:
            self.sessions.ensure_canonical()
            self._runtime_start_state = "READY"
        except AnalyticsError as exc:
            self._runtime_start_state = "DEGRADED"
            self._runtime_start_error = {"code": exc.code, "message": str(exc)[:500]}
        except Exception:
            self._runtime_start_state = "DEGRADED"
            self._runtime_start_error = {
                "code": "RUNTIME_INITIALIZATION_FAILED",
                "message": "The Analytics AI runtime could not be initialized.",
            }
        finally:
            self._runtime_start_lock.release()
        return self.status()

    def warehouses(self, *, refresh: bool = False) -> dict[str, Any]:
        """Return a short-lived, safe warehouse inventory through the shared provider."""
        now = time.monotonic()
        with self._warehouse_guard:
            if (not refresh and self._warehouse_cache_at
                    and now - self._warehouse_cache_at < WAREHOUSE_CACHE_TTL_SECONDS):
                status = "READY" if self._warehouse_cache else "EMPTY"
                return self._warehouse_result(self._warehouse_cache, status, None,
                                              refreshed_at=self._warehouse_cache_refreshed_at)
            if self.compute is None:
                return self._warehouse_result([], "DEGRADED", {
                    "code": "WAREHOUSE_DISCOVERY_UNAVAILABLE",
                    "message": "SQL Warehouse discovery is not available. Local datasets and the catalog remain usable.",
                })
            try:
                payload = self.compute.list_sql_warehouses()
                raw_items = payload.get("warehouses", []) if isinstance(payload, dict) else []
                if not isinstance(raw_items, list):
                    raise ProviderError("Databricks returned an invalid SQL warehouse list",
                                        code="WAREHOUSE_RESPONSE_INVALID", retryable=False)
                items = []
                seen = set()
                for item in raw_items[:1000]:
                    if not isinstance(item, dict):
                        continue
                    safe_item = self._safe_warehouse(item)
                    if not safe_item:
                        continue
                    if safe_item["warehouse_id"] in seen:
                        continue
                    seen.add(safe_item["warehouse_id"])
                    items.append(safe_item)
                self._warehouse_cache = items
                self._warehouse_cache_at = time.monotonic()
                self._warehouse_cache_refreshed_at = datetime.now(timezone.utc).isoformat()
                result_status = "READY" if items else "EMPTY"
                return self._warehouse_result(items, result_status, None,
                                              refreshed_at=self._warehouse_cache_refreshed_at)
            except AnalyticsError as exc:
                category = str(exc.code)
                if category not in {"PROVIDER_NOT_INSTALLED", "AUTH_REQUIRED", "AUTH_INVALID",
                                    "PERMISSION_DENIED", "WORKSPACE_NETWORK_TIMEOUT",
                                    "WORKSPACE_UNREACHABLE", "CLI_PROCESS_TIMEOUT", "SDK_PROCESS_TIMEOUT",
                                    "WORKSPACE_NOT_CONFIGURED", "PROFILE_NOT_CONFIGURED",
                                    "WAREHOUSE_RESPONSE_INVALID", "PROVIDER_UNHEALTHY"}:
                    category = "PROVIDER_UNHEALTHY"
                message = "Unable to refresh SQL Warehouses. Your local datasets and catalog remain available."
                return self._warehouse_result(self._warehouse_cache,
                    "STALE" if self._warehouse_cache else "DEGRADED",
                    {"code": category, "message": message},
                    refreshed_at=self._warehouse_cache_refreshed_at)
            except Exception:
                return self._warehouse_result(self._warehouse_cache,
                    "STALE" if self._warehouse_cache else "DEGRADED",
                    {"code": "PROVIDER_UNHEALTHY",
                     "message": "Unable to refresh SQL Warehouses. Your local datasets and catalog remain available."},
                    refreshed_at=self._warehouse_cache_refreshed_at)

    def get_warehouse(self, warehouse_id: str) -> dict[str, Any]:
        if (not isinstance(warehouse_id, str) or not warehouse_id or len(warehouse_id) > 256
                or any(ord(char) < 32 for char in warehouse_id)):
            raise ValidationError("A valid SQL warehouse is required")
        if self.compute is None or not hasattr(self.compute, "get_sql_warehouse"):
            raise UnavailableError("SQL Warehouse details are not available through the shared Databricks capability",
                                   code="WAREHOUSE_DISCOVERY_UNAVAILABLE", retryable=False)
        try:
            item = self.compute.get_sql_warehouse(warehouse_id)
        except AnalyticsError:
            raise
        if not isinstance(item, dict):
            raise ProviderError("Databricks returned invalid SQL warehouse metadata",
                                code="WAREHOUSE_RESPONSE_INVALID", retryable=False)
        safe_item = self._safe_warehouse(item)
        if not safe_item:
            raise ProviderError("Databricks returned invalid SQL warehouse metadata",
                                code="WAREHOUSE_RESPONSE_INVALID", retryable=False)
        return safe_item

    def hydrate_catalog_tree(self) -> dict[str, Any]:
        """Refresh roots, then schemas and table/view metadata without reading table rows."""
        with self._catalog_hydration_guard:
            future = self._catalog_hydration_future
            if future and not future.done():
                return {"status": "LOADING"}
            self.store.catalog_hydration_set("tree", "", "PENDING", phase="catalogs",
                                              progress_current=0, progress_total=0)
            _LOG.info("analytics_catalog_event %s", json.dumps({"event": "catalog_hydration_started"},
                                                                   sort_keys=True, separators=(",", ":")))
            try:
                self._catalog_hydration_future = self._executor.submit(self._hydrate_catalog_tree)
            except RuntimeError:
                self.store.catalog_hydration_set("tree", "", "FAILED", error_code="SERVICE_STOPPING",
                                                  error_message="The Analytics service is stopping.")
                return {"status": "FAILED", "error": "SERVICE_STOPPING"}
            return {"status": "PENDING"}

    def _hydrate_catalog_tree(self) -> dict[str, Any]:
        try:
            self.store.catalog_hydration_set("tree", "", "LOADING", phase="catalogs",
                                              progress_current=0, progress_total=0)
            root = self.catalog.catalogs(refresh=True, limit=200)
            if root.get("status") in {"BROWSE_ONLY", "FAILED"}:
                code = str(root.get("error") or "CATALOG_DISCOVERY_FAILED")
                self.store.catalog_hydration_set("tree", "", "FAILED", error_code=code,
                                                  error_message="Catalog roots could not be refreshed.")
                return {"status": "FAILED", "error": code}
            catalogs = self._catalog_rows("CATALOG", "")
            if not catalogs:
                self.store.catalog_hydration_set("tree", "", "EMPTY", phase="complete",
                                                  progress_current=0, progress_total=0)
                self._log_catalog_hydration("catalog_hydration_completed", status="EMPTY",
                                            catalogs=0, schemas=0, tables=0, views=0)
                return {"status": "EMPTY"}
            total = len(catalogs)
            completed = 0
            self.store.catalog_hydration_set("tree", "", "LOADING", phase="schemas",
                                              progress_current=completed, progress_total=total)
            for catalog in catalogs:
                if self._closed.is_set():
                    self.store.catalog_hydration_set("tree", "", "PENDING", error_code="CANCELLED",
                                                      error_message="Catalog refresh will resume on the next service start.",
                                                      progress_current=completed, progress_total=total)
                    return {"status": "CANCELLED"}
                catalog_name = str(catalog.get("full_name") or "")
                if not catalog_name:
                    completed += 1
                    continue
                schemas_result = self.catalog.schemas(catalog_name, refresh=True, limit=200)
                schemas = self._catalog_rows("SCHEMA", catalog_name) if schemas_result.get("status") not in {
                    "BROWSE_ONLY", "FAILED"} else []
                completed += 1
                total += len(schemas)
                self.store.catalog_hydration_set("tree", "", "LOADING", phase="tables",
                                                  progress_current=completed, progress_total=total)
                for schema in schemas:
                    if self._closed.is_set():
                        self.store.catalog_hydration_set("tree", "", "PENDING", error_code="CANCELLED",
                                                          error_message="Catalog refresh will resume on the next service start.",
                                                          progress_current=completed, progress_total=total)
                        return {"status": "CANCELLED"}
                    parts = str(schema.get("full_name") or "").split(".")
                    if len(parts) == 2:
                        self.catalog.tables(parts[0], parts[1], refresh=True, limit=200)
                    completed += 1
                    self.store.catalog_hydration_set("tree", "", "LOADING", phase="tables",
                                                      progress_current=completed, progress_total=total)
            summary = self.store.catalog_hydration_summary()
            partial = any(scope_states.get("FAILED", 0)
                          for scope, scope_states in summary.get("scope_hydration_states", {}).items()
                          if scope in {"schemas", "tables"})
            self.store.catalog_hydration_set("tree", "", "READY", phase="complete",
                                              error_code="PARTIAL_DISCOVERY" if partial else "",
                                              progress_current=completed, progress_total=total)
            self._log_catalog_hydration("catalog_hydration_completed", status="READY",
                                        catalogs=summary["catalogs"], schemas=summary["schemas"],
                                        tables=summary["tables"], views=summary["views"], partial=partial)
            return {"status": "READY", "partial": partial}
        except Exception:
            self.store.catalog_hydration_set("tree", "", "FAILED", error_code="CATALOG_HYDRATION_FAILED",
                                              error_message="Catalog metadata refresh failed; cached metadata remains available.")
            self._log_catalog_hydration("catalog_hydration_failed", status="FAILED",
                                        reason_code="CATALOG_HYDRATION_FAILED")
            return {"status": "FAILED", "error": "CATALOG_HYDRATION_FAILED"}

    @staticmethod
    def _log_catalog_hydration(event: str, **details: Any) -> None:
        _LOG.info("analytics_catalog_event %s", json.dumps({"event": event, **details},
                                                            sort_keys=True, separators=(",", ":")))

    def _catalog_rows(self, object_type: str, parent: str) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.store.catalog_list(parent=parent, object_type=object_type,
                                           limit=2000, offset=offset)
            values.extend(page)
            if len(page) < 2000:
                return values
            offset += len(page)

    @staticmethod
    def _safe_warehouse(item: dict[str, Any]) -> dict[str, Any] | None:
        warehouse_id = item.get("warehouse_id") or item.get("id")
        if not isinstance(warehouse_id, str) or not warehouse_id or len(warehouse_id) > 256 \
                or any(ord(char) < 32 for char in warehouse_id):
            return None
        state = str(item.get("state") or "UNKNOWN").upper()
        if state not in WAREHOUSE_STATES:
            state = "UNKNOWN"
        name = item.get("name")
        return {
            "warehouse_id": warehouse_id,
            "name": str(name)[:160] if isinstance(name, str) and name.strip() else "Unnamed SQL warehouse",
            "state": state,
            "warehouse_type": str(item.get("warehouse_type") or item.get("type") or "")[:80],
            "size": str(item.get("size") or "")[:80],
        }

    @staticmethod
    def _warehouse_result(items: list[dict[str, Any]], status: str,
                          error: dict[str, str] | None, *,
                          refreshed_at: str | None = None) -> dict[str, Any]:
        return {"status": status, "warehouses": [dict(item) for item in items],
                "refreshed_at": refreshed_at, "error": error}

    def me(self) -> dict[str, Any]:
        current_identity = self.identity() if self.identity else {}
        if not isinstance(current_identity, dict):
            current_identity = {}
        profile = self._profile_selection()
        username = (current_identity.get("display_name") or current_identity.get("user_name")
                    or current_identity.get("userName") or getpass.getuser())
        return {"name": str(username)[:160], "identity_source": "databricks" if current_identity else "os",
                "workspace": profile.get("host", ""), "profile": profile.get("name", ""),
                "databricks_configured": bool(profile.get("name")),
                "url": self.url, "status": self.status()}

    def status(self) -> dict[str, Any]:
        profile = self._profile_selection()
        runtime_state: dict[str, Any] = {}
        runtime_status = "NOT_CONFIGURED"
        canonical = "NOT_CREATED"
        if self.paths.runtime.is_file() and not self.paths.runtime.is_symlink():
            try:
                import json
                runtime_state = json.loads(self.paths.runtime.read_text(encoding="utf-8"))
                generation = int(runtime_state.get("runtime_generation") or runtime_state.get("generation") or 0)
                base_url = str(runtime_state.get("base_url") or "")
                if generation in {1, 2} and base_url:
                    adapter = create_adapter(generation, base_url, self.paths.workspace, timeout=3)
                    runtime_status = "READY" if adapter.health() else "DEGRADED"
                else:
                    runtime_status = "DEGRADED"
                canonical = "PRESENT" if runtime_state.get("canonical_session_id") else "NOT_CREATED"
            except (OSError, ValueError, AnalyticsError):
                runtime_status = "FAILED"
                canonical = "UNKNOWN"
        if self._runtime_start_state == "STARTING":
            runtime_status = "STARTING"
        elif self._runtime_start_state == "DEGRADED":
            runtime_status = "DEGRADED"
        elif self._runtime_start_state == "READY" and runtime_status == "NOT_CONFIGURED":
            runtime_status = "READY"
        catalog_page = self.catalog.catalogs(refresh=False, limit=200)
        catalog_cache = catalog_page.get("items", [])
        catalog_summary = self.store.catalog_hydration_summary()
        catalog_hydration = catalog_page.get("hydration", {})
        local_engine = DuckDBLocalEngine()
        try:
            from .transfer import PyArrowChunkCodec
            arrow_available = PyArrowChunkCodec().available
        except Exception:
            arrow_available = False
        try:
            local_bytes = self._data_bytes()
        except OSError:
            local_bytes = 0
        service_state = {"status": "READY", "pid": os.getpid()}
        duckdb_status = {"status": "READY" if local_engine.available else "DEGRADED",
                         "reason_code": None if local_engine.available else "DEPENDENCY_MISSING",
                         "message": None if local_engine.available else "DuckDB is missing from the Analytics runtime."}
        pyarrow_status = {"status": "READY" if arrow_available else "DEGRADED",
                          "reason_code": None if arrow_available else "DEPENDENCY_MISSING",
                          "message": None if arrow_available else "PyArrow is missing from the Analytics runtime."}
        canonical_status = "NOT_CREATED"
        if runtime_status == "STARTING":
            canonical_status = "RECOVERING"
        elif runtime_status in {"DEGRADED", "FAILED", "NOT_CONFIGURED"}:
            canonical_status = "UNAVAILABLE"
        elif runtime_state.get("canonical_session_id"):
            try:
                adapter = create_adapter(int(runtime_state.get("runtime_generation") or runtime_state.get("generation") or 0),
                                         str(runtime_state.get("base_url") or ""), self.paths.workspace, timeout=3)
                session = adapter.get_session(str(runtime_state["canonical_session_id"]))
                canonical_status = "READY" if session and session.get("title") == "anvil-global-analytics" else "RECOVERING"
            except (AnalyticsError, ValueError, TypeError):
                canonical_status = "RECOVERING"
        databricks_workspace = ("READY" if self._warehouse_cache_refreshed_at and
                                self._warehouse_cache_at and time.monotonic() - self._warehouse_cache_at < WAREHOUSE_CACHE_TTL_SECONDS
                                else "NOT_CHECKED" if profile.get("name") else "NOT_CONFIGURED")
        return {
            "service": service_state,
            "url": self.url,
            "model_policy": ANALYTICS_MODEL_POLICY.as_dict(),
            "databricks": {"status": databricks_workspace,
                           "configuration": "READY" if profile.get("name") else "NOT_CONFIGURED",
                           "authentication": "NOT_CHECKED", "workspace": databricks_workspace,
                           "profile": profile.get("name", ""), "host": profile.get("host", "")},
            "opencode": {"status": runtime_status, "generation": runtime_state.get("runtime_generation") or
                        runtime_state.get("generation"), "canonical_session": canonical_status,
                        **({"error": self._runtime_start_error} if self._runtime_start_error else {})},
            "runtime": {"status": runtime_status, "generation": runtime_state.get("runtime_generation") or
                        runtime_state.get("generation"), "canonical_session": canonical_status,
                        **({"error": self._runtime_start_error} if self._runtime_start_error else {})},
            "canonical_session": {"status": canonical_status,
                                  **({"reason_code": self._runtime_start_error.get("code")} if self._runtime_start_error else {})},
            "duckdb": duckdb_status,
            "pyarrow": pyarrow_status,
            "catalog": {"status": ("READY" if catalog_summary["catalogs"] else
                                     catalog_hydration.get("state", "NOT_LOADED")),
                        **catalog_summary, "cached_root_items": len(catalog_cache)},
            "local": {"duckdb": duckdb_status["status"],
                      "pyarrow": pyarrow_status["status"],
                      "storage_bytes": local_bytes},
            "capabilities": {"catalog": "AVAILABLE" if catalog_cache else
                             ("READY" if profile.get("name") else "DEGRADED"),
                             "sql_remote": "READY" if profile.get("name") else "DEGRADED",
                             "sql_local": "READY" if local_engine.available else "DEGRADED",
                             "ask_anvil": "READY" if runtime_status == "READY" else "DEGRADED",
                             "materialization": "READY" if arrow_available else "DEGRADED"},
        }

    def runtime_status(self) -> dict[str, Any]:
        return self.status()

    def catalogs(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self.catalog.catalogs(limit=limit, offset=offset)

    def schemas(self, catalog_name: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        result = self.catalog.schemas(catalog_name, limit=limit, offset=offset)
        if result.get("status") == "NOT_LOADED":
            return self.catalog.schemas(catalog_name, refresh=True, limit=limit, offset=offset)
        return result

    def tables(self, catalog_name: str, schema_name: str, *,
               limit: int = 100, offset: int = 0) -> dict[str, Any]:
        result = self.catalog.tables(catalog_name, schema_name, limit=limit, offset=offset)
        if result.get("status") == "NOT_LOADED":
            return self.catalog.tables(catalog_name, schema_name, refresh=True, limit=limit, offset=offset)
        return result

    def search_catalog(self, query: str, *, parent: str = "", limit: int = 100) -> dict[str, Any]:
        term = query.strip().casefold()
        if len(term) > 256 or len(parent) > 768:
            raise ValidationError("Catalog search text exceeds its limit")
        if not term:
            raise ValidationError("Enter a catalog search term")
        bounded_limit = max(1, min(limit, 200))
        matches, truncated = self.store.catalog_search(term, parent=parent, limit=bounded_limit)
        return {"status": "CACHED", "parent": parent, "items": matches,
                "truncated": truncated}

    def table(self, full_name: str, *, refresh: bool = False) -> dict[str, Any]:
        return self.catalog.describe(full_name, refresh=refresh)

    def preview(self, full_name: str, warehouse_id: str, *, limit: int = 10,
                profile: str | None = None) -> dict[str, Any]:
        del profile
        return self.catalog.preview(full_name, warehouse_id, limit=limit)

    def refresh_catalog(self, *, scope: str, catalog_name: str = "",
                        schema_name: str = "", limit: int = 100,
                        offset: int = 0) -> dict[str, Any]:
        return self.catalog.refresh_scope(scope, catalog_name=catalog_name, schema_name=schema_name,
                                          limit=limit, offset=offset)

    def query_explain(self, sql: str) -> dict[str, Any]:
        normalized = ensure_read_only(sql)
        plan = parse_local_query(normalized)
        local = DuckDBLocalEngine()
        if plan is None:
            return {"route": "DATABRICKS", "local_coverage": False,
                    "reason": "This SQL shape is not in Anvil's provable local subset."}
        workspace_identity = self._workspace_identity()
        remote_schema, source_version = self._table_coverage_metadata(plan.source_name)
        decision = self.coverage.covers(plan, workspace_identity=workspace_identity,
                                        remote_schema=remote_schema, source_version=source_version)
        if decision.covered and local.available:
            return {"route": "LOCAL", "local_coverage": True,
                    "snapshot_id": decision.snapshot_id, "reason": decision.reason}
        return {"route": "DATABRICKS", "local_coverage": decision.covered,
                "snapshot_id": decision.snapshot_id,
                "reason": (decision.reason if not decision.covered else
                           "Local coverage exists, but DuckDB is unavailable.")}

    def run_query(self, sql: str, *, route: str = "AUTO", warehouse_id: str = "",
                  profile: str | None = None, timeout: int = 120) -> dict[str, Any]:
        plan = parse_local_query(ensure_read_only(sql))
        remote_schema, source_version = (self._table_coverage_metadata(plan.source_name)
                                         if plan else (None, None))
        return self.query.execute(sql, route=route, warehouse_id=warehouse_id or None,
                                  profile=profile, timeout=timeout,
                                  workspace_identity=self._workspace_identity(),
                                  remote_schema=remote_schema, source_version=source_version)

    def query_history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.query_recent(limit=max(1, min(limit, 100)))

    def operations_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        items = []
        for item in self.store.operation_recent(limit=max(1, min(limit, 100))):
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
            items.append({"operation_id": str(item.get("operation_id") or "")[:256],
                          "kind": str(item.get("kind") or "")[:40],
                          "state": str(item.get("state") or "")[:40],
                          "source_name": str(plan.get("source_name") or "")[:768],
                          "updated_at": str(item.get("updated_at") or "")[:40]})
        return items

    def investigations_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [{"title": str(item.get("title") or "")[:160],
                 "state": str(item.get("state") or "")[:40],
                 "summary": str(item.get("summary") or "")[:1000],
                 "updated_at": str(item.get("updated_at") or "")[:40]}
                for item in self.store.investigation_recent(limit=max(1, min(limit, 100)))]

    def profile_table(self, full_name: str, warehouse_id: str, *, limit: int = 100) -> dict[str, Any]:
        sample = self.preview(full_name, warehouse_id, limit=max(1, min(limit, 100)))
        if sample.get("status") != "READY":
            return {"status": sample.get("status", "BROWSE_ONLY"),
                    "error": sample.get("error", "PREVIEW_UNAVAILABLE")}
        columns = sample.get("columns")
        rows = sample.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ProviderError("The shared Databricks preview returned an invalid sample",
                                code="PREVIEW_RESULT_INVALID", retryable=False)
        profiled = []
        for index, name in enumerate(columns[:100]):
            values = [row[index] if isinstance(row, (list, tuple)) and index < len(row) else None
                      for row in rows[:100]]
            present = [value for value in values if value is not None]
            distinct = {json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
                        for value in present}
            result: dict[str, Any] = {"name": str(name), "null_count": len(values) - len(present),
                                      "distinct_in_sample": len(distinct)}
            if present and (all(isinstance(value, (int, float)) and not isinstance(value, bool)
                                for value in present) or all(isinstance(value, str) for value in present)):
                try:
                    result["min"] = min(present)
                    result["max"] = max(present)
                except (TypeError, ValueError):
                    pass
            profiled.append(result)
        return {"status": "READY", "source_name": full_name,
                "sample_rows": len(rows[:100]), "sample_truncated": bool(sample.get("truncated")),
                "columns": profiled}

    def get_lineage(self, full_name: str, warehouse_id: str, *, limit: int = 100) -> dict[str, Any]:
        self.catalog._validate_full_name(full_name)
        if not warehouse_id or len(warehouse_id) > 256:
            raise ValidationError("Choose a SQL warehouse to query Databricks lineage")
        literal = full_name.replace("'", "''")
        statement = ("SELECT event_time, entity_type, entity_id, source_table_full_name, "
                     "target_table_full_name, source_type, target_type "
                     "FROM system.access.table_lineage "
                     f"WHERE source_table_full_name = '{literal}' OR target_table_full_name = '{literal}' "
                     "ORDER BY event_time DESC LIMIT " + str(max(1, min(limit, 100))))
        result = self.run_query(statement, route="DATABRICKS", warehouse_id=warehouse_id, timeout=120)
        return {"status": "READY", **result}

    def compare_remote_local(self, sql: str, warehouse_id: str, *,
                             profile: str | None = None) -> dict[str, Any]:
        local = self.run_query(sql, route="LOCAL")
        remote = self.run_query(sql, route="DATABRICKS", warehouse_id=warehouse_id, profile=profile)
        local_columns = [str(value).casefold() for value in local.get("columns", [])]
        remote_columns = [str(value).casefold() for value in remote.get("columns", [])]
        if local.get("truncated") or remote.get("truncated"):
            equivalent: bool | None = None
            different_rows = None
        elif local_columns != remote_columns:
            equivalent = False
            different_rows = None
        else:
            local_counts = Counter(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                                   for row in local.get("rows", []))
            remote_counts = Counter(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                                    for row in remote.get("rows", []))
            different_rows = sum((local_counts - remote_counts).values()) + sum((remote_counts - local_counts).values())
            equivalent = different_rows == 0
        return {"status": "COMPARABLE" if equivalent is not None else "INCONCLUSIVE",
                "equivalent": equivalent, "different_rows": different_rows,
                "local_rows": len(local.get("rows", [])),
                "remote_rows": len(remote.get("rows", [])),
                "columns_match": local_columns == remote_columns,
                "reason": ("Results match within the bounded result window." if equivalent is True else
                           "Results differ within the bounded result window." if equivalent is False else
                           "At least one result was truncated, so equality could not be proven.")}

    def local_coverage(self, full_name: str, *, sql: str = "") -> dict[str, Any]:
        workspace_identity = self._workspace_identity()
        if sql:
            plan = parse_local_query(ensure_read_only(sql))
            if plan is None or plan.source_name.casefold() != full_name.casefold():
                return {"covered": False, "reason": "SQL cannot be proven against one local source."}
            remote_schema, source_version = self._table_coverage_metadata(full_name)
            decision = self.coverage.covers(plan, workspace_identity=workspace_identity,
                                            remote_schema=remote_schema, source_version=source_version)
            return {"covered": decision.covered, "reason": decision.reason,
                    "missing_columns": list(decision.missing_columns),
                    "snapshot_id": decision.snapshot_id, "state": decision.state,
                    "reasons": list(decision.reasons)}
        snapshot = self.coverage.current(full_name, workspace_identity)
        if not snapshot:
            return {"covered": False, "reason": "No local copy exists for this table.",
                    "state": "NOT_COVERED", "freshness": "UNKNOWN"}
        manifest = snapshot["manifest"]
        columns_mode = str(manifest.get("columns_mode") or
                           ("ALL" if manifest.get("all_columns") else "SELECTED")).upper()
        selected_columns = manifest.get("selected_columns")
        if not isinstance(selected_columns, list):
            selected_columns = [] if columns_mode == "ALL" else manifest.get("columns", [])
        coverage_columns = (("*",) if columns_mode == "ALL" else
                            tuple(str(item) for item in manifest.get("columns", []) if isinstance(item, str)))
        remote_schema, source_version = self._table_coverage_metadata(full_name)
        own_coverage = self.coverage.covers(
            QueryPlan("", full_name, coverage_columns, str(manifest.get("predicate") or "")),
            workspace_identity=workspace_identity, remote_schema=remote_schema,
            source_version=source_version)
        freshness = ("STALE_SCHEMA" if "schema_changed" in own_coverage.reasons else
                     "STALE_DATA" if "source_version_changed" in own_coverage.reasons else
                     "CURRENT" if own_coverage.state == "FULLY_COVERED" else "UNKNOWN")
        return {"covered": own_coverage.covered, "state": own_coverage.state,
                "freshness": freshness, "reason": own_coverage.reason,
                "reasons": list(own_coverage.reasons), "snapshot_id": snapshot["snapshot_id"],
                "dataset_id": dataset_identity(workspace_identity, full_name),
                "columns": (manifest.get("columns", []) if columns_mode == "ALL" else selected_columns),
                "predicate": manifest.get("predicate", ""),
                "source_version": manifest.get("source_version", ""),
                "rows": manifest.get("row_count", 0),
                "bytes": manifest.get("parquet_bytes", manifest.get("bytes", 0)),
                "updated_at": manifest.get("created_at", ""),
                "columns_mode": columns_mode,
                "rows_mode": manifest.get("rows_mode") or
                    ("FILTERED" if manifest.get("predicate") else "FULL"),
                "workspace_identity": manifest.get("workspace_identity", "")}

    def local_datasets(self, *, limit: int = 100) -> list[dict[str, Any]]:
        workspace_identity = self._workspace_identity()
        if not workspace_identity:
            return []
        return self.coverage.list_local_datasets(workspace_identity, limit=limit)

    def delete_local_dataset(self, dataset_id: str) -> dict[str, Any]:
        # Serialize removal with materialization submission so a planned job
        # cannot appear after the running-operation check but before deletion.
        with self._job_guard:
            return self._delete_local_dataset_locked(dataset_id)

    def _delete_local_dataset_locked(self, dataset_id: str) -> dict[str, Any]:
        workspace_identity = self._workspace_identity()
        if not workspace_identity:
            raise UnavailableError("Select the Databricks workspace that owns this local copy",
                                   code="PROFILE_NOT_SELECTED", retryable=False)
        if not isinstance(dataset_id, str) or len(dataset_id) != 64 or any(
                char not in "0123456789abcdef" for char in dataset_id):
            raise ValidationError("Local dataset identity is invalid")
        record = self.store.local_dataset_get(dataset_id)
        if not record or record["workspace_identity"] != workspace_identity:
            raise ValidationError("Local dataset was not found in the selected workspace")
        source_name = str(record["source_name"])
        for operation in self.store.operation_recent(limit=500):
            payload = operation.get("payload") if isinstance(operation.get("payload"), dict) else {}
            plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
            if (plan.get("source_name") == source_name and
                    plan.get("workspace_identity") == workspace_identity and
                    operation.get("state") in {"PLANNED", "RUNNING", "VALIDATING"}):
                raise ConflictError("A local copy cannot be removed while its update is running",
                                    code="DATASET_UPDATE_RUNNING")
        active = [operation_id for operation_id, future in self._jobs.items()
                  if not future.done()]
        for operation_id in active:
            operation = self.store.operation_get(operation_id)
            plan = operation.payload.get("plan") if operation and isinstance(operation.payload, dict) else {}
            if (isinstance(plan, dict) and plan.get("source_name") == source_name and
                    plan.get("workspace_identity") == workspace_identity):
                raise ConflictError("A local copy cannot be removed while its update is running",
                                    code="DATASET_UPDATE_RUNNING")
        roots = {self.coverage.dataset_root(source_name, workspace_identity),
                 self.coverage.dataset_root(source_name)}
        from .coverage import dataset_lock, dataset_state
        removed = []
        for root in roots:
            if not root.exists() and not root.is_symlink():
                continue
            with dataset_lock(root, exclusive=True):
                state = dataset_state(root)
                snapshot_ids = set()
                for key in ("current", "previous"):
                    item = state.get(key)
                    if isinstance(item, dict) and re.fullmatch(r"[a-f0-9]{64}", str(item.get("snapshot_id") or "")):
                        snapshot_ids.add(str(item["snapshot_id"]))
                staging_ids = state.get("staging") if isinstance(state.get("staging"), list) else []
                snapshots_dir = root / "snapshots"
                if snapshots_dir.exists() and (snapshots_dir.is_symlink() or not snapshots_dir.is_dir()):
                    raise ValidationError("Local dataset snapshot path is unsafe")
                if snapshots_dir.is_dir():
                    for directory in snapshots_dir.iterdir():
                        if not re.fullmatch(r"[a-f0-9]{64}", directory.name):
                            continue
                        manifest_path = directory / "manifest.json"
                        if directory.is_symlink() or not directory.is_dir() or manifest_path.is_symlink() or not manifest_path.is_file():
                            continue
                        manifest = self.coverage._read_json(manifest_path, maximum_bytes=2 * 1024 * 1024)
                        if (manifest.get("state") == "READY" and manifest.get("snapshot_id") == directory.name
                                and manifest.get("source_name") == source_name
                                and manifest.get("workspace_identity") == workspace_identity):
                            snapshot_ids.add(directory.name)
                for snapshot_id in snapshot_ids:
                    directory = snapshots_dir / snapshot_id
                    if directory.is_symlink() or not directory.is_dir():
                        continue
                    manifest_path = directory / "manifest.json"
                    if manifest_path.is_symlink() or not manifest_path.is_file():
                        continue
                    manifest = self.coverage._read_json(manifest_path, maximum_bytes=2 * 1024 * 1024)
                    if (manifest.get("snapshot_id") == snapshot_id and
                            manifest.get("source_name") == source_name and
                            manifest.get("state") == "READY" and
                            manifest.get("workspace_identity") == workspace_identity):
                        shutil.rmtree(directory)
                        removed.append(snapshot_id)
                for operation_id in staging_ids:
                    if not isinstance(operation_id, str) or not re.fullmatch(r"[a-f0-9]{64}", operation_id):
                        continue
                    operation = self.store.operation_get(operation_id)
                    plan = operation.payload.get("plan") if operation and isinstance(operation.payload, dict) else {}
                    if (isinstance(plan, dict) and plan.get("source_name") == source_name and
                            plan.get("workspace_identity") == workspace_identity):
                        if operation and operation.state.value not in {"READY", "FAILED", "CANCELLED"}:
                            raise ConflictError("A local copy cannot be removed while its update is active",
                                                code="DATASET_UPDATE_RUNNING")
                        partial = snapshots_dir / ("." + operation_id + ".partial")
                        if partial.is_symlink():
                            raise ValidationError("Local dataset staging path is unsafe")
                        if partial.is_dir():
                            shutil.rmtree(partial)
                if snapshots_dir.is_dir():
                    for partial in snapshots_dir.iterdir():
                        match = re.fullmatch(r"\.([a-f0-9]{64})\.partial", partial.name)
                        if not match:
                            continue
                        operation_id = match.group(1)
                        operation = self.store.operation_get(operation_id)
                        plan = (operation.payload.get("plan") if operation and
                                isinstance(operation.payload, dict) else {})
                        if (not isinstance(plan, dict) or plan.get("source_name") != source_name or
                                plan.get("workspace_identity") != workspace_identity):
                            continue
                        if operation.state.value not in {"READY", "FAILED", "CANCELLED"}:
                            raise ConflictError("A local copy cannot be removed while its update is active",
                                                code="DATASET_UPDATE_RUNNING")
                        if partial.is_symlink():
                            raise ValidationError("Local dataset staging path is unsafe")
                        if partial.is_dir():
                            shutil.rmtree(partial)
                for pointer in (root / "dataset-state.json", root / "current.json"):
                    if pointer.is_symlink():
                        raise ValidationError("Local dataset pointer is unsafe")
                    if pointer.exists():
                        pointer.unlink()
        self.store.local_dataset_delete(dataset_id)
        self.store.materialization_delete(removed)
        _analytics_event(logging.INFO, "local_dataset_removed", dataset_id=dataset_id,
                         source_name=source_name, generation_count=len(set(removed)))
        return {"dataset_id": dataset_id, "source_name": source_name,
                "deleted": True, "removed_generations": len(set(removed))}

    def submit_materialization(self, body: dict[str, Any]) -> dict[str, Any]:
        table_name = str(body.get("source_name") or "")
        columns = body.get("columns")
        if not isinstance(columns, list) or any(not isinstance(value, str) for value in columns):
            raise ValidationError("Materialization columns must be a list of names")
        profile = body.get("profile")
        warehouse_id = body.get("warehouse_id")
        if profile is not None and (not isinstance(profile, str) or len(profile) > 128):
            raise ValidationError("Databricks profile name is invalid")
        selected_profile = self._profile_selection()
        if not selected_profile.get("name") or not selected_profile.get("host"):
            raise UnavailableError("Select an Anvil-owned Databricks profile before materializing data",
                                   code="PROFILE_NOT_SELECTED", retryable=False)
        if profile and profile != selected_profile["name"]:
            raise ValidationError("Analytics only uses the currently selected Anvil-owned Databricks profile")
        profile = selected_profile["name"]
        metadata = self.catalog.describe(table_name, refresh=False).get("object")
        if not isinstance(metadata, dict):
            raise ValidationError("Refresh table metadata before materializing local data")
        source_version = str(metadata.get("source_updated_at") or metadata.get("updated_at") or "")
        workspace_identity = self._workspace_identity()
        predicate = str(body.get("predicate") or "")
        max_rows = self._integer(body.get("max_rows", 100_000), "row bound", 1, 1_000_000)
        max_bytes = self._integer(body.get("max_bytes", 512 * 1024 * 1024), "byte bound",
                                  1024 * 1024, 1024 * 1024 * 1024)
        full_table_confirmed = body.get("full_table_confirmed") is True
        force_refresh = body.get("force_refresh") is True
        remote_schema = metadata.get("columns") if isinstance(metadata.get("columns"), list) else None
        typed_schema = (remote_schema if remote_schema and all(
            isinstance(item, dict) and item.get("name") and
            (item.get("type_text") or item.get("type_name") or item.get("type"))
            for item in remote_schema) else None)
        remote_schema_identity = schema_identity(typed_schema) if typed_schema else ""
        plan = self.materializations.plan(
            workspace_identity=workspace_identity,
            source_name=table_name, projection=columns, predicate=predicate,
            source_version=source_version,
            max_rows=max_rows, max_bytes=max_bytes,
            estimated_bytes=None,
            full_table_confirmed=full_table_confirmed, force_refresh=force_refresh,
            source_schema_identity=remote_schema_identity)
        selected_schema_identity = ""
        if typed_schema and plan.projection != ("*",):
            columns_by_name = {str(item["name"]).casefold(): item for item in typed_schema}
            selected_schema = [columns_by_name.get(name.casefold()) for name in plan.projection]
            if all(item is not None for item in selected_schema):
                selected_schema_identity = schema_identity(selected_schema)
        plan = replace(plan, selected_schema_identity=selected_schema_identity)
        coverage_plan = self.coverage.plan_materialization(
            workspace_identity=workspace_identity, source_name=table_name,
            projection=plan.intent_projection or plan.projection, predicate=plan.predicate,
            source_version=source_version, remote_schema=remote_schema,
            rows_mode="FILTERED" if predicate.strip() else "FULL")
        if not force_refresh and not coverage_plan.remote_transfer_required:
            _analytics_event(logging.INFO, "local_dataset_reused", source_name=table_name,
                             action=coverage_plan.action, workspace_identity=workspace_identity)
            return {"operation_id": coverage_plan.snapshot_id, "state": "READY",
                    "snapshot_id": coverage_plan.snapshot_id, "reused": True,
                    "action": coverage_plan.action, "message": coverage_plan.reason}
        if not self.materializations.transfer.codec.available:
            raise UnavailableError("PyArrow is not installed; Parquet materialization is unavailable",
                                   code="PYARROW_MISSING", retryable=False)
        if warehouse_id is not None and (not isinstance(warehouse_id, str) or len(warehouse_id) > 256):
            raise ValidationError("SQL warehouse selection is invalid")
        if not warehouse_id:
            inventory = self.warehouses(refresh=True)
            candidates = inventory.get("warehouses", []) if isinstance(inventory, dict) else []
            selected_warehouse = next((item for item in candidates
                                       if item.get("state") == "RUNNING"), None)
            if selected_warehouse is None:
                selected_warehouse = next((item for item in candidates
                                           if item.get("state") == "STOPPED"), None)
            if selected_warehouse is None:
                raise UnavailableError("No available SQL Warehouse can run this explicit local copy request",
                                       code="WAREHOUSE_UNAVAILABLE", retryable=False)
            warehouse_id = str(selected_warehouse["warehouse_id"])
        with self._job_guard:
            existing = self.store.operation_get(plan.operation_id)
            if existing and existing.state in {MaterializationState.READY, MaterializationState.RUNNING,
                                               MaterializationState.PLANNED}:
                return self.materializations.status(plan.operation_id)
            principal = self.me()["name"]
            operation_payload = {"plan": plan.as_dict(), "warehouse_id": warehouse_id,
                                 "profile": profile or "", "principal": principal}
            self.store.operation_put(OperationRecord(plan.operation_id, "MATERIALIZATION",
                                                      MaterializationState.PLANNED,
                                                      operation_payload, {"chunks": [], "phase": "PLANNED"}))
            future = self._jobs.get(plan.operation_id)
            if future and not future.done():
                return self.materializations.status(plan.operation_id)
            self._jobs[plan.operation_id] = self._executor.submit(
                self.materializations.run, plan, warehouse_id, profile=profile,
                principal=principal)
        _analytics_event(logging.INFO, "local_dataset_rematerialization_started",
                         source_name=table_name, action=coverage_plan.action,
                         workspace_identity=workspace_identity)
        return self.materializations.status(plan.operation_id)

    def materialization(self, operation_id: str) -> dict[str, Any]:
        return self.materializations.status(operation_id)

    def materializations_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.materializations.recent(limit=limit)

    def cancel_materialization(self, operation_id: str) -> dict[str, Any]:
        return self.materializations.cancel(operation_id)

    def resume_materialization(self, operation_id: str) -> dict[str, Any]:
        with self._job_guard:
            current = self._jobs.get(operation_id)
            if current and not current.done():
                return self.materializations.status(operation_id)
            self._jobs[operation_id] = self._executor.submit(self.materializations.resume, operation_id)
        return self.materializations.status(operation_id)

    def ask_anvil(self, prompt: str, *, context: dict[str, Any] | None = None,
                  deep_investigation: bool = False,
                  event: Callable[[str, dict[str, Any]], None] | None = None,
                  timeout: int = 300) -> dict[str, Any]:
        question = prompt.strip()
        if not question or len(question) > MAX_CHAT_CHARS:
            raise ValidationError("Ask Anvil requires a question under 16,000 characters")
        if not self._chat_lock.acquire(blocking=False):
            raise ConflictError("Anvil is finishing another Analytics chat response", code="SESSION_BUSY")
        try:
            _analytics_event(logging.INFO, "ask_anvil_request_started",
                             deep_investigation=bool(deep_investigation))
            if event:
                event("status", {"state": "starting", "message": "Preparing the Analytics session"})
            _analytics_event(logging.INFO, "ask_anvil_activity_changed", state="starting")
            canonical = self.sessions.ensure_canonical()
            canonical_id = canonical["session_id"]
            adapter = self.runtime.adapter
            session_id = canonical_id
            task_id = ""
            if deep_investigation:
                task = self.sessions.create_task_session("Analytics investigation")
                session_id = task["session_id"]
                task_id = session_id
            query_context = self._chat_context(context or {})
            persistent = self.sessions.context.rehydration_text()
            full_prompt = ("You are answering from Anvil's global Analytics workspace.\n\n"
                           "Relevant durable context:\n" + persistent + "\n\n"
                           "Current UI context (only use as helpful context; do not assume it is complete):\n"
                           + query_context + "\n\nUser question:\n" + question)
            if event:
                event("status", {"state": "thinking", "message": "Asking Anvil in the canonical Analytics session"})
            _analytics_event(logging.INFO, "ask_anvil_activity_changed", state="thinking")
            _analytics_event(logging.INFO, "analytics_model_resolved",
                             logical_model=ANALYTICS_MODEL_POLICY.logical_model,
                             provider_id=ANALYTICS_MODEL_POLICY.provider_id,
                             model_id=ANALYTICS_MODEL_POLICY.model_id,
                             fallback=ANALYTICS_MODEL_POLICY.fallback)
            result = adapter.prompt(session_id, full_prompt, model=ANALYTICS_MODEL_POLICY.selector())
            if getattr(adapter, "generation", 1) == 2:
                result = adapter.wait_for_response(session_id, timeout=timeout)
            answer = self._assistant_text(result)
            if not answer:
                raise ProviderError("OpenCode returned an empty Analytics response",
                                    code="OPENCODE_RESPONSE_EMPTY", retryable=True)
            answer = answer[:60_000]
            if task_id:
                self.sessions.finish_task_session(task_id, summary=answer[:6000])
                adapter.add_context(canonical_id, "Completed Analytics investigation summary:\n" + answer[:6000])
            if event:
                event("result", {"text": answer, "session": "canonical" if not task_id else "investigation"})
                event("done", {"state": "completed"})
            return {"text": answer, "session": "canonical" if not task_id else "investigation"}
        except AnalyticsError:
            raise
        except Exception as exc:
            raise UnavailableError("Anvil could not complete the Analytics chat request",
                                   code="ASK_ANVIL_FAILED", retryable=True) from exc
        finally:
            self._chat_lock.release()

    def _profile_selection(self) -> dict[str, str]:
        try:
            shared = _shared_module()
            name, host, _profiles = shared.resolve_profile()
            return {"name": name, "host": host}
        except Exception:
            return {}

    def _workspace_identity(self) -> str:
        host = self._profile_selection().get("host", "").strip().rstrip("/").casefold()
        if not host:
            return ""
        import hashlib
        return hashlib.sha256(host.encode("utf-8")).hexdigest()

    def _table_coverage_metadata(self, full_name: str) -> tuple[list[dict[str, Any]] | None, str | None]:
        parts = full_name.split(".")
        if len(parts) != 3:
            return None, None
        cached = next((item for item in self.store.catalog_list(parent=".".join(parts[:2]), limit=2000)
                       if str(item.get("full_name") or "").casefold() == full_name.casefold()), None)
        if not cached:
            return None, None
        columns = cached.get("columns") if isinstance(cached.get("columns"), list) else None
        version = str(cached.get("source_updated_at") or cached.get("updated_at") or "")
        return columns, version or None

    def _data_bytes(self) -> int:
        total = 0
        if not self.paths.datasets.exists() or self.paths.datasets.is_symlink():
            return total
        for path in self.paths.datasets.rglob("*"):
            if path.is_symlink():
                continue
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    @staticmethod
    def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValidationError(f"Materialization {label} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _chat_context(value: dict[str, Any]) -> str:
        allowed: dict[str, Any] = {}
        for key in ("table", "route", "sql"):
            item = value.get(key)
            if isinstance(item, str):
                allowed[key] = item[:4096]
        columns = value.get("columns")
        if isinstance(columns, list):
            allowed["columns"] = [str(item)[:256] for item in columns[:100] if isinstance(item, str)]
        preview = value.get("preview")
        if isinstance(preview, dict) and isinstance(preview.get("columns"), list) and isinstance(preview.get("rows"), list):
            allowed["preview"] = {"columns": preview["columns"][:50],
                                  "rows": preview["rows"][:10]}
        text = json.dumps(allowed, ensure_ascii=False, separators=(",", ":"), default=str)
        return text[:MAX_ACTIVE_CONTEXT_CHARS]

    @staticmethod
    def _assistant_text(message: Any) -> str:
        if not isinstance(message, dict):
            return ""
        parts = message.get("parts")
        if not isinstance(parts, list):
            data = message.get("data")
            parts = data.get("parts") if isinstance(data, dict) else []
        text_parts: list[str] = []
        for part in parts if isinstance(parts, list) else []:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
        if text_parts:
            return "\n".join(text_parts).strip()
        for key in ("text", "content", "message"):
            value = message.get(key)
            if isinstance(value, str):
                return value.strip()
        return ""
