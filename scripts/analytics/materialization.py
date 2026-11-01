"""User-intent boundary for planning, starting and resuming local snapshots."""

from __future__ import annotations

import threading
from typing import Any

from .errors import ConflictError, ValidationError
from .models import MaterializationState, OperationRecord
from .paths import AnalyticsPaths
from .planner import AcquisitionPlan, plan_materialization
from .store import ContextStore
from .transfer import MaterializationTransfer, TransferProvider


class MaterializationService:
    """Coordinates an explicit acquisition request without exposing transfer links."""

    def __init__(self, paths: AnalyticsPaths, store: ContextStore,
                 provider: TransferProvider, *, transfer: MaterializationTransfer | None = None) -> None:
        self.paths, self.store, self.provider = paths, store, provider
        self.transfer = transfer or MaterializationTransfer(paths, store, provider)
        self._cancel_events: dict[str, threading.Event] = {}
        self._guard = threading.Lock()

    def plan(self, *, workspace_identity: str, source_name: str,
             projection: list[str] | tuple[str, ...], predicate: str = "",
             source_version: str = "", max_rows: int = 100_000,
             max_bytes: int = 512 * 1024 * 1024,
             estimated_bytes: int | None = None,
             full_table_confirmed: bool = False,
             force_refresh: bool = False) -> AcquisitionPlan:
        return plan_materialization(workspace_identity=workspace_identity,
                                    source_name=source_name, projection=projection,
                                    predicate=predicate, source_version=source_version,
                                    max_rows=max_rows, max_bytes=max_bytes,
                                    estimated_bytes=estimated_bytes,
                                    full_table_confirmed=full_table_confirmed,
                                    force_refresh=force_refresh)

    def run(self, plan: AcquisitionPlan, warehouse_id: str, *, profile: str | None = None,
            principal: str = "", timeout: int = 1800,
            progress: Any | None = None) -> dict[str, Any]:
        event = threading.Event()
        with self._guard:
            existing = self._cancel_events.get(plan.operation_id)
            if existing and not existing.is_set():
                raise ConflictError("This materialization is already running", code="OPERATION_ALREADY_RUNNING")
            self._cancel_events[plan.operation_id] = event
        try:
            return self.transfer.run(plan, warehouse_id, profile=profile,
                                     principal=principal, timeout=timeout,
                                     cancel_requested=event.is_set, progress=progress)
        finally:
            with self._guard:
                if self._cancel_events.get(plan.operation_id) is event:
                    self._cancel_events.pop(plan.operation_id, None)

    def resume(self, operation_id: str, *, progress: Any | None = None) -> dict[str, Any]:
        operation = self.store.operation_get(operation_id)
        if operation is None or operation.kind != "MATERIALIZATION":
            raise ValidationError("Materialization operation was not found")
        if operation.state in {MaterializationState.READY, MaterializationState.CANCELLED}:
            return self.status(operation_id)
        plan_value = operation.payload.get("plan")
        if not isinstance(plan_value, dict):
            raise ConflictError("Saved materialization plan is unavailable", code="OPERATION_STATE_INVALID")
        try:
            plan = AcquisitionPlan(
                str(plan_value["operation_id"]), str(plan_value["workspace_identity"]),
                str(plan_value["source_name"]), str(plan_value["source_version"]),
                tuple(plan_value["projection"]), str(plan_value["predicate"]),
                int(plan_value["max_rows"]), int(plan_value["max_bytes"]),
                plan_value.get("estimated_bytes"), bool(plan_value.get("force_refresh")))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConflictError("Saved materialization plan is invalid", code="OPERATION_STATE_INVALID") from exc
        if plan.operation_id != operation_id:
            raise ConflictError("Saved materialization identity does not match its operation",
                                code="OPERATION_STATE_INVALID")
        warehouse_id = operation.payload.get("warehouse_id")
        if not isinstance(warehouse_id, str) or not warehouse_id:
            raise ConflictError("Saved SQL warehouse selection is unavailable", code="OPERATION_STATE_INVALID")
        return self.run(plan, warehouse_id, profile=operation.payload.get("profile") or None,
                        principal=operation.payload.get("principal", ""), progress=progress)

    def cancel(self, operation_id: str) -> dict[str, Any]:
        operation = self.store.operation_get(operation_id)
        if operation is None or operation.kind != "MATERIALIZATION":
            raise ValidationError("Materialization operation was not found")
        if operation.state in {MaterializationState.READY, MaterializationState.FAILED,
                               MaterializationState.CANCELLED}:
            return self.status(operation_id)
        with self._guard:
            event = self._cancel_events.get(operation_id)
            if event:
                event.set()
        statement_id = operation.checkpoint.get("statement_id")
        if statement_id:
            self.provider.transfer_cancel(statement_id,
                                          profile=operation.payload.get("profile") or None,
                                          timeout=30)
        self.store.operation_put(OperationRecord(
            operation.operation_id, operation.kind, MaterializationState.CANCELLED,
            operation.payload, {**operation.checkpoint, "phase": "CANCELLED"}, ""))
        return self.status(operation_id)

    def status(self, operation_id: str) -> dict[str, Any]:
        operation = self.store.operation_get(operation_id)
        if operation is None or operation.kind != "MATERIALIZATION":
            raise ValidationError("Materialization operation was not found")
        chunks = operation.checkpoint.get("chunks", [])
        chunks = chunks if isinstance(chunks, list) else []
        snapshot_id = operation.checkpoint.get("snapshot_id", "")
        materialization = self.store.materialization_get(snapshot_id) if snapshot_id else None
        return {"operation_id": operation.operation_id, "state": operation.state.value,
                "phase": operation.checkpoint.get("phase", ""),
                "completed_chunks": len(chunks),
                "rows": sum(int(item.get("rows", 0)) for item in chunks if isinstance(item, dict)),
                "bytes": sum(int(item.get("bytes", 0)) for item in chunks if isinstance(item, dict)),
                "error_code": operation.error_code,
                "snapshot_id": snapshot_id,
                "materialization": ({"source_name": materialization["source_name"],
                                     "source_version": materialization["source_version"],
                                     "state": materialization["state"],
                                     "columns": materialization["columns"],
                                     "byte_count": materialization["byte_count"]}
                                    if materialization else None)}

    def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [self.status(row["operation_id"]) for row in self.store.operation_recent(limit=limit)
                if row.get("kind") == "MATERIALIZATION"]
