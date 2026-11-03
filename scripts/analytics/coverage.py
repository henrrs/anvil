"""Exact, conservative coverage checks for published Parquet snapshots."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fcntl

from .errors import IntegrityError
from .paths import AnalyticsPaths
from .planner import QueryPlan, predicate_columns
from .store import ContextStore

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoverageDecision:
    covered: bool
    reason: str
    missing_columns: tuple[str, ...] = ()
    snapshot_id: str = ""
    state: str = "NOT_COVERED"
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoveragePlan:
    action: str
    reason: str
    snapshot_id: str = ""
    remote_transfer_required: bool = True


@contextmanager
def dataset_lock(root: Path, *, exclusive: bool, blocking: bool = True):
    """Coordinate readers, publication, retention and explicit deletion."""
    if root.is_symlink():
        raise IntegrityError("Analytics dataset directory must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = root / "dataset.lock"
    if lock_path.is_symlink():
        raise IntegrityError("Analytics dataset lock must not be a symlink")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, stat.S_IRUSR | stat.S_IWUSR)
    handle = os.fdopen(descriptor, "r+b")
    try:
        os.fchmod(handle.fileno(), stat.S_IRUSR | stat.S_IWUSR)
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if not blocking:
            operation |= fcntl.LOCK_NB
        fcntl.flock(handle.fileno(), operation)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def dataset_state(root: Path) -> dict[str, Any]:
    """Read the versioned pointer, tolerating the legacy current.json format."""
    state_path = root / "dataset-state.json"
    if state_path.is_symlink():
        raise IntegrityError("Analytics dataset state must not be a symlink")
    if state_path.is_file():
        return LocalCoverageService._read_json(state_path, maximum_bytes=64 * 1024)
    legacy = root / "current.json"
    if legacy.is_symlink():
        raise IntegrityError("Analytics snapshot pointer must not be a symlink")
    if legacy.is_file():
        value = LocalCoverageService._read_json(legacy, maximum_bytes=64 * 1024)
        current = value.get("current") if isinstance(value.get("current"), dict) else value
        return {"version": 1, "current": current, "previous": None, "staging": []}
    return {"version": 1, "current": None, "previous": None, "staging": []}


def atomic_dataset_state(root: Path, value: dict[str, Any]) -> None:
    """Durably replace the logical dataset pointer and legacy compatibility pointer."""
    state_path = root / "dataset-state.json"
    legacy_path = root / "current.json"
    for path in (state_path, legacy_path):
        if path.is_symlink():
            raise IntegrityError("Analytics snapshot pointer must not be a symlink")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    if len(payload) > 64 * 1024:
        raise IntegrityError("Analytics dataset state exceeds its size limit")
    temporary = root / (".dataset-state-" + str(os.getpid()) + ".tmp")
    if temporary.is_symlink():
        raise IntegrityError("Analytics dataset temporary state must not be a symlink")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY |
                         (getattr(os, "O_NOFOLLOW", 0)), stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, state_path)
    directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    current = value.get("current")
    try:
        if isinstance(current, dict) and isinstance(current.get("snapshot_id"), str):
            legacy_payload = json.dumps({"snapshot_id": current["snapshot_id"]},
                                        separators=(",", ":")).encode("utf-8") + b"\n"
            legacy_temp = root / (".current-" + str(os.getpid()) + ".tmp")
            descriptor = os.open(legacy_temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY |
                                 getattr(os, "O_NOFOLLOW", 0), stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(legacy_payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(legacy_temp, legacy_path)
        elif legacy_path.exists():
            legacy_path.unlink()
    except OSError as exc:
        # dataset-state.json is authoritative for this release. A legacy mirror
        # write must not turn a completed pointer switch into a reported failed
        # materialization; log the compatibility repair for the next read.
        _LOG.warning(json.dumps({"event": "legacy_pointer_mirror_failed",
                                 "reason_code": type(exc).__name__},
                                sort_keys=True, separators=(",", ":")))


def source_key(source_name: str, workspace_identity: str | None = None) -> str:
    """Return a stable workspace/table key, or the v2.17 legacy table-only key."""
    canonical_source = ".".join(part.casefold() for part in source_name.split("."))
    identity = (source_name if not workspace_identity else
                workspace_identity.casefold() + "\0" + canonical_source)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def dataset_identity(workspace_identity: str, source_name: str) -> str:
    if not workspace_identity:
        raise ValueError("workspace identity is required for a LocalDataset")
    return source_key(source_name, workspace_identity)


def schema_identity(columns: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    normalized = []
    for column in columns:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or "").strip()
        if not name:
            continue
        type_name = str(column.get("type_text") or column.get("type_name") or
                         column.get("type") or "UNKNOWN").strip()
        normalized.append((name.casefold(), re.sub(r"\s+", " ", type_name).casefold()))
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")).hexdigest()


class LocalCoverageService:
    def __init__(self, paths: AnalyticsPaths, store: ContextStore) -> None:
        self.paths = paths
        self.store = store

    def dataset_root(self, source_name: str, workspace_identity: str | None = None) -> Path:
        return self.paths.datasets / source_key(source_name, workspace_identity)

    def pointer_path(self, source_name: str, workspace_identity: str | None = None) -> Path:
        return self.dataset_root(source_name, workspace_identity) / "current.json"

    def current(self, source_name: str, workspace_identity: str | None = None) -> dict[str, Any] | None:
        source_root = self.dataset_root(source_name, workspace_identity)
        if self.paths.datasets.is_symlink():
            raise IntegrityError("Analytics data root must not be a symlink")
        current = self._read_current(source_root, source_name, workspace_identity)
        candidates = [current] if current is not None else []
        # v2.17 and earlier keyed data only by table name. Reuse it only when
        # its manifest proves it belongs to the selected workspace.
        if workspace_identity:
            legacy_root = self.dataset_root(source_name)
            if legacy_root != source_root:
                legacy = self._read_current(legacy_root, source_name, workspace_identity)
                if legacy is not None:
                    candidates.append(legacy)
        if not candidates:
            return None
        return max(candidates, key=self._dataset_breadth)

    @staticmethod
    def _dataset_breadth(current: dict[str, Any]) -> tuple[int, int, int, int, int]:
        manifest = current["manifest"]
        columns_mode = str(manifest.get("columns_mode") or
                           ("ALL" if manifest.get("all_columns") else "SELECTED")).upper()
        rows_mode = str(manifest.get("rows_mode") or
                        ("FILTERED" if manifest.get("predicate") else "FULL")).upper()
        columns = manifest.get("columns") if isinstance(manifest.get("columns"), list) else []
        return (int(columns_mode == "ALL"), int(rows_mode == "FULL"), len(columns),
                int(bool(manifest.get("source_version"))), int(manifest.get("row_count") or 0))

    @contextmanager
    def locked_snapshot(self, source_name: str,
                        workspace_identity: str | None = None):
        """Hold a shared generation lock until a local query has finished reading."""
        if self.paths.datasets.is_symlink():
            raise IntegrityError("Analytics data root must not be a symlink")
        roots = {self.dataset_root(source_name, workspace_identity)}
        if workspace_identity:
            roots.add(self.dataset_root(source_name))
        with ExitStack() as stack:
            for root in sorted(roots, key=str):
                stack.enter_context(dataset_lock(root, exclusive=False))
            yield self.current(source_name, workspace_identity)

    def _read_current(self, source_root: Path, source_name: str,
                      workspace_identity: str | None) -> dict[str, Any] | None:
        if source_root.is_symlink():
            raise IntegrityError("Analytics dataset directory must not be a symlink")
        state = dataset_state(source_root)
        pointer = state.get("current") if isinstance(state.get("current"), dict) else None
        if pointer is None:
            return None
        snapshot_id = pointer.get("snapshot_id") if isinstance(pointer, dict) else None
        if not isinstance(snapshot_id, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
            raise IntegrityError("Analytics snapshot pointer has an invalid identity")
        base = source_root / "snapshots"
        snapshot_dir = base / snapshot_id
        if base.is_symlink() or snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
            raise IntegrityError("Current Analytics snapshot directory is missing or unsafe")
        try:
            snapshot_dir.relative_to(self.paths.datasets)
        except ValueError as exc:
            raise IntegrityError("Current Analytics snapshot escaped the data root") from exc
        manifest_path = snapshot_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise IntegrityError("Current Analytics snapshot manifest is missing or unsafe")
        manifest = self._read_json(manifest_path, maximum_bytes=2 * 1024 * 1024)
        if manifest.get("snapshot_id") != snapshot_id or manifest.get("state") != "READY":
            raise IntegrityError("Current Analytics snapshot manifest does not match its pointer")
        manifest_source = str(manifest.get("source_name") or "")
        if manifest_source.casefold() != source_name.casefold():
            raise IntegrityError("Current Analytics snapshot source does not match its pointer")
        manifest_workspace = str(manifest.get("workspace_identity") or "")
        if workspace_identity and manifest_workspace != workspace_identity:
            return None
        names = manifest.get("files")
        if not isinstance(names, list) or len(names) > 100_000:
            raise IntegrityError("Analytics snapshot file inventory is invalid")
        file_bytes = manifest.get("file_bytes", {})
        file_hashes = manifest.get("file_sha256", {})
        if not isinstance(file_bytes, dict) or not isinstance(file_hashes, dict):
            raise IntegrityError("Analytics snapshot file inventory is invalid")
        files: list[Path] = []
        for name in names:
            if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name or "\\" in name:
                raise IntegrityError("Analytics snapshot contains an invalid data file path")
            file_path = snapshot_dir / name
            if file_path.is_symlink() or not file_path.is_file():
                raise IntegrityError("Analytics snapshot data file is missing or unsafe")
            expected_size = file_bytes.get(name)
            if isinstance(expected_size, int) and file_path.stat().st_size != expected_size:
                raise IntegrityError("Analytics snapshot data file size does not match its manifest")
            expected_hash = file_hashes.get(name)
            if expected_hash is not None:
                if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
                    raise IntegrityError("Analytics snapshot data file hash is invalid")
                digest = hashlib.sha256()
                with file_path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != expected_hash:
                    raise IntegrityError("Analytics snapshot data file hash does not match its manifest")
            files.append(file_path)
        if not files:
            raise IntegrityError("Analytics snapshot does not contain Parquet data")
        with self.store.transaction() as db:
            row = db.execute("SELECT state FROM materializations WHERE materialization_id=?",
                             (snapshot_id,)).fetchone()
        if row is None or row["state"] != "READY":
            return None
        return {"snapshot_id": snapshot_id, "snapshot_dir": snapshot_dir,
                "manifest": manifest, "files": tuple(files), "dataset_root": source_root,
                "workspace_identity": manifest_workspace, "state": state}

    def publish_dataset_record(self, current: dict[str, Any], state: str = "LOCAL_CURRENT") -> None:
        """Repair the SQLite summary from the filesystem publication record."""
        manifest = current["manifest"]
        workspace_identity = str(manifest.get("workspace_identity") or "")
        if not workspace_identity:
            return
        snapshot_state = current.get("state") if isinstance(current.get("state"), dict) else {}
        previous = snapshot_state.get("previous") if isinstance(snapshot_state.get("previous"), dict) else {}
        self.store.local_dataset_put({
            "dataset_id": dataset_identity(workspace_identity, str(manifest["source_name"])),
            "workspace_identity": workspace_identity,
            "source_name": str(manifest["source_name"]),
            "columns_mode": str(manifest.get("columns_mode") or
                                 ("ALL" if manifest.get("all_columns") else "SELECTED")),
            "selected_columns": (manifest.get("selected_columns") if isinstance(
                manifest.get("selected_columns"), list) else
                [] if manifest.get("all_columns") else manifest.get("columns", [])),
            "rows_mode": str(manifest.get("rows_mode") or
                              ("FILTERED" if manifest.get("predicate") else "FULL")),
            "predicate": str(manifest.get("predicate") or ""),
            "schema_identity": str(manifest.get("schema_identity") or ""),
            "source_version": str(manifest.get("source_version") or ""),
            "freshness": str(manifest.get("freshness") or "UNKNOWN"),
            "state": state,
            "current_generation": current["snapshot_id"],
            "previous_generation": str(previous.get("snapshot_id") or ""),
            "previous_expires_at": str(previous.get("expires_at") or ""),
            "row_count": int(manifest.get("row_count") or 0),
            "size_bytes": int(manifest.get("parquet_bytes") or manifest.get("bytes") or 0),
        })

    def mark_invalid(self, current: dict[str, Any], reason: str) -> None:
        """Persist that metadata disagrees with the queryable current schema."""
        self.publish_dataset_record(current, state="INVALID")
        _LOG.error(json.dumps({"event": "local_coverage_inconsistency_detected",
                               "source_name": current.get("manifest", {}).get("source_name", ""),
                               "reason_code": "LOCAL_SCHEMA_MISMATCH",
                               "reason": str(reason)[:300]},
                              sort_keys=True, separators=(",", ":")))

    def list_local_datasets(self, workspace_identity: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return one healthy current row per source and self-heal interrupted metadata writes."""
        datasets_by_id: dict[str, tuple[tuple[int, int, int, int, int, int],
                                        dict[str, Any]]] = {}
        if self.paths.datasets.is_symlink():
            raise IntegrityError("Analytics data root must not be a symlink")
        for root in sorted(self.paths.datasets.iterdir() if self.paths.datasets.exists() else []):
            if (root.is_symlink() or not root.is_dir() or root.name.startswith(".") or
                    not re.fullmatch(r"[a-f0-9]{64}", root.name)):
                continue
            try:
                with dataset_lock(root, exclusive=True):
                    state = dataset_state(root)
                    state, removed = self._prune_generations(root, state, workspace_identity)
                    if removed:
                        self.store.materialization_delete(removed)
                    current_pointer = state.get("current")
                    if not isinstance(current_pointer, dict):
                        continue
                    snapshot_id = current_pointer.get("snapshot_id")
                    if not isinstance(snapshot_id, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
                        continue
                    snapshot_dir = root / "snapshots" / snapshot_id
                    manifest_path = snapshot_dir / "manifest.json"
                    if (snapshot_dir.is_symlink() or not snapshot_dir.is_dir() or
                            manifest_path.is_symlink() or not manifest_path.is_file()):
                        continue
                    manifest = self._read_json(manifest_path, maximum_bytes=2 * 1024 * 1024)
                    source_name = str(manifest.get("source_name") or "")
                    if (manifest.get("workspace_identity") != workspace_identity or not source_name or
                            root.name not in {source_key(source_name, workspace_identity), source_key(source_name)}):
                        continue
                    current = self._read_current(root, source_name, workspace_identity)
                    if current is None:
                        continue
                    dataset_id = dataset_identity(workspace_identity, source_name)
                    # Legacy and workspace-scoped roots can both contain a safe
                    # copy. Keep the broader copy, preferring the scoped root on
                    # equal coverage to match query routing deterministically.
                    rank = (*self._dataset_breadth(current),
                            int(root.name == source_key(source_name, workspace_identity)))
                    previous = datasets_by_id.get(dataset_id)
                    if previous is None or rank > previous[0]:
                        stored = self.store.local_dataset_get(dataset_id)
                        # Do not turn a schema mismatch back into READY merely
                        # because a metadata listing saw the unchanged manifest.
                        if not stored or str(stored.get("state") or "").upper() != "INVALID":
                            self.publish_dataset_record(current)
                        datasets_by_id[dataset_id] = (rank, current)
            except (IntegrityError, OSError, ValueError):
                continue
        rows = []
        for dataset_id, (_rank, current) in datasets_by_id.items():
            manifest = current["manifest"]
            stored = self.store.local_dataset_get(dataset_id)
            data_state = ("INVALID" if stored and str(stored.get("state") or "").upper() == "INVALID"
                          else "READY")
            rows.append({"dataset_id": dataset_id,
                         "workspace_identity": workspace_identity,
                         "source_name": str(manifest["source_name"]),
                         "state": data_state, "snapshot_id": current["snapshot_id"],
                         "columns": (manifest.get("columns", []) if str(
                             manifest.get("columns_mode") or "").upper() == "ALL" else
                             manifest.get("selected_columns", manifest.get("columns", []))),
                         "columns_mode": manifest.get("columns_mode") or
                             ("ALL" if manifest.get("all_columns") else "SELECTED"),
                         "rows_mode": manifest.get("rows_mode") or
                             ("FILTERED" if manifest.get("predicate") else "FULL"),
                         "predicate": manifest.get("predicate", ""),
                         "rows": manifest.get("row_count", 0),
                         "bytes": manifest.get("parquet_bytes", manifest.get("bytes", 0)),
                         "updated_at": manifest.get("created_at", "")})
        return rows[:max(1, min(limit, 500))]

    def _prune_generations(self, root: Path, state: dict[str, Any],
                           workspace_identity: str) -> tuple[dict[str, Any], list[str]]:
        """Expire one prior generation and terminal staging folders under an exclusive lock."""
        current = state.get("current") if isinstance(state.get("current"), dict) else None
        previous = state.get("previous") if isinstance(state.get("previous"), dict) else None
        keep = {str(item.get("snapshot_id")) for item in (current, previous) if isinstance(item, dict)}
        removed: list[str] = []
        snapshots = root / "snapshots"
        source_name = ""
        current_id = str(current.get("snapshot_id") or "") if current else ""
        if re.fullmatch(r"[a-f0-9]{64}", current_id) and not snapshots.is_symlink():
            current_manifest = snapshots / current_id / "manifest.json"
            if current_manifest.is_file() and not current_manifest.is_symlink():
                try:
                    current_record = self._read_json(current_manifest, maximum_bytes=2 * 1024 * 1024)
                    if current_record.get("workspace_identity") == workspace_identity:
                        source_name = str(current_record.get("source_name") or "")
                except IntegrityError:
                    pass
        if previous:
            expired = False
            try:
                expires = time.strptime(str(previous.get("expires_at") or ""), "%Y-%m-%dT%H:%M:%SZ")
                expired = expires <= time.gmtime()
            except ValueError:
                expired = True
            if expired:
                snapshot_id = str(previous.get("snapshot_id") or "")
                if source_name and re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
                    self._remove_generation(snapshots, snapshot_id, workspace_identity,
                                            source_name, removed)
                    if removed:
                        _LOG.info(json.dumps({"event": "local_previous_generation_expired",
                                              "source_name": source_name,
                                              "workspace_identity": workspace_identity},
                                             sort_keys=True, separators=(",", ":")))
                previous = None
                keep.discard(snapshot_id)
        staging_ids = state.get("staging") if isinstance(state.get("staging"), list) else []
        retained_staging = []
        for operation_id in staging_ids:
            if not isinstance(operation_id, str) or not re.fullmatch(r"[a-f0-9]{64}", operation_id):
                continue
            operation = self.store.operation_get(operation_id)
            operation_plan = operation.payload.get("plan") if operation and isinstance(operation.payload, dict) else None
            if (operation and operation.state.value in {"READY", "FAILED", "CANCELLED"} and
                    isinstance(operation_plan, dict) and
                    operation_plan.get("workspace_identity") == workspace_identity):
                if (not isinstance(operation_plan.get("source_name"), str) or root.name not in {
                        source_key(str(operation_plan.get("source_name")), workspace_identity),
                        source_key(str(operation_plan.get("source_name")))}):
                    retained_staging.append(operation_id)
                    continue
                partial = snapshots / ("." + operation_id + ".partial")
                if partial.is_symlink():
                    continue
                if partial.is_dir():
                    shutil.rmtree(partial)
                continue
            retained_staging.append(operation_id)
        updated = {**state, "version": 1, "current": current,
                   "previous": previous, "staging": retained_staging[-100:]}
        if updated != state:
            atomic_dataset_state(root, updated)
        return updated, removed

    def _remove_generation(self, snapshots: Path, snapshot_id: str,
                           workspace_identity: str, source_name: str, removed: list[str]) -> None:
        if snapshots.is_symlink() or not snapshots.is_dir():
            return
        directory = snapshots / snapshot_id
        if directory.is_symlink() or not directory.is_dir():
            return
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            return
        try:
            manifest = self._read_json(manifest_path, maximum_bytes=2 * 1024 * 1024)
        except IntegrityError:
            return
        if (manifest.get("snapshot_id") == snapshot_id and manifest.get("state") == "READY"
                and manifest.get("workspace_identity") == workspace_identity
                and manifest.get("source_name") == source_name):
            shutil.rmtree(directory)
            removed.append(snapshot_id)

    def covers(self, plan: QueryPlan, *, workspace_identity: str | None = None,
               remote_schema: list[dict[str, Any]] | None = None,
               source_version: str | None = None) -> CoverageDecision:
        current = self.current(plan.source_name, workspace_identity)
        if current is None:
            return CoverageDecision(False, "No local copy exists for this table.", state="NOT_COVERED",
                                    reasons=("missing_dataset",))
        manifest = current["manifest"]
        if not manifest.get("complete"):
            return CoverageDecision(False, "The local snapshot is partial and cannot prove complete query coverage.",
                                    snapshot_id=current["snapshot_id"], state="PARTIALLY_COVERED",
                                    reasons=("missing_rows",))
        intent_mode = str(manifest.get("columns_mode") or
                          ("ALL" if manifest.get("all_columns") else "SELECTED")).upper()
        schema_changed = False
        actual_schema_identity = schema_identity(remote_schema) if remote_schema is not None else ""
        saved_table_schema = str(manifest.get("source_schema_identity") or
                                 (manifest.get("schema_identity") if intent_mode == "ALL" else "") or "")
        if remote_schema is not None:
            if intent_mode == "ALL":
                if not saved_table_schema:
                    return CoverageDecision(False, "The local copy has no verified table schema identity.",
                                            snapshot_id=current["snapshot_id"], state="UNKNOWN",
                                            reasons=("schema_identity_missing",))
                schema_changed = saved_table_schema != actual_schema_identity
                if schema_changed:
                    return CoverageDecision(False, "The remote table schema changed; update the local copy.",
                                            snapshot_id=current["snapshot_id"], state="STALE",
                                            reasons=("schema_changed",))
            else:
                physical_columns = manifest.get("columns")
                if not isinstance(physical_columns, list):
                    physical_columns = []
                remote_by_name = {str(item.get("name") or "").casefold(): item
                                  for item in remote_schema if isinstance(item, dict)}
                missing_schema_columns = [str(name) for name in physical_columns
                                          if str(name).casefold() not in remote_by_name]
                if missing_schema_columns:
                    return CoverageDecision(False,
                                            "A column used by the local copy no longer exists in the remote table.",
                                            tuple(missing_schema_columns[:100]), current["snapshot_id"],
                                            "STALE", ("schema_changed",))
                selected_schema = [remote_by_name[str(name).casefold()] for name in physical_columns]
                saved_selected_schema = str(manifest.get("selected_schema_identity") or
                                            manifest.get("schema_identity") or "")
                typed_selected_schema = (selected_schema if selected_schema and all(
                    item.get("type_text") or item.get("type_name") or item.get("type")
                    for item in selected_schema) else None)
                if saved_selected_schema and typed_selected_schema:
                    if schema_identity(typed_selected_schema) != saved_selected_schema:
                        return CoverageDecision(False,
                                                "A selected local column changed type; update the local copy.",
                                                (), current["snapshot_id"], "STALE", ("schema_changed",))
                    if saved_table_schema:
                        # A new unrelated column may update table metadata. Keep
                        # selected coverage valid only when its stored types
                        # still match the remote schema.
                        schema_changed = saved_table_schema != actual_schema_identity
        saved_version = str(manifest.get("source_version") or "")
        if (source_version and saved_version and source_version not in {"UNVERIFIED", "UNKNOWN"}
                and saved_version not in {"UNVERIFIED", "UNKNOWN"} and source_version != saved_version):
            if not (intent_mode == "SELECTED" and schema_changed):
                return CoverageDecision(False, "The source data changed; update the local copy before using it.",
                                        snapshot_id=current["snapshot_id"], state="STALE",
                                        reasons=("source_version_changed",))
        available = manifest.get("columns")
        if not isinstance(available, list):
            available = []
        all_columns = bool(manifest.get("all_columns"))
        all_columns = all_columns or intent_mode == "ALL"
        requirements = getattr(plan, "requirements", None)
        requires_all_columns = (requirements.requires_all_columns if requirements else
                                plan.projection == ("*",))
        if requires_all_columns:
            missing: tuple[str, ...] = () if all_columns else ("*",)
        else:
            available_names = {str(name).casefold() for name in available}
            requested = (requirements.required_columns if requirements else plan.projection)
            required_columns = (*requested, *predicate_columns(plan.predicate))
            missing = tuple(dict.fromkeys(name for name in required_columns
                                          if name.casefold() not in available_names))
        if missing:
            reason = ("The local snapshot contains only selected columns." if missing == ("*",) else
                      "The local snapshot is missing requested column(s): " +
                      ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "."))
            return CoverageDecision(False, reason,
                                    missing, current["snapshot_id"], "PARTIALLY_COVERED",
                                    ("missing_columns",))
        local_predicate = str(manifest.get("predicate") or "")
        if not predicates_cover(local_predicate, plan.predicate):
            return CoverageDecision(False, "The local row coverage cannot prove this filter is contained.",
                                    (), current["snapshot_id"], "PARTIALLY_COVERED",
                                    ("missing_rows", "unsupported_predicate"))
        freshness = ("CURRENT" if source_version not in {"", "UNVERIFIED", "UNKNOWN"} and
                     saved_version == source_version else "UNKNOWN")
        state = "FULLY_COVERED" if freshness == "CURRENT" else "UNKNOWN"
        reason = ("The local copy covers the requested source, columns and rows." if freshness == "CURRENT"
                  else "The local copy covers this request; source freshness could not be verified.")
        return CoverageDecision(True, reason, (), current["snapshot_id"], state,
                                ("freshness_unknown",) if freshness == "UNKNOWN" else ())

    def plan_materialization(self, *, source_name: str, workspace_identity: str,
                             projection: tuple[str, ...] | list[str], predicate: str = "",
                             source_version: str = "", remote_schema: list[dict[str, Any]] | None = None,
                             rows_mode: str | None = None) -> CoveragePlan:
        current = self.current(source_name, workspace_identity)
        if current is None:
            return CoveragePlan("REMATERIALIZE", "No local copy exists for this table.")
        columns = tuple(projection)
        request = QueryPlan("", source_name, columns, predicate)
        decision = self.covers(request, workspace_identity=workspace_identity,
                               remote_schema=remote_schema, source_version=source_version or None)
        if not decision.covered:
            if decision.state == "STALE":
                return CoveragePlan("REFRESH", decision.reason, current["snapshot_id"])
            return CoveragePlan("REMATERIALIZE", decision.reason, current["snapshot_id"])
        manifest = current["manifest"]
        requested_mode = "ALL" if columns == ("*",) else "SELECTED"
        stored_mode = str(manifest.get("columns_mode") or
                          ("ALL" if manifest.get("all_columns") else "SELECTED")).upper()
        requested_rows = rows_mode or ("FILTERED" if predicate.strip() else "FULL")
        stored_rows = str(manifest.get("rows_mode") or
                          ("FILTERED" if str(manifest.get("predicate") or "").strip() else "FULL")).upper()
        stored_columns = {str(value).casefold() for value in manifest.get("columns", [])
                          if isinstance(value, str)}
        requested_columns = {str(value).casefold() for value in columns if value != "*"}
        projection_reuse = (requested_mode == "SELECTED" and
                            (stored_mode == "ALL" or stored_columns > requested_columns))
        filters_differ = (self._normalize(str(manifest.get("predicate") or "")) !=
                          self._normalize(predicate))
        filter_reuse = (requested_rows == "FILTERED" and
                        (stored_rows == "FULL" or (stored_rows == "FILTERED" and filters_differ)))
        if projection_reuse and filter_reuse:
            return CoveragePlan("REUSE_WITH_PROJECTION_AND_FILTER",
                                "The local copy covers these columns and rows; Anvil can apply the requested projection and filter.",
                                current["snapshot_id"], False)
        if projection_reuse:
            return CoveragePlan("REUSE_WITH_PROJECTION",
                                "The existing local copy already contains these columns.",
                                current["snapshot_id"], False)
        if filter_reuse:
            return CoveragePlan("REUSE_WITH_FILTER",
                                "The existing local copy contains the requested rows.",
                                current["snapshot_id"], False)
        if (stored_mode == requested_mode and stored_rows == requested_rows and
                self._normalize(str(manifest.get("predicate") or "")) == self._normalize(predicate)):
            return CoveragePlan("REUSE_LOCAL", "The existing local copy already matches this request.",
                                current["snapshot_id"], False)
        return CoveragePlan("REUSE_LOCAL", decision.reason, current["snapshot_id"], False)

    def snapshot_for(self, source_name: str, workspace_identity: str | None = None) -> dict[str, Any] | None:
        return self.current(source_name, workspace_identity)

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip())

    @staticmethod
    def _read_json(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
        try:
            if path.stat().st_size > maximum_bytes:
                raise IntegrityError("Analytics snapshot metadata exceeds its size limit")
            value = json.loads(path.read_text(encoding="utf-8"))
        except IntegrityError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IntegrityError("Analytics snapshot metadata is unreadable") from exc
        if not isinstance(value, dict):
            raise IntegrityError("Analytics snapshot metadata is invalid")
        return value


def predicates_cover(local_predicate: str, requested_predicate: str) -> bool:
    """Prove only exact or simple AND-composed scalar range/equality containment."""
    local = LocalCoverageService._normalize(local_predicate)
    requested = LocalCoverageService._normalize(requested_predicate)
    if not local:
        return True
    if local == requested:
        return True
    if not requested:
        return False
    local_terms = _simple_predicates(local)
    request_terms = _simple_predicates(requested)
    if local_terms is None or request_terms is None:
        return False
    return all(any(_implies(request, constraint) for request in request_terms)
               for constraint in local_terms)


def _simple_predicates(value: str) -> tuple[tuple[str, str, tuple[str, Any]], ...] | None:
    try:
        from .planner import tokenize
        tokens = tokenize(value)
    except Exception:
        return None
    groups: list[list[Any]] = [[]]
    for token in tokens:
        if token.depth != 0:
            return None
        if token.kind == "word" and token.value == "and":
            if not groups[-1]:
                return None
            groups.append([])
        else:
            groups[-1].append(token)
    if not groups[-1] or len(groups) > 32:
        return None
    parsed: list[tuple[str, str, tuple[str, Any]]] = []
    for group in groups:
        index = 0
        if len(group) < 3 or group[0].kind not in {"word", "identifier"}:
            return None
        column = str(group[0].value).casefold()
        index += 1
        if index + 1 < len(group) and group[index].kind == "symbol" and group[index].value in {
                "=", "!=", "<>", ">", ">=", "<", "<="}:
            operator = str(group[index].value)
            index += 1
        else:
            return None
        type_hint = ""
        if index + 1 < len(group) and group[index].kind == "word" and group[index].value in {"date", "timestamp"}:
            type_hint = group[index].value
            index += 1
        if index >= len(group):
            return None
        literal_tokens = group[index:]
        if len(literal_tokens) != 1:
            return None
        literal = literal_tokens[0]
        if literal.kind == "literal":
            kind, value = type_hint or "string", literal.value
        elif literal.kind == "number":
            try:
                from decimal import Decimal
                kind, value = "number", Decimal(literal.value)
            except Exception:
                return None
        elif literal.kind == "word" and literal.value in {"true", "false", "null"}:
            kind, value = "boolean" if literal.value != "null" else "null", literal.value
        else:
            return None
        parsed.append((column, operator, (kind, value)))
    return tuple(parsed)


def _implies(request: tuple[str, str, tuple[str, Any]],
             local: tuple[str, str, tuple[str, Any]]) -> bool:
    request_column, request_operator, request_value = request
    local_column, local_operator, local_value = local
    if request_column != local_column or request_value[0] != local_value[0]:
        return False
    kind = request_value[0]
    if kind not in {"number", "date", "timestamp"}:
        return request_operator == local_operator == "=" and request_value[1] == local_value[1]
    left, right = request_value[1], local_value[1]
    try:
        if local_operator == "=":
            return request_operator == "=" and left == right
        if request_operator == "=":
            return ((local_operator == ">=" and left >= right) or
                    (local_operator == ">" and left > right) or
                    (local_operator == "<=" and left <= right) or
                    (local_operator == "<" and left < right))
        if request_operator in {">", ">="} and local_operator in {">", ">="}:
            if left > right:
                return True
            if left < right:
                return False
            return request_operator == ">" or local_operator == ">="
        if request_operator in {"<", "<="} and local_operator in {"<", "<="}:
            if left < right:
                return True
            if left > right:
                return False
            return request_operator == "<" or local_operator == "<="
    except (TypeError, ValueError):
        return False
    return False


# Keep the original import name available for callers in the v2.17 API.
CoverageRegistry = LocalCoverageService
