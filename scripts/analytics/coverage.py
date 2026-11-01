"""Exact, conservative coverage checks for published Parquet snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .paths import AnalyticsPaths
from .planner import QueryPlan
from .store import ContextStore


@dataclass(frozen=True)
class CoverageDecision:
    covered: bool
    reason: str
    missing_columns: tuple[str, ...] = ()
    snapshot_id: str = ""


def source_key(source_name: str) -> str:
    return hashlib.sha256(source_name.encode("utf-8")).hexdigest()


class CoverageRegistry:
    def __init__(self, paths: AnalyticsPaths, store: ContextStore) -> None:
        self.paths = paths
        self.store = store

    def pointer_path(self, source_name: str) -> Path:
        return self.paths.datasets / source_key(source_name) / "current.json"

    def current(self, source_name: str) -> dict[str, Any] | None:
        pointer_path = self.pointer_path(source_name)
        source_root = pointer_path.parent
        if self.paths.datasets.is_symlink():
            raise IntegrityError("Analytics data root must not be a symlink")
        if source_root.is_symlink() or pointer_path.is_symlink():
            raise IntegrityError("Analytics snapshot pointer must not be a symlink")
        if not pointer_path.is_file():
            return None
        pointer = self._read_json(pointer_path, maximum_bytes=64 * 1024)
        snapshot_id = pointer.get("snapshot_id")
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
        if manifest.get("source_name") != source_name:
            raise IntegrityError("Current Analytics snapshot source does not match its pointer")
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
                "manifest": manifest, "files": tuple(files)}

    def covers(self, plan: QueryPlan) -> CoverageDecision:
        current = self.current(plan.source_name)
        if current is None:
            return CoverageDecision(False, "No local snapshot exists for this source.")
        manifest = current["manifest"]
        if not manifest.get("complete"):
            return CoverageDecision(False, "The local snapshot is partial and cannot prove complete query coverage.",
                                    snapshot_id=current["snapshot_id"])
        snapshot_predicate = self._normalize(str(manifest.get("predicate") or ""))
        query_predicate = self._normalize(plan.predicate)
        if snapshot_predicate and snapshot_predicate != query_predicate:
            return CoverageDecision(False, "The local snapshot filter does not match the requested filter.",
                                    snapshot_id=current["snapshot_id"])
        available = manifest.get("columns")
        if not isinstance(available, list):
            available = []
        all_columns = bool(manifest.get("all_columns"))
        if plan.projection == ("*",):
            missing: tuple[str, ...] = () if all_columns else ("*",)
        else:
            available_names = {str(name).casefold() for name in available}
            missing = tuple(name for name in plan.projection
                            if name.casefold() not in available_names)
        if missing:
            return CoverageDecision(False, "The local snapshot does not include all requested columns.",
                                    missing, current["snapshot_id"])
        return CoverageDecision(True, "The local snapshot covers the requested source, columns and filter.",
                                (), current["snapshot_id"])

    def snapshot_for(self, source_name: str) -> dict[str, Any] | None:
        return self.current(source_name)

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
