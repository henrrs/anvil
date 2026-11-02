#!/usr/bin/env python3
"""Safe rollback support for the lifecycle-owned Analytics SQLite control store."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from analytics.store import SCHEMA_VERSION, migration_rollback_policy


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")


def _schema_version(connection: sqlite3.Connection) -> int:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
    if table is None:
        return 0
    return int(connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0])


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = path.absolute().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def inspect_database(database: Path) -> dict[str, Any]:
    database = database.expanduser().absolute()
    _reject_symlink(database, "Analytics context database")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        _reject_symlink(sidecar, "SQLite sidecar")
        if sidecar.exists() and not sidecar.is_file():
            raise ValueError("SQLite sidecar must be a regular file")
    if not database.exists():
        return {"present": False, "schema_version": 0, "integrity": "NOT_PRESENT"}
    if not database.is_file():
        raise ValueError("Analytics context database is not a regular file")
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect_readonly(database)
        integrity = str(connection.execute("PRAGMA quick_check(1)").fetchone()[0]).lower()
        if integrity != "ok":
            raise ValueError("Analytics context database failed SQLite quick_check")
        version = _schema_version(connection)
    except (sqlite3.Error, OSError) as exc:
        raise ValueError("Analytics context database could not be inspected safely") from exc
    finally:
        if connection is not None:
            connection.close()
    return {"present": True, "schema_version": version, "integrity": integrity}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_database(source: Path, destination: Path) -> None:
    _reject_symlink(source, "Analytics context database")
    _reject_symlink(destination, "SQLite rollback snapshot")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if destination.exists():
        raise ValueError("SQLite rollback snapshot destination already exists")
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = _connect_readonly(source)
        target_connection = sqlite3.connect(destination, timeout=10)
        source_connection.backup(target_connection)
        target_connection.commit()
    except sqlite3.Error as exc:
        raise ValueError("SQLite backup API could not create a consistent rollback snapshot") from exc
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
    destination.chmod(0o600)
    observed = inspect_database(destination)
    expected = inspect_database(source)
    if not observed["present"] or observed["schema_version"] != expected["schema_version"]:
        raise ValueError("SQLite rollback snapshot does not match the source schema")


def capture_rollback_state(database: Path, artifact_dir: Path, *, target_schema: int = SCHEMA_VERSION) -> dict[str, Any]:
    observed = inspect_database(database)
    policy = migration_rollback_policy(int(observed["schema_version"]), target_schema)
    if policy["status"] != "READY":
        raise ValueError("Analytics schema migration has no safe rollback contract")
    record: dict[str, Any] = {
        **observed,
        "target_schema_version": target_schema,
        "rollback_policy": policy["policy"],
        "migrations": policy["migrations"],
        "restore_required": bool(policy.get("restore_required")),
        "mode": (database.stat().st_mode & 0o777) if observed["present"] else None,
        "backup_sha256": None,
    }
    if record["restore_required"] and observed["present"]:
        backup = artifact_dir / "context.db"
        _backup_database(database, backup)
        record["backup_sha256"] = _sha256(backup)
        record["artifact"] = "lifecycle-baseline/context.db"
    else:
        record["artifact"] = None
    return record


def verify_snapshot(record: dict[str, Any], artifact: Path) -> None:
    if not record.get("restore_required"):
        return
    if not record.get("present"):
        if artifact.exists() or artifact.is_symlink():
            raise ValueError("unexpected SQLite rollback artifact exists for a previously absent database")
        return
    _reject_symlink(artifact, "SQLite rollback snapshot")
    if not artifact.is_file() or _sha256(artifact) != record.get("backup_sha256"):
        raise ValueError("verified SQLite rollback snapshot is missing or has changed")
    observed = inspect_database(artifact)
    if (not observed["present"] or observed["schema_version"] != record.get("schema_version")
            or observed["integrity"] != "ok"):
        raise ValueError("SQLite rollback snapshot failed schema or integrity validation")


def _remove_sidecars(database: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        _reject_symlink(sidecar, "SQLite sidecar")
        if sidecar.exists():
            if not sidecar.is_file():
                raise ValueError("SQLite sidecar must be a regular file")
            sidecar.unlink()


def restore_rollback_state(record: dict[str, Any], artifact_dir: Path, database: Path) -> None:
    """Restore only when the recorded schema migration contract requires it."""
    if not record.get("restore_required"):
        return
    database = database.expanduser().absolute()
    _reject_symlink(database, "Analytics context database")
    for parent in (database.parent, *database.parent.parents):
        if parent.is_symlink():
            raise ValueError("Analytics database parent path must not contain symbolic links")
    database.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not record.get("present"):
        _remove_sidecars(database)
        if database.exists():
            if not database.is_file():
                raise ValueError("Analytics context database is not a regular file")
            database.unlink()
        return

    artifact = artifact_dir / "context.db"
    verify_snapshot(record, artifact)
    fd, temporary_name = tempfile.mkstemp(prefix=".context-rollback.", dir=database.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = _connect_readonly(artifact)
        target_connection = sqlite3.connect(temporary, timeout=10)
        source_connection.backup(target_connection)
        target_connection.commit()
    except sqlite3.Error as exc:
        temporary.unlink(missing_ok=True)
        raise ValueError("SQLite backup API could not restore the pre-operation database") from exc
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
    restored = inspect_database(temporary)
    if not restored["present"] or restored["schema_version"] != record.get("schema_version"):
        temporary.unlink(missing_ok=True)
        raise ValueError("restored SQLite database failed its schema verification")
    temporary.chmod(int(record.get("mode") or 0o600))
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    _remove_sidecars(database)
    os.replace(temporary, database)
    directory_fd = os.open(database.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def verify_restored_state(record: dict[str, Any], database: Path) -> None:
    if not record.get("restore_required"):
        return
    actual = inspect_database(database)
    if bool(actual["present"]) != bool(record.get("present")):
        raise ValueError("Analytics context database presence differs from the pre-operation baseline")
    if record.get("present") and actual.get("schema_version") != record.get("schema_version"):
        raise ValueError("Analytics context database schema differs from the pre-operation baseline")
