"""Bounded transfer of Databricks Arrow chunks into validated Parquet snapshots."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import random
import re
import shutil
import socket
import ssl
import stat
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from .errors import (ConflictError, IntegrityError, UnavailableError,
                     ValidationError)
from .coverage import (LocalCoverageService, atomic_dataset_state, dataset_lock,
                       dataset_state, schema_identity, source_key)
from .paths import AnalyticsPaths
from .planner import AcquisitionPlan
from .store import ContextStore

MAX_CHUNKS = 100_000
MAX_CHUNK_BYTES = 2 * 1024 ** 3
CHUNK_RETRY_ATTEMPTS = 4
DOWNLOAD_TIMEOUT_SECONDS = 120
_LOG = logging.getLogger(__name__)


def _now_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _transfer_event(event: str, **details: Any) -> None:
    _LOG.info(json.dumps({"event": event, **details}, sort_keys=True,
                         separators=(",", ":"), default=str))


class TransferProvider(Protocol):
    def transfer_submit(self, statement: str, warehouse_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def transfer_status(self, statement_id: str, warehouse_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def transfer_chunk(self, statement_id: str, chunk_index: int, warehouse_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def transfer_cancel(self, statement_id: str, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ChunkStats:
    row_count: int
    columns: tuple[str, ...]
    schema_fingerprint: str


class ChunkCodec(Protocol):
    @property
    def available(self) -> bool: ...
    def write_parquet(self, arrow_file: Path, parquet_file: Path) -> ChunkStats: ...
    def write_empty(self, schema: dict[str, Any], parquet_file: Path) -> ChunkStats: ...


class PyArrowChunkCodec:
    """Optional Arrow IPC to Parquet adapter; no dependency is installed implicitly."""

    def __init__(self) -> None:
        try:
            import pyarrow as pa
            import pyarrow.ipc as ipc
            import pyarrow.parquet as pq
            self.pa, self.ipc, self.pq = pa, ipc, pq
        except ImportError:
            self.pa = self.ipc = self.pq = None

    @property
    def available(self) -> bool:
        return self.pa is not None

    def write_parquet(self, arrow_file: Path, parquet_file: Path) -> ChunkStats:
        if not self.available:
            raise UnavailableError("PyArrow is not installed; Parquet materialization is unavailable",
                                   code="PYARROW_MISSING", retryable=False)
        try:
            source = self.pa.memory_map(str(arrow_file), "r")
            reader = self.ipc.open_stream(source)
            schema = reader.schema
            writer = self.pq.ParquetWriter(str(parquet_file), schema, compression="zstd")
            rows = 0
            try:
                for batch in reader:
                    writer.write_batch(batch)
                    rows += batch.num_rows
            finally:
                writer.close()
                source.close()
            return ChunkStats(rows, tuple(schema.names), _schema_hash(schema))
        except UnavailableError:
            raise
        except Exception as exc:
            raise IntegrityError("A transferred Arrow chunk could not be validated or converted") from exc

    def write_empty(self, schema: dict[str, Any], parquet_file: Path) -> ChunkStats:
        if not self.available:
            raise UnavailableError("PyArrow is not installed; Parquet materialization is unavailable",
                                   code="PYARROW_MISSING", retryable=False)
        columns = schema.get("columns") if isinstance(schema, dict) else None
        if not isinstance(columns, list) or any(not isinstance(col, dict) or not col.get("name") for col in columns):
            raise IntegrityError("Databricks returned an invalid empty-result schema")
        arrow_schema = self.pa.schema([self.pa.field(str(col["name"]), self.pa.null()) for col in columns])
        try:
            self.pq.write_table(self.pa.Table.from_batches([], schema=arrow_schema), str(parquet_file),
                                compression="zstd")
            return ChunkStats(0, tuple(arrow_schema.names), _schema_hash(arrow_schema))
        except Exception as exc:
            raise IntegrityError("An empty Parquet snapshot could not be created") from exc


def _schema_hash(schema: Any) -> str:
    return hashlib.sha256(str(schema).encode("utf-8")).hexdigest()


class ExternalLinkDownloader:
    """Download a trusted-provider link without credentials, redirects or URL logging."""

    def download(self, url: str, destination: Path, *, max_bytes: int,
                timeout: int = DOWNLOAD_TIMEOUT_SECONDS) -> tuple[int, str]:
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValidationError("Databricks returned an unsafe transfer URL") from exc
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or port not in (None, 443)):
            raise ValidationError("Databricks returned an unsafe transfer URL")
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname in {"localhost", "localhost.localdomain"}:
            raise ValidationError("Databricks returned an unsafe transfer URL")
        try:
            # Resolve and reject private destinations before opening the signed link.
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
            if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise ValidationError("Databricks returned an unsafe transfer destination")
        except ValidationError:
            raise
        except OSError as exc:
            raise UnavailableError("The Databricks transfer host could not be reached",
                                   code="TRANSFER_HOST_UNREACHABLE", retryable=True) from exc
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.apache.arrow.stream"},
                                         method="GET")
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(
            context=ssl.create_default_context()))
        written = 0
        digest = hashlib.sha256()
        try:
            with opener.open(request, timeout=timeout) as response, destination.open("xb") as output:
                declared = response.headers.get("Content-Length")
                if declared:
                    try:
                        if int(declared) > max_bytes:
                            raise ValidationError("An Arrow chunk exceeds the configured byte limit")
                    except ValueError as exc:
                        raise IntegrityError("The transfer returned an invalid content length") from exc
                while True:
                    block = response.read(min(1024 * 1024, max_bytes - written + 1))
                    if not block:
                        break
                    written += len(block)
                    if written > max_bytes:
                        raise ValidationError("An Arrow chunk exceeds the configured byte limit")
                    output.write(block)
                    digest.update(block)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
            return written, digest.hexdigest()
        except ValidationError:
            _unlink(destination)
            raise
        except urllib.error.HTTPError as exc:
            _unlink(destination)
            code = ("TRANSFER_LINK_EXPIRED" if exc.code in {401, 403, 404} else
                    "TRANSFER_HTTP_FAILED" if exc.code >= 500 or exc.code == 429 else
                    "TRANSFER_HTTP_REJECTED")
            raise UnavailableError("The Databricks result chunk download failed",
                                   code=code, retryable=code != "TRANSFER_HTTP_REJECTED") from None
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError):
            _unlink(destination)
            raise UnavailableError("The Databricks result chunk could not be downloaded",
                                   code="TRANSFER_NETWORK_FAILED", retryable=True) from None
        except OSError:
            _unlink(destination)
            raise UnavailableError("The Databricks result chunk could not be downloaded",
                                   code="TRANSFER_NETWORK_FAILED", retryable=True) from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _unlink(path: Path) -> None:
    try:
        if path.is_file() and not path.is_symlink():
            path.unlink()
    except OSError:
        pass


class MaterializationTransfer:
    """One operation, checkpointed by Arrow chunk; only validated snapshots are published."""

    def __init__(self, paths: AnalyticsPaths, store: ContextStore, provider: TransferProvider,
                 *, downloader: Any | None = None, codec: ChunkCodec | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.paths, self.store, self.provider = paths, store, provider
        self.downloader = downloader or ExternalLinkDownloader()
        self.codec = codec or PyArrowChunkCodec()
        self.sleep, self.monotonic = sleep, monotonic

    def run(self, plan: AcquisitionPlan, warehouse_id: str, *, profile: str | None = None,
            principal: str = "", timeout: int = 1800,
            cancel_requested: Callable[[], bool] | None = None,
            progress: Callable[[dict[str, Any]], None] | None = None,
            worker_instance_id: str = "") -> dict[str, Any]:
        if not self.codec.available:
            raise UnavailableError("PyArrow is not installed; Parquet materialization is unavailable",
                                   code="PYARROW_MISSING", retryable=False)
        if not warehouse_id or len(warehouse_id) > 256:
            raise ValidationError("A valid running SQL warehouse is required")
        if timeout < 5 or timeout > 24 * 60 * 60:
            raise ValidationError("Materialization timeout must be between 5 seconds and 24 hours")
        root = self._source_root(plan.source_name, plan.workspace_identity)
        snapshots = root / "snapshots"
        staging = snapshots / ("." + plan.operation_id + ".partial")
        lock_path = root / (plan.operation_id + ".lock")
        with _operation_lock(lock_path):
            existing_operation = self.store.operation_get(plan.operation_id)
            if existing_operation and existing_operation.state.value == "READY":
                return {"operation_id": plan.operation_id, "state": "READY",
                        "snapshot_id": existing_operation.checkpoint.get("snapshot_id", ""), "reused": True}
            free = shutil.disk_usage(root).free
            estimated_local = plan.estimated_bytes if plan.estimated_bytes is not None else plan.max_bytes
            if estimated_local is not None and free < estimated_local:
                raise ConflictError("Not enough local disk space to safely create this local copy",
                                    code="DISK_SPACE_INSUFFICIENT")
            snapshots.mkdir(mode=0o700, exist_ok=True)
            self.paths.secure_directory(snapshots)
            if staging.is_symlink():
                raise IntegrityError("Materialization staging directory must not be a symlink")
            staging.mkdir(mode=0o700, exist_ok=True)
            self.paths.secure_directory(staging)
            with dataset_lock(root, exclusive=True):
                state = dataset_state(root)
                staging_ids = state.get("staging") if isinstance(state.get("staging"), list) else []
                staging_ids = [item for item in staging_ids if isinstance(item, str)]
                if plan.operation_id not in staging_ids:
                    staging_ids.append(plan.operation_id)
                atomic_dataset_state(root, {**state, "version": 2, "staging": staging_ids[-100:]})
            operation = self.store.operation_get(plan.operation_id)
            payload = {"plan": plan.as_dict(), "warehouse_id": warehouse_id,
                       "profile": profile or "", "principal": principal[:256]}
            checkpoint = operation.checkpoint if operation else {"chunks": [], "phase": "PLANNED"}
            if operation and operation.state.value == "READY":
                return {"operation_id": plan.operation_id, "state": "READY",
                        "snapshot_id": operation.checkpoint.get("snapshot_id", ""), "reused": True}
            if operation and operation.state.value in {"FAILED", "CANCELLED", "PAUSED"}:
                raise ConflictError("This operation is terminal; retry it as a new materialization",
                                    code="OPERATION_NOT_RESUMABLE")
            owner = str(checkpoint.get("worker_instance_id") or "")
            if owner and worker_instance_id and owner != worker_instance_id and not checkpoint.get("resume_available"):
                raise ConflictError("This operation belongs to another worker instance",
                                    code="OPERATION_NOT_RESUMABLE")
            checkpoint = {**checkpoint,
                          "worker_instance_id": worker_instance_id or owner or uuid.uuid4().hex,
                          "worker_pid": os.getpid(),
                          "created_at": checkpoint.get("created_at") or _now_utc(),
                          "started_at": checkpoint.get("started_at") or _now_utc(),
                          "heartbeat_at": _now_utc()}
            if checkpoint.get("phase") in {"SUBMITTING", "SUBMITTING_QUERY", "SUBMISSION_UNKNOWN"} and not checkpoint.get("statement_id"):
                raise ConflictError("Databricks submission status is unknown; retry with a new materialization operation",
                                    code="SUBMISSION_STATUS_UNKNOWN")
            checkpoint = {**checkpoint, "phase": checkpoint.get("phase", "PLANNED")}
            self._put_operation(plan, payload, "RUNNING", checkpoint)
            deadline = self.monotonic() + timeout
            statement_id = checkpoint.get("statement_id")
            try:
                if cancel_requested and cancel_requested():
                    self._put_operation(plan, payload, "CANCELLED", {**checkpoint, "phase": "CANCELLED"})
                    return {"operation_id": plan.operation_id, "state": "CANCELLED", "completed_chunks": 0}
                if not statement_id:
                    checkpoint["phase"] = "STARTING_WAREHOUSE"
                    self._put_operation(plan, payload, "RUNNING", checkpoint)
                    _transfer_event("materialization_remote_transfer_started",
                                    source_name=plan.source_name,
                                    workspace_identity=plan.workspace_identity,
                                    warehouse_id=warehouse_id)
                    def warehouse_ready() -> None:
                        checkpoint["phase"] = "SUBMITTING_QUERY"
                        self._put_operation(plan, payload, "RUNNING", checkpoint)

                    submitted = self.provider.transfer_submit(
                        plan.statement(), warehouse_id, profile=profile,
                        max_rows=plan.max_rows, max_bytes=plan.max_bytes, timeout=min(timeout, 600),
                        on_warehouse_ready=warehouse_ready)
                    statement_id = submitted.get("statement_id") if isinstance(submitted, dict) else None
                    if not isinstance(statement_id, str) or not statement_id or len(statement_id) > 128:
                        raise IntegrityError("Databricks returned an invalid transfer identifier")
                    checkpoint.update({"phase": "WAITING_FOR_RESULT", "statement_id": statement_id})
                    self._put_operation(plan, payload, "RUNNING", checkpoint)
                    response = submitted
                else:
                    response = self.provider.transfer_status(statement_id, warehouse_id, profile=profile,
                                                             timeout=min(timeout, 120))
                response = self._wait_ready(statement_id, warehouse_id, profile, response,
                                            deadline, cancel_requested, progress, plan, payload, checkpoint)
                manifest = response.get("manifest") if isinstance(response.get("manifest"), dict) else {}
                if manifest.get("format") not in {None, "ARROW_STREAM"}:
                    raise IntegrityError("Databricks returned a non-Arrow materialization result")
                if manifest.get("truncated") is True:
                    raise ConflictError("The result exceeded materialization limits; narrow the columns or filter and retry",
                                        code="MATERIALIZATION_LIMIT_REACHED")
                total_rows = manifest.get("total_row_count")
                total_bytes = manifest.get("total_byte_count")
                if isinstance(total_rows, int) and plan.max_rows is not None and total_rows > plan.max_rows:
                    raise ConflictError("The result exceeded the configured row limit",
                                        code="MATERIALIZATION_LIMIT_REACHED")
                if isinstance(total_bytes, int) and plan.max_bytes is not None and total_bytes > plan.max_bytes:
                    raise ConflictError("The result exceeded the configured byte limit",
                                        code="MATERIALIZATION_LIMIT_REACHED")
                if isinstance(total_bytes, int) and shutil.disk_usage(root).free < total_bytes:
                    raise ConflictError("Not enough local disk space to safely create this local copy",
                                        code="DISK_SPACE_INSUFFICIENT")
                result_fingerprint = self.result_fingerprint(statement_id, manifest)
                if (checkpoint.get("remote_result_fingerprint") and
                        checkpoint["remote_result_fingerprint"] != result_fingerprint):
                    raise ConflictError("The remote result changed; restart this local copy from a clean transfer",
                                        code="REMOTE_RESULT_CHANGED")
                checkpoint.update({"remote_result_fingerprint": result_fingerprint,
                                   "planned_rows": total_rows if isinstance(total_rows, int) else None,
                                   "estimated_total_bytes": total_bytes if isinstance(total_bytes, int) else None,
                                   "total_chunks": manifest.get("total_chunk_count"),
                                   "phase": "RESULT_READY", "resume_available": True})
                self._put_operation(plan, payload, "RUNNING", checkpoint)
                checkpoint["phase"] = "DOWNLOADING_ARROW"
                self._put_operation(plan, payload, "RUNNING", checkpoint)
                count = manifest.get("total_chunk_count", 0)
                if not isinstance(count, int) or count < 0 or count > MAX_CHUNKS:
                    raise IntegrityError("Databricks returned an invalid result chunk count")
                result = response.get("result") if isinstance(response.get("result"), dict) else {}
                links = result.get("external_links") if isinstance(result.get("external_links"), list) else []
                completed = self._verified_chunks(staging, checkpoint)
                for index in range(count):
                    if cancel_requested and cancel_requested():
                        try:
                            self.provider.transfer_cancel(statement_id, profile=profile, timeout=30)
                        finally:
                            self._put_operation(plan, payload, "CANCELLED", {**checkpoint, "phase": "CANCELLED"})
                        return {"operation_id": plan.operation_id, "state": "CANCELLED",
                                "completed_chunks": len(checkpoint.get("chunks", []))}
                    if self.monotonic() >= deadline:
                        raise UnavailableError("Materialization timed out; downloaded chunk progress was preserved",
                                               code="MATERIALIZATION_TIMEOUT", retryable=True)
                    if index in completed:
                        continue
                    link_record = self._find_link(links, index)
                    if link_record is None:
                        chunk_response = self.provider.transfer_chunk(statement_id, index, warehouse_id,
                                                                      profile=profile, timeout=60)
                        link_record = self._find_link_from_response(chunk_response, index)
                    if link_record is None:
                        raise IntegrityError("Databricks did not return a signed URL for a result chunk")
                    expected_bytes = link_record.get("byte_count")
                    if isinstance(expected_bytes, int) and shutil.disk_usage(root).free < expected_bytes * 2:
                        raise ConflictError("Not enough local disk space to safely create this local copy",
                                            code="DISK_SPACE_INSUFFICIENT")
                    arrow_path = staging / (f"chunk-{index:06d}.arrow")
                    try:
                        downloaded_bytes, digest, expected_bytes = self._download_with_retry(
                            statement_id, index, warehouse_id, profile, link_record,
                            arrow_path, plan.max_bytes or MAX_CHUNK_BYTES, deadline)
                        if isinstance(expected_bytes, int) and downloaded_bytes != expected_bytes:
                            raise IntegrityError("A transferred Arrow chunk does not match its declared byte count")
                        existing_bytes = sum(item.get("bytes", 0) for item in checkpoint.get("chunks", []))
                        if plan.max_bytes is not None and downloaded_bytes + existing_bytes > plan.max_bytes:
                            raise ConflictError("The transfer exceeded its configured byte limit",
                                                code="MATERIALIZATION_LIMIT_REACHED")
                        if shutil.disk_usage(root).free < max(downloaded_bytes, 16 * 1024 ** 2):
                            raise ConflictError("Not enough local disk space to safely create this local copy",
                                                code="DISK_SPACE_INSUFFICIENT")
                        parquet_path = staging / (f"chunk-{index:06d}.parquet.tmp")
                        checkpoint["phase"] = "WRITING_PARQUET"
                        self._put_operation(plan, payload, "RUNNING", checkpoint)
                        try:
                            stats = self.codec.write_parquet(arrow_path, parquet_path)
                        except Exception as exc:
                            raise UnavailableError("Anvil could not write a local Parquet chunk",
                                                   code="PARQUET_WRITE_ERROR", retryable=False) from exc
                        parquet_bytes = parquet_path.stat().st_size
                        if parquet_bytes <= 0:
                            raise IntegrityError("Arrow conversion produced an empty Parquet file")
                        if plan.max_bytes is not None and parquet_bytes + sum(item.get("parquet_bytes", 0)
                                               for item in checkpoint.get("chunks", [])) > plan.max_bytes:
                            raise ConflictError("The local Parquet snapshot exceeded its configured byte limit",
                                                code="MATERIALIZATION_LIMIT_REACHED")
                        expected_columns = tuple(plan.projection) if plan.projection != ("*",) else stats.columns
                        if plan.projection != ("*",) and tuple(name.casefold() for name in stats.columns) != tuple(
                                name.casefold() for name in plan.projection):
                            raise IntegrityError("The Arrow result schema does not match the requested projection")
                        prior_schema = checkpoint.get("schema_fingerprint")
                        if prior_schema and prior_schema != stats.schema_fingerprint:
                            raise IntegrityError("Arrow result chunks have inconsistent schemas")
                        target = staging / (f"chunk-{index:06d}.parquet")
                        os.replace(parquet_path, target)
                        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
                        checkpoint.setdefault("chunks", []).append({
                            "index": index, "rows": stats.row_count, "bytes": downloaded_bytes,
                            "parquet_bytes": parquet_bytes, "sha256": digest,
                            "parquet_sha256": _file_hash(target), "file": target.name})
                        checkpoint["schema_fingerprint"] = stats.schema_fingerprint
                        checkpoint["columns"] = list(stats.columns or expected_columns)
                        checkpoint["phase"] = "DOWNLOADING_ARROW"
                        self._put_operation(plan, payload, "RUNNING", checkpoint)
                        _transfer_event("materialization_chunk_completed", operation_id=plan.operation_id,
                                        chunk_index=index, rows=stats.row_count,
                                        completed_chunks=len(checkpoint["chunks"]), total_chunks=count)
                        _unlink(arrow_path)
                        _unlink(parquet_path)
                        if progress:
                            progress({"operation_id": plan.operation_id, "state": "RUNNING",
                                      "completed_chunks": len(checkpoint["chunks"]), "total_chunks": count,
                                      "rows": sum(item["rows"] for item in checkpoint["chunks"]),
                                      "bytes": sum(item["bytes"] for item in checkpoint["chunks"])})
                    finally:
                        _unlink(arrow_path)
                        _unlink(staging / (f"chunk-{index:06d}.parquet.tmp"))
                if count == 0:
                    empty_path = staging / "chunk-000000.parquet.tmp"
                    empty_stats = self.codec.write_empty(manifest.get("schema") or {}, empty_path)
                    target = staging / "chunk-000000.parquet"
                    os.replace(empty_path, target)
                    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
                    checkpoint["chunks"] = [{"index": 0, "rows": 0, "bytes": 0,
                                             "parquet_bytes": target.stat().st_size,
                                             "sha256": hashlib.sha256(b"").hexdigest(),
                                             "parquet_sha256": _file_hash(target),
                                             "file": target.name}]
                    checkpoint["schema_fingerprint"] = empty_stats.schema_fingerprint
                    checkpoint["columns"] = list(empty_stats.columns)
                checkpoint["phase"] = "VALIDATING"
                self._put_operation(plan, payload, "RUNNING", checkpoint)
                if cancel_requested and cancel_requested():
                    raise ConflictError("Materialization was canceled", code="CANCELLED_BY_USER")
                checkpoint["phase"] = "ACTIVATING"
                self._put_operation(plan, payload, "RUNNING", checkpoint)
                committed = self._publish(plan, staging, root, checkpoint, manifest,
                                          principal=principal)
                self._put_operation(plan, payload, "READY", {**checkpoint, "phase": "READY",
                                                                "snapshot_id": committed["snapshot_id"]})
                if progress:
                    progress({"operation_id": plan.operation_id, "state": "READY",
                              "snapshot_id": committed["snapshot_id"]})
                _transfer_event("local_dataset_switched", source_name=plan.source_name,
                                workspace_identity=plan.workspace_identity,
                                snapshot_id=committed["snapshot_id"],
                                rows=committed["row_count"],
                                bytes=committed["parquet_bytes"])
                _transfer_event("materialization_completed", operation_id=plan.operation_id,
                                source_name=plan.source_name, rows=committed["row_count"])
                return {"operation_id": plan.operation_id, "state": "READY",
                        "snapshot_id": committed["snapshot_id"], "rows": committed["row_count"],
                        "bytes": committed["byte_count"], "reused": False}
            except Exception as exc:
                if cancel_requested and cancel_requested():
                    state = "CANCELLED"
                else:
                    state = "FAILED"
                safe_code = str(getattr(exc, "code", "MATERIALIZATION_FAILED"))[:100]
                reason = ("CANCELLED_BY_USER" if state == "CANCELLED" else
                          "REMOTE_ERROR" if safe_code in {"REMOTE_QUERY_FAILED", "SUBMISSION_STATUS_UNKNOWN",
                                                          "MATERIALIZATION_TIMEOUT"}
                          else "WAREHOUSE_ERROR" if "WAREHOUSE" in safe_code
                          else "TRANSFER_ERROR" if safe_code.startswith("TRANSFER_")
                          else "PARQUET_WRITE_ERROR" if "PARQUET" in safe_code or "ARROW" in safe_code
                          else "VALIDATION_FAILED" if isinstance(exc, IntegrityError)
                          else safe_code)
                resumable = bool(state == "FAILED" and getattr(exc, "retryable", False) and
                                 checkpoint.get("statement_id") and
                                 checkpoint.get("remote_result_fingerprint"))
                checkpoint.update({"phase": "RESUMABLE" if resumable else state,
                                   "resume_available": resumable,
                                   "failure_reason": reason, "failed_at": _now_utc()})
                self._put_operation(plan, payload, state, checkpoint, safe_code)
                if not resumable:
                    self._cleanup_staging(plan, root, staging)
                if safe_code in {"REMOTE_RESULT_EXPIRED", "REMOTE_RESULT_CHANGED"}:
                    _transfer_event("materialization_result_expired", operation_id=plan.operation_id,
                                    reason_code=safe_code)
                _transfer_event("materialization_cancelled" if state == "CANCELLED" else
                                "materialization_failed", operation_id=plan.operation_id,
                                source_name=plan.source_name, reason_code=reason)
                raise

    def _wait_ready(self, statement_id: str, warehouse_id: str, profile: str | None,
                    response: dict[str, Any], deadline: float,
                    cancel_requested: Callable[[], bool] | None, progress: Callable[[dict[str, Any]], None] | None,
                    plan: AcquisitionPlan, payload: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
        polls = 0
        while True:
            status = response.get("status") if isinstance(response.get("status"), dict) else {}
            state = str(status.get("state") or "").upper()
            if state == "SUCCEEDED":
                return response
            if state in {"FAILED", "CANCELED", "CLOSED"}:
                error = status.get("error") if isinstance(status.get("error"), dict) else {}
                message = error.get("message") or "Databricks could not complete the materialization query"
                raise UnavailableError(str(message)[:500], code="REMOTE_QUERY_FAILED", retryable=False)
            if state not in {"PENDING", "RUNNING"}:
                raise IntegrityError("Databricks returned an unknown statement state")
            if cancel_requested and cancel_requested():
                self.provider.transfer_cancel(statement_id, profile=profile, timeout=30)
                self._put_operation(plan, payload, "CANCELLED", {**checkpoint, "phase": "CANCELLED"})
                raise ConflictError("Materialization was canceled")
            if self.monotonic() >= deadline:
                raise UnavailableError("The Databricks query exceeded its time limit; retry to start a fresh transfer",
                                       code="MATERIALIZATION_TIMEOUT", retryable=True)
            if progress and polls % 5 == 0:
                progress({"operation_id": plan.operation_id, "state": state or "RUNNING",
                          "phase": "WAITING_FOR_RESULT"})
            self.sleep(min(2.0, max(0.0, deadline - self.monotonic())))
            response = self.provider.transfer_status(statement_id, warehouse_id, profile=profile,
                                                     timeout=min(120, max(5, int(deadline - self.monotonic()))))
            polls += 1

    @staticmethod
    def _find_link(links: list[Any], index: int) -> dict[str, Any] | None:
        for item in links:
            if isinstance(item, dict) and item.get("chunk_index") == index:
                url = item.get("external_link")
                if isinstance(url, str) and url:
                    return item
        return None

    @classmethod
    def _find_link_from_response(cls, response: Any, index: int) -> dict[str, Any] | None:
        if not isinstance(response, dict):
            return None
        result = response.get("result") if isinstance(response.get("result"), dict) else response
        links = result.get("external_links") if isinstance(result.get("external_links"), list) else []
        link = cls._find_link(links, index)
        if link:
            return link
        # Some API responses represent one external result link directly.
        if result.get("chunk_index", index) == index and isinstance(result.get("external_link"), str):
            return result
        return None

    @staticmethod
    def result_fingerprint(statement_id: str, manifest: dict[str, Any]) -> str:
        stable = {"statement_id": statement_id}
        for key in ("format", "total_chunk_count", "total_row_count", "total_byte_count", "schema", "truncated"):
            stable[key] = manifest.get(key)
        return hashlib.sha256(json.dumps(stable, sort_keys=True,
            separators=(",", ":"), default=str).encode("utf-8")).hexdigest()

    def _download_with_retry(self, statement_id: str, index: int, warehouse_id: str,
                             profile: str | None, link: dict[str, Any], destination: Path,
                             max_bytes: int, deadline: float) -> tuple[int, str, Any]:
        current = link
        for attempt in range(CHUNK_RETRY_ATTEMPTS):
            try:
                size, digest = self.downloader.download(current["external_link"], destination,
                                                        max_bytes=min(max_bytes, MAX_CHUNK_BYTES))
                return size, digest, current.get("byte_count")
            except UnavailableError as exc:
                _unlink(destination)
                if not exc.retryable or attempt + 1 >= CHUNK_RETRY_ATTEMPTS:
                    raise
                if exc.code == "TRANSFER_LINK_EXPIRED":
                    renewed = self.provider.transfer_chunk(statement_id, index, warehouse_id,
                                                           profile=profile, timeout=60)
                    new_link = self._find_link_from_response(renewed, index)
                    if new_link is None:
                        raise UnavailableError("The Databricks result link could not be renewed",
                                               code="REMOTE_RESULT_EXPIRED", retryable=False) from exc
                    current = new_link
                delay = min(4.0, 0.25 * (2 ** attempt) + random.uniform(0.0, 0.25))
                _transfer_event("materialization_chunk_retry", chunk_index=index,
                                attempt=attempt + 1, reason_code=exc.code)
                if self.monotonic() + delay >= deadline:
                    raise
                self.sleep(delay)
        raise AssertionError("unreachable retry state")

    def _verified_chunks(self, staging: Path, checkpoint: dict[str, Any]) -> set[int]:
        valid: set[int] = set()
        chunks = checkpoint.get("chunks")
        if not isinstance(chunks, list):
            raise IntegrityError("Materialization checkpoint is invalid")
        for item in list(chunks):
            if not isinstance(item, dict) or not isinstance(item.get("index"), int):
                raise IntegrityError("Materialization checkpoint is invalid")
            name = item.get("file")
            if not isinstance(name, str) or "/" in name or "\\" in name:
                raise IntegrityError("Materialization checkpoint contains an unsafe path")
            path = staging / name
            if path.is_symlink():
                raise IntegrityError("Materialization checkpoint file must not be a symlink")
            if path.is_file() and _file_hash(path) == item.get("parquet_sha256"):
                valid.add(item["index"])
            else:
                _unlink(path)
                chunks.remove(item)
        return valid

    def _publish(self, plan: AcquisitionPlan, staging: Path, source_root: Path,
                 checkpoint: dict[str, Any], remote_manifest: dict[str, Any], *,
                 principal: str) -> dict[str, Any]:
        chunks = sorted(checkpoint.get("chunks", []), key=lambda item: item["index"])
        expected_count = remote_manifest.get("total_chunk_count", 0)
        if expected_count and [item["index"] for item in chunks] != list(range(expected_count)):
            raise IntegrityError("Materialization checkpoint is missing one or more result chunks")
        rows = sum(int(item["rows"]) for item in chunks)
        remote_rows = remote_manifest.get("total_row_count")
        if isinstance(remote_rows, int) and rows != remote_rows:
            raise IntegrityError("Downloaded row count does not match the Databricks manifest")
        total_bytes = sum(int(item["bytes"]) for item in chunks)
        remote_bytes = remote_manifest.get("total_byte_count")
        if isinstance(remote_bytes, int) and total_bytes != remote_bytes:
            raise IntegrityError("Downloaded byte count does not match the Databricks manifest")
        parquet_bytes = sum(int(item["parquet_bytes"]) for item in chunks)
        chunk_hashes = [item["parquet_sha256"] for item in chunks]
        snapshot_id = hashlib.sha256(json.dumps({"operation": plan.operation_id,
                                                "source_version": plan.source_version,
                                                "chunks": chunk_hashes}, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
        file_names = [item["file"] for item in chunks]
        manifest = {"state": "READY", "snapshot_id": snapshot_id,
                    "operation_id": plan.operation_id, "source_name": plan.source_name,
                    "workspace_identity": plan.workspace_identity,
                    "source_version": plan.source_version,
                    "columns": checkpoint.get("columns", []),
                    "selected_columns": list(plan.intent_projection or plan.projection),
                    "all_columns": (plan.intent_projection or plan.projection) == ("*",),
                    "columns_mode": "ALL" if (plan.intent_projection or plan.projection) == ("*",) else "SELECTED",
                    "rows_mode": "LIMITED" if plan.max_rows is not None else
                                 "FILTERED" if plan.predicate else "FULL",
                    "row_limit": plan.max_rows,
                    "predicate": plan.predicate, "complete": True,
                    "row_count": rows, "bytes": total_bytes,
                    "parquet_bytes": parquet_bytes, "files": file_names,
                    "file_bytes": {item["file"]: item["parquet_bytes"] for item in chunks},
                    "file_sha256": {item["file"]: item["parquet_sha256"] for item in chunks},
                    "principal": principal[:256], "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        remote_schema = remote_manifest.get("schema")
        schema_columns = remote_schema.get("columns") if isinstance(remote_schema, dict) else None
        if (isinstance(schema_columns, list) and schema_columns and
                all(isinstance(item, dict) and (item.get("type_text") or item.get("type_name") or item.get("type"))
                    for item in schema_columns)):
            manifest["parquet_schema_identity"] = schema_identity(schema_columns)
        if plan.source_schema_identity:
            manifest["schema_identity"] = plan.source_schema_identity
            manifest["source_schema_identity"] = plan.source_schema_identity
        elif manifest.get("parquet_schema_identity"):
            # Compatibility for plans created before full table schema identity
            # was recorded by the catalog metadata path.
            manifest["schema_identity"] = manifest["parquet_schema_identity"]
        if plan.selected_schema_identity:
            manifest["selected_schema_identity"] = plan.selected_schema_identity
        manifest["freshness"] = ("CURRENT" if plan.source_version not in {"", "UNVERIFIED", "UNKNOWN"}
                                  else "UNKNOWN")
        manifest_path = staging / "manifest.json"
        _atomic_json(manifest_path, manifest)
        final_dir = source_root / "snapshots" / snapshot_id
        if final_dir.exists() or final_dir.is_symlink():
            if final_dir.is_symlink() or not final_dir.is_dir():
                raise IntegrityError("Materialization target is unsafe")
            existing_manifest = _read_json(final_dir / "manifest.json")
            if existing_manifest.get("snapshot_id") != snapshot_id:
                raise IntegrityError("Existing materialization snapshot does not match its identity")
            shutil.rmtree(staging)
        else:
            os.replace(staging, final_dir)
            self.paths.secure_directory(final_dir)
        materialization = {"materialization_id": snapshot_id, "source_name": plan.source_name,
                           "source_version": plan.source_version,
                           "filters": [plan.predicate] if plan.predicate else [],
                           "columns": manifest["columns"], "coverage": manifest,
                           "state": "READY", "files": file_names,
                           "byte_count": total_bytes, "principal": principal[:256]}
        self.store.materialization_put(materialization)
        now = time.time()
        with dataset_lock(source_root, exclusive=True):
            old_state = dataset_state(source_root)
            old_pointer = old_state.get("current") if isinstance(old_state.get("current"), dict) else None
            previous = None
            if old_pointer and old_pointer.get("snapshot_id") != snapshot_id:
                previous = {"snapshot_id": old_pointer["snapshot_id"],
                            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 86400))}
            elif old_pointer and old_pointer.get("snapshot_id") == snapshot_id:
                previous = old_state.get("previous")
            else:
                old_previous = old_state.get("previous")
                if isinstance(old_previous, dict):
                    try:
                        if time.strptime(str(old_previous.get("expires_at") or ""),
                                         "%Y-%m-%dT%H:%M:%SZ") > time.gmtime(now):
                            previous = old_previous
                    except ValueError:
                        previous = None
            stage_ids = old_state.get("staging") if isinstance(old_state.get("staging"), list) else []
            stage_ids = [item for item in stage_ids if item != plan.operation_id and isinstance(item, str)]
            published = {**old_state, "version": 2, "schema_version": 2,
                         "table_identity": source_key(plan.source_name, plan.workspace_identity),
                         "coverage": {"columns_mode": manifest["columns_mode"],
                                      "rows_mode": manifest["rows_mode"],
                                      "predicate": plan.predicate},
                         "source_schema": {"identity": manifest.get("source_schema_identity") or
                                           manifest.get("schema_identity") or ""},
                         "physical_schema": (old_state.get("physical_schema", {}) if old_pointer and
                                             old_pointer.get("snapshot_id") == snapshot_id else {}),
                         "current": {"snapshot_id": snapshot_id,
                                     "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))},
                         "previous": previous, "staging": stage_ids[-100:]}
            operation = self.store.operation_get(plan.operation_id)
            if operation and isinstance(operation.payload, dict):
                self._put_operation(plan, operation.payload, "RUNNING",
                                    {**checkpoint, "phase": "ACTIVATING"})
            atomic_dataset_state(source_root, published)
            coverage = LocalCoverageService(self.paths, self.store)
            current = coverage.current(plan.source_name, plan.workspace_identity)
            if current is None:
                raise IntegrityError("Published local dataset could not be read back")
            coverage.publish_dataset_record(current)
            keep = {snapshot_id}
            if previous and isinstance(previous.get("snapshot_id"), str):
                keep.add(previous["snapshot_id"])
            self._prune_generations(source_root, plan, keep)
        return {"snapshot_id": snapshot_id, "row_count": rows, "byte_count": total_bytes,
                "parquet_bytes": parquet_bytes}

    def _source_root(self, source_name: str, workspace_identity: str) -> Path:
        datasets = self.paths.datasets
        if datasets.is_symlink():
            raise IntegrityError("Analytics data root must not be a symlink")
        datasets.mkdir(mode=0o700, exist_ok=True)
        self.paths.secure_directory(datasets)
        root = datasets / source_key(source_name, workspace_identity)
        if root.is_symlink():
            raise IntegrityError("Materialization source directory must not be a symlink")
        root.mkdir(mode=0o700, exist_ok=True)
        self.paths.secure_directory(root)
        return root

    def _prune_generations(self, root: Path, plan: AcquisitionPlan, keep: set[str]) -> None:
        snapshots = root / "snapshots"
        if snapshots.is_symlink() or not snapshots.is_dir():
            return
        removed = []
        for directory in snapshots.iterdir():
            if directory.name in keep or not re.fullmatch(r"[a-f0-9]{64}", directory.name):
                continue
            if directory.is_symlink() or not directory.is_dir():
                continue
            manifest_path = directory / "manifest.json"
            if manifest_path.is_symlink() or not manifest_path.is_file():
                continue
            try:
                manifest = _read_json(manifest_path)
            except (IntegrityError, OSError, ValueError):
                continue
            if (manifest.get("state") == "READY" and manifest.get("snapshot_id") == directory.name
                    and manifest.get("source_name") == plan.source_name
                    and manifest.get("workspace_identity") == plan.workspace_identity):
                shutil.rmtree(directory)
                removed.append(directory.name)
        self.store.materialization_delete(removed)

    def _put_operation(self, plan: AcquisitionPlan, payload: dict[str, Any], state: str,
                       checkpoint: dict[str, Any], error_code: str = "") -> None:
        from .models import MaterializationState, OperationRecord
        existing = self.store.operation_get(plan.operation_id)
        if existing:
            for key in ("worker_instance_id", "worker_pid", "created_at", "started_at"):
                if key not in checkpoint and key in existing.checkpoint:
                    checkpoint[key] = existing.checkpoint[key]
        checkpoint["heartbeat_at"] = _now_utc()
        self.store.operation_put(OperationRecord(plan.operation_id, "MATERIALIZATION",
                                                 MaterializationState(state), payload, checkpoint, error_code))

    def _cleanup_staging(self, plan: AcquisitionPlan, root: Path, staging: Path) -> None:
        """Discard incomplete work under the dataset lock and preserve CURRENT."""
        try:
            with dataset_lock(root, exclusive=True):
                if staging.is_symlink():
                    raise IntegrityError("Materialization staging directory must not be a symlink")
                if staging.exists():
                    if not staging.is_dir() or staging.resolve().parent != (root / "snapshots").resolve():
                        raise IntegrityError("Materialization staging directory is unsafe")
                    shutil.rmtree(staging)
                state = dataset_state(root)
                staging_ids = state.get("staging") if isinstance(state.get("staging"), list) else []
                atomic_dataset_state(root, {**state, "staging": [value for value in staging_ids
                                                                     if value != plan.operation_id]})
        except (OSError, IntegrityError) as exc:
            _transfer_event("materialization_staging_cleanup_failed",
                            operation_id=plan.operation_id,
                            reason_code=str(getattr(exc, "code", type(exc).__name__)))


class _operation_lock:
    """Cross-process lock for an idempotent materialization identity."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "_operation_lock":
        import fcntl
        if self.path.is_symlink():
            raise IntegrityError("Materialization lock must not be a symlink")
        self.handle = self.path.open("a+b")
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        import fcntl
        if self.handle:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise IntegrityError("Analytics snapshot metadata must not be a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.parent / ("." + path.name + ".tmp")
    if temporary.is_symlink():
        raise IntegrityError("Analytics temporary metadata must not be a symlink")
    with temporary.open("wb") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise IntegrityError("Materialization snapshot metadata is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityError("Materialization snapshot metadata is unreadable") from exc
    if not isinstance(value, dict):
        raise IntegrityError("Materialization snapshot metadata is invalid")
    return value


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
