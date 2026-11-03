"""User-intent boundary and restart-safe ownership for local snapshots."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import stat
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage import (LocalCoverageService, atomic_dataset_state, dataset_lock,
                       dataset_state, source_key)
from .errors import ConflictError, IntegrityError, ValidationError
from .models import MaterializationState, OperationRecord
from .paths import AnalyticsPaths
from .planner import AcquisitionPlan, plan_materialization
from .store import ContextStore
from .transfer import MaterializationTransfer, TransferProvider

_LOG = logging.getLogger(__name__)
HEARTBEAT_INTERVAL_SECONDS = 10
LEASE_TIMEOUT_SECONDS = 90
NONTERMINAL_STATES = {"PLANNED", "RUNNING", "PAUSED", "VALIDATING"}
TERMINAL_STATES = {"READY", "FAILED", "CANCELLED"}


class MaterializationService:
    """Coordinates explicit acquisition, leases, recovery and cancellation."""

    def __init__(self, paths: AnalyticsPaths, store: ContextStore,
                 provider: TransferProvider, *, transfer: MaterializationTransfer | None = None) -> None:
        self.paths, self.store, self.provider = paths, store, provider
        self.transfer = transfer or MaterializationTransfer(paths, store, provider)
        self.worker_instance_id = uuid.uuid4().hex
        self._cancel_events: dict[str, threading.Event] = {}
        self._guard = threading.Lock()
        self.reconcile_startup()

    def plan(self, *, workspace_identity: str, source_name: str,
             projection: list[str] | tuple[str, ...], predicate: str = "",
             source_version: str = "", max_rows: int = 100_000,
             max_bytes: int = 512 * 1024 * 1024,
             estimated_bytes: int | None = None,
             full_table_confirmed: bool = False,
             force_refresh: bool = False,
             source_schema_identity: str = "") -> AcquisitionPlan:
        return plan_materialization(workspace_identity=workspace_identity,
                                    source_name=source_name, projection=projection,
                                    predicate=predicate, source_version=source_version,
                                    max_rows=max_rows, max_bytes=max_bytes,
                                    estimated_bytes=estimated_bytes,
                                    full_table_confirmed=full_table_confirmed,
                                    force_refresh=force_refresh,
                                    source_schema_identity=source_schema_identity)

    def claim_table(self, plan: AcquisitionPlan) -> Any | None:
        """Take a process-held lock for the canonical table before creating work."""
        return self.claim_table_for(plan.source_name, plan.workspace_identity)

    def claim_table_for(self, source_name: str, workspace_identity: str) -> Any | None:
        """Take the same process-held lock when mutating or deleting a dataset."""
        if self.paths.datasets.is_symlink():
            raise IntegrityError("Analytics data root must not be a symlink")
        root = self.paths.datasets / source_key(source_name, workspace_identity)
        if root.is_symlink():
            raise IntegrityError("Analytics dataset directory must not be a symlink")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.paths.secure_directory(root)
        lock_path = root / "materialization.lock"
        if lock_path.is_symlink():
            raise IntegrityError("Materialization table lock must not be a symlink")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                             stat.S_IRUSR | stat.S_IWUSR)
        handle = os.fdopen(descriptor, "r+b")
        try:
            os.fchmod(handle.fileno(), stat.S_IRUSR | stat.S_IWUSR)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except BlockingIOError:
            handle.close()
            return None
        except Exception:
            handle.close()
            raise

    @staticmethod
    def release_table(lease: Any | None) -> None:
        if lease is None:
            return
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
        finally:
            lease.close()

    def run(self, plan: AcquisitionPlan, warehouse_id: str, *, profile: str | None = None,
            principal: str = "", timeout: int = 1800,
            progress: Any | None = None, lease: Any | None = None) -> dict[str, Any]:
        acquired_here = lease is None
        if acquired_here:
            lease = self.claim_table(plan)
            if lease is None:
                raise ConflictError("A local materialization is already active for this table",
                                    code="ALREADY_IN_PROGRESS", retryable=True)
        event = threading.Event()
        with self._guard:
            existing = self._cancel_events.get(plan.operation_id)
            if existing and not existing.is_set():
                if acquired_here:
                    self.release_table(lease)
                raise ConflictError("This materialization is already running",
                                    code="OPERATION_ALREADY_RUNNING")
            self._cancel_events[plan.operation_id] = event

        record = self.store.operation_get(plan.operation_id)
        if record and record.state == MaterializationState.READY:
            with self._guard:
                self._cancel_events.pop(plan.operation_id, None)
            self.release_table(lease)
            return self.status(plan.operation_id)
        if record and record.state in {MaterializationState.FAILED, MaterializationState.CANCELLED,
                                       MaterializationState.PAUSED}:
            with self._guard:
                self._cancel_events.pop(plan.operation_id, None)
            self.release_table(lease)
            raise ConflictError("This operation is terminal; retry it as a new materialization",
                                code="OPERATION_NOT_RESUMABLE")

        now = _now()
        payload = (record.payload if record else {
            "plan": plan.as_dict(), "warehouse_id": warehouse_id,
            "profile": profile or "", "principal": principal[:256]})
        checkpoint = dict(record.checkpoint) if record else {"chunks": []}
        checkpoint.update({"phase": "PREPARING", "worker_instance_id": self.worker_instance_id,
                           "worker_pid": os.getpid(), "started_at": checkpoint.get("started_at") or now,
                           "heartbeat_at": now, "failure_reason": ""})
        self.store.operation_put(OperationRecord(plan.operation_id, "MATERIALIZATION",
                                                 MaterializationState.RUNNING, payload, checkpoint, ""))
        stopped = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat_loop,
                                     args=(plan.operation_id, event, stopped),
                                     name="anvil-materialization-heartbeat", daemon=True)
        heartbeat.start()
        try:
            return self.transfer.run(plan, warehouse_id, profile=profile,
                                     principal=principal, timeout=timeout,
                                     cancel_requested=event.is_set, progress=progress,
                                     worker_instance_id=self.worker_instance_id)
        except Exception as exc:
            current = self.store.operation_get(plan.operation_id)
            if current and current.state not in {MaterializationState.READY,
                                                 MaterializationState.FAILED,
                                                 MaterializationState.CANCELLED}:
                code = str(getattr(exc, "code", "MATERIALIZATION_FAILED"))[:100]
                reason = ("CANCELLED_BY_USER" if event.is_set() else
                          "WAREHOUSE_ERROR" if "WAREHOUSE" in code else
                          "PARQUET_WRITE_ERROR" if "PARQUET" in code or "ARROW" in code else
                          "REMOTE_ERROR" if code.startswith("REMOTE") or "TIMEOUT" in code else
                          "TRANSFER_ERROR" if code.startswith("TRANSFER") else
                          "VALIDATION_FAILED" if isinstance(exc, IntegrityError) else code)
                checkpoint = {**current.checkpoint, "phase": "FAILED", "failure_reason": reason,
                              "failed_at": _now()}
                self.store.operation_put(OperationRecord(current.operation_id, current.kind,
                                                         MaterializationState.FAILED,
                                                         current.payload, checkpoint, code))
                self._cleanup_staging(current)
                _event("materialization_failed", operation_id=plan.operation_id,
                       source_name=plan.source_name, reason_code=reason)
            raise
        finally:
            stopped.set()
            heartbeat.join(timeout=HEARTBEAT_INTERVAL_SECONDS + 1)
            with self._guard:
                if self._cancel_events.get(plan.operation_id) is event:
                    self._cancel_events.pop(plan.operation_id, None)
            self.release_table(lease)

    def _heartbeat_loop(self, operation_id: str, cancel: threading.Event,
                        stop: threading.Event) -> None:
        while not stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                if not self.store.operation_heartbeat(operation_id, self.worker_instance_id, _now()):
                    cancel.set()
                    _event("materialization_worker_lost", operation_id=operation_id)
                    return
                _event("materialization_heartbeat", operation_id=operation_id,
                       worker_instance_id=self.worker_instance_id)
            except Exception as exc:
                _LOG.warning(json.dumps({"event": "materialization_heartbeat_failed",
                                         "operation_id": operation_id,
                                         "reason_code": type(exc).__name__},
                                        sort_keys=True, separators=(",", ":")))

    def reconcile_startup(self) -> None:
        """Fail persisted work from a prior process and clean only its staging."""
        for item in self.store.operation_recent(limit=500):
            if item.get("kind") != "MATERIALIZATION" or item.get("state") not in NONTERMINAL_STATES:
                continue
            operation = self.store.operation_get(str(item.get("operation_id") or ""))
            if operation is None:
                continue
            checkpoint = dict(operation.checkpoint)
            heartbeat = _parse_time(checkpoint.get("heartbeat_at"))
            expired = heartbeat is not None and time.time() - heartbeat > LEASE_TIMEOUT_SECONDS
            reason = ("LEASE_EXPIRED" if expired else "SERVICE_RESTARTED"
                      if checkpoint.get("worker_instance_id") else "WORKER_LOST")
            failed_checkpoint = {**checkpoint, "phase": "FAILED", "failure_reason": reason,
                                 "failed_at": _now(), "heartbeat_at": _now()}
            self.store.operation_put(OperationRecord(operation.operation_id, operation.kind,
                                                     MaterializationState.FAILED,
                                                     operation.payload, failed_checkpoint, reason))
            self._cleanup_staging(operation)
            _event("materialization_reconciled", operation_id=operation.operation_id,
                   state="FAILED", reason_code=reason)

    def _cleanup_staging(self, operation: OperationRecord) -> None:
        plan = operation.payload.get("plan") if isinstance(operation.payload, dict) else None
        if not isinstance(plan, dict):
            return
        operation_id = str(operation.operation_id)
        source_name = str(plan.get("source_name") or "")
        workspace_identity = str(plan.get("workspace_identity") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", operation_id) or not source_name or not workspace_identity:
            return
        root = self.paths.datasets / source_key(source_name, workspace_identity)
        if root.is_symlink():
            return
        stage = root / "snapshots" / ("." + operation_id + ".partial")
        try:
            with dataset_lock(root, exclusive=True):
                if stage.is_symlink():
                    raise IntegrityError("Materialization staging directory must not be a symlink")
                if stage.exists():
                    if not stage.is_dir() or stage.resolve().parent != (root / "snapshots").resolve():
                        raise IntegrityError("Materialization staging path is unsafe")
                    shutil.rmtree(stage)
                state = dataset_state(root)
                staging = state.get("staging") if isinstance(state.get("staging"), list) else []
                atomic_dataset_state(root, {**state, "staging": [item for item in staging
                                                                  if item != operation_id]})
        except (OSError, IntegrityError) as exc:
            _LOG.warning(json.dumps({"event": "materialization_staging_cleanup_failed",
                                     "operation_id": operation_id,
                                     "reason_code": str(getattr(exc, "code", type(exc).__name__))},
                                    sort_keys=True, separators=(",", ":")))

    def retry(self, operation_id: str, *, progress: Any | None = None) -> dict[str, Any]:
        plan, payload = self.prepare_retry(operation_id)
        self.store.operation_put(OperationRecord(plan.operation_id, "MATERIALIZATION", MaterializationState.PLANNED,
                                                 payload, {"phase": "QUEUED", "chunks": []}, ""))
        return self.run(plan, str(payload.get("warehouse_id") or ""),
                        profile=payload.get("profile") or None,
                        principal=str(payload.get("principal") or ""), progress=progress)

    def prepare_retry(self, operation_id: str) -> tuple[AcquisitionPlan, dict[str, Any]]:
        """Build a fresh retry plan without resuming any persisted worker state."""
        operation = self.store.operation_get(operation_id)
        if operation is None or operation.kind != "MATERIALIZATION":
            raise ValidationError("Materialization operation was not found")
        if operation.state not in {MaterializationState.FAILED, MaterializationState.CANCELLED,
                                   MaterializationState.PAUSED}:
            if operation.state in {MaterializationState.PLANNED, MaterializationState.RUNNING,
                                   MaterializationState.VALIDATING}:
                return self.status(operation_id)
            raise ConflictError("Only failed or canceled materializations can be retried",
                                code="OPERATION_NOT_RETRYABLE")
        plan_value = operation.payload.get("plan")
        if not isinstance(plan_value, dict):
            raise ConflictError("Saved materialization plan is unavailable", code="OPERATION_STATE_INVALID")
        plan = _plan_from_dict(plan_value)
        fresh_id = uuid.uuid4().hex
        plan = AcquisitionPlan(fresh_id, plan.workspace_identity, plan.source_name, plan.source_version,
                               plan.projection, plan.predicate, plan.max_rows, plan.max_bytes,
                               plan.estimated_bytes, plan.force_refresh, plan.intent_projection,
                               plan.source_schema_identity, plan.selected_schema_identity)
        payload = {**operation.payload, "plan": plan.as_dict()}
        return plan, payload

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
        if event is None:
            raise ConflictError("The materialization worker is no longer active; refresh operation status",
                                code="WORKER_NOT_RUNNING")
        self.store.operation_checkpoint_update(operation_id,
                                              {"phase": "CANCEL_REQUESTED",
                                               "cancel_requested_at": _now(),
                                               "heartbeat_at": _now()}, active_only=True)
        statement_id = operation.checkpoint.get("statement_id")
        if statement_id:
            try:
                self.provider.transfer_cancel(statement_id,
                                              profile=operation.payload.get("profile") or None,
                                              timeout=30)
            except Exception as exc:
                _LOG.warning(json.dumps({"event": "materialization_cancel_remote_failed",
                                         "operation_id": operation_id,
                                         "reason_code": type(exc).__name__},
                                        sort_keys=True, separators=(",", ":")))
        _event("materialization_cancel_requested", operation_id=operation_id)
        return self.status(operation_id)

    def status(self, operation_id: str) -> dict[str, Any]:
        operation = self.store.operation_get(operation_id)
        if operation is None or operation.kind != "MATERIALIZATION":
            raise ValidationError("Materialization operation was not found")
        chunks = operation.checkpoint.get("chunks", [])
        chunks = chunks if isinstance(chunks, list) else []
        plan = operation.payload.get("plan") if isinstance(operation.payload, dict) else {}
        snapshot_id = operation.checkpoint.get("snapshot_id", "")
        materialization = self.store.materialization_get(snapshot_id) if snapshot_id else None
        return {"operation_id": operation.operation_id, "state": operation.state.value,
                "source_name": str(plan.get("source_name") or "") if isinstance(plan, dict) else "",
                "phase": operation.checkpoint.get("phase", ""),
                "created_at": operation.checkpoint.get("created_at", ""),
                "started_at": operation.checkpoint.get("started_at", ""),
                "last_activity_at": operation.checkpoint.get("heartbeat_at", ""),
                "failure_reason": operation.checkpoint.get("failure_reason", ""),
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


def _plan_from_dict(value: dict[str, Any]) -> AcquisitionPlan:
    try:
        return AcquisitionPlan(
            str(value["operation_id"]), str(value["workspace_identity"]),
            str(value["source_name"]), str(value.get("source_version") or ""),
            tuple(value["projection"]), str(value.get("predicate") or ""),
            int(value["max_rows"]), int(value["max_bytes"]), value.get("estimated_bytes"),
            bool(value.get("force_refresh")),
            tuple(value.get("intent_projection") or value["projection"]),
            str(value.get("source_schema_identity") or ""),
            str(value.get("selected_schema_identity") or ""))
    except (KeyError, TypeError, ValueError) as exc:
        raise ConflictError("Saved materialization plan is invalid", code="OPERATION_STATE_INVALID") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _event(event: str, **details: Any) -> None:
    _LOG.info(json.dumps({"event": event, **details}, sort_keys=True,
                         separators=(",", ":"), default=str))
