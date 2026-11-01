"""SQLite WAL context store for Analytics control-plane state."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import IntegrityError, ValidationError
from .models import (CatalogObject, KnowledgeItem, MaterializationState,
                     OperationRecord, QueryRecord)
from .paths import AnalyticsPaths

SCHEMA_VERSION = 1


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Analytics metadata must be JSON serializable") from exc


class ContextStore:
    """Own durable metadata only; datasets and SQL execution live elsewhere."""

    def __init__(self, database: Path | str | None = None,
                 paths: AnalyticsPaths | None = None) -> None:
        self.paths = paths or AnalyticsPaths.discover(create=True)
        self.database = Path(database).expanduser().absolute() if database else self.paths.database
        try:
            self.database.relative_to(self.paths.root)
        except ValueError as exc:
            raise IntegrityError("Context database must remain under the Analytics root") from exc
        if self.database.is_symlink():
            raise IntegrityError("Context database must not be a symlink")
        if not self.database.parent.exists():
            self.database.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.paths.secure_directory(self.database.parent)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.database.is_symlink():
            raise IntegrityError("Context database must not be a symlink")
        for suffix in ("-wal", "-shm"):
            if Path(str(self.database) + suffix).is_symlink():
                raise IntegrityError("SQLite sidecar files must not be symlinks")
        connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
        finally:
            connection.close()
            if self.database.exists():
                self.paths.secure_file(self.database)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(self.database) + suffix)
                if sidecar.exists() and not sidecar.is_symlink() and sidecar.is_file():
                    sidecar.chmod(0o600)

    def _migrate(self) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                current = int(db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0])
                if current > SCHEMA_VERSION:
                    raise IntegrityError("Analytics database was created by a newer Anvil version")
                if current < 1:
                    self._migration_1(db)
                    db.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(1, ?)", (_now(),))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    @staticmethod
    def _migration_1(db: sqlite3.Connection) -> None:
        statements = ("""
            CREATE TABLE catalog_objects (
                full_name TEXT PRIMARY KEY,
                object_type TEXT NOT NULL,
                workspace_id TEXT NOT NULL DEFAULT '',
                parent_name TEXT NOT NULL DEFAULT '',
                comment TEXT NOT NULL DEFAULT '',
                properties_json TEXT NOT NULL DEFAULT '{}',
                columns_json TEXT NOT NULL DEFAULT '[]',
                source_updated_at TEXT NOT NULL DEFAULT '',
                cached_at TEXT NOT NULL
            );
            CREATE INDEX catalog_objects_parent ON catalog_objects(parent_name, object_type);
            CREATE TABLE knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(kind, subject, content)
            );
            CREATE INDEX knowledge_subject ON knowledge(subject, updated_at DESC);
            CREATE TABLE query_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sql_text TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                route TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                row_count INTEGER,
                byte_count INTEGER,
                status TEXT NOT NULL,
                error_code TEXT NOT NULL DEFAULT '',
                source_objects_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX query_history_recent ON query_history(created_at DESC);
            CREATE TABLE materializations (
                materialization_id TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_version TEXT NOT NULL DEFAULT '',
                filters_json TEXT NOT NULL DEFAULT '[]',
                columns_json TEXT NOT NULL DEFAULT '[]',
                coverage_json TEXT NOT NULL DEFAULT '{}',
                state TEXT NOT NULL,
                files_json TEXT NOT NULL DEFAULT '[]',
                byte_count INTEGER NOT NULL DEFAULT 0,
                principal TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_code TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE runtime_sessions (
                session_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                parent_session_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'ACTIVE'
            );
            CREATE INDEX runtime_sessions_role ON runtime_sessions(role, updated_at DESC);
            CREATE TABLE investigations (
                investigation_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                state TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE operations (
                operation_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                state TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                checkpoint_json TEXT NOT NULL,
                error_code TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        # sqlite3.executescript() commits an open transaction first. Execute the
        # migration as one statement inside the caller's BEGIN IMMEDIATE instead.
        for statement in statements.split(";"):
            if statement.strip():
                db.execute(statement)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def catalog_upsert(self, objects: list[CatalogObject]) -> int:
        if not objects:
            return 0
        now = _now()
        with self.transaction() as db:
            db.executemany("""
                INSERT INTO catalog_objects(full_name, object_type, workspace_id, parent_name,
                    comment, properties_json, columns_json, source_updated_at, cached_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(full_name) DO UPDATE SET object_type=excluded.object_type,
                    workspace_id=excluded.workspace_id, parent_name=excluded.parent_name,
                    comment=excluded.comment, properties_json=excluded.properties_json,
                    columns_json=excluded.columns_json, source_updated_at=excluded.source_updated_at,
                    cached_at=excluded.cached_at
            """, [(o.full_name, o.object_type.value, o.workspace_id, o.parent_name,
                   o.comment, _json(o.properties), _json(o.columns), o.updated_at, now)
                  for o in objects])
        return len(objects)

    def catalog_list(self, *, parent: str = "", object_type: str | None = None,
                     limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
        if not 1 <= limit <= 2000 or type(offset) is not int or not 0 <= offset <= 10_000_000:
            raise ValidationError("Catalog page size or offset is invalid")
        sql = "SELECT * FROM catalog_objects WHERE parent_name=?"
        params: list[Any] = [parent]
        if object_type:
            sql += " AND object_type=?"
            params.append(object_type.upper())
        sql += " ORDER BY full_name LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [{**dict(row), "properties": json.loads(row["properties_json"]),
                 "columns": json.loads(row["columns_json"])} for row in rows]

    def catalog_search(self, term: str, *, parent: str = "", limit: int = 100) -> tuple[list[dict[str, Any]], bool]:
        """Search every cached UC object while bounding returned rows."""
        if not term.strip() or len(term) > 256 or len(parent) > 768 or not 1 <= limit <= 200:
            raise ValidationError("Catalog search term or result limit is invalid")
        escaped_term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_term}%"
        sql = r"SELECT * FROM catalog_objects WHERE (full_name LIKE ? ESCAPE '\' OR comment LIKE ? ESCAPE '\')"
        params: list[Any] = [pattern, pattern]
        if parent:
            escaped_parent = parent.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += r" AND (full_name=? OR full_name LIKE ? ESCAPE '\')"
            params.extend((parent, escaped_parent + ".%"))
        sql += " ORDER BY full_name LIMIT ?"
        params.append(limit + 1)
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        truncated = len(rows) > limit
        values = rows[:limit]
        return ([{**dict(row), "properties": json.loads(row["properties_json"]),
                  "columns": json.loads(row["columns_json"])} for row in values], truncated)

    def knowledge_add(self, item: KnowledgeItem) -> int:
        if not item.kind.strip() or not item.subject.strip() or not item.content.strip():
            raise ValidationError("Knowledge kind, subject and content are required")
        if not 0 <= item.confidence <= 1:
            raise ValidationError("Knowledge confidence must be between 0 and 1")
        now = _now()
        with self.transaction() as db:
            db.execute("""
                INSERT INTO knowledge(kind, subject, content, confidence, source, tags_json, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(kind, subject, content) DO UPDATE SET confidence=excluded.confidence,
                    source=excluded.source, tags_json=excluded.tags_json, updated_at=excluded.updated_at
            """, (item.kind, item.subject, item.content, item.confidence, item.source,
                  _json(item.tags), now, now))
            row = db.execute("SELECT id FROM knowledge WHERE kind=? AND subject=? AND content=?",
                             (item.kind, item.subject, item.content)).fetchone()
        return int(row[0])

    def knowledge_recent(self, *, subject: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ValidationError("Knowledge limit must be between 1 and 200")
        sql = "SELECT * FROM knowledge"
        params: list[Any] = []
        if subject is not None:
            sql += " WHERE subject=?"
            params.append(subject)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [{**dict(row), "tags": json.loads(row["tags_json"])} for row in rows]

    def query_record(self, record: QueryRecord) -> int:
        if record.latency_ms < 0 or (record.row_count is not None and record.row_count < 0):
            raise ValidationError("Query metrics must not be negative")
        with self.transaction() as db:
            cursor = db.execute("""
                INSERT INTO query_history(sql_text, fingerprint, created_at, route, latency_ms,
                    row_count, byte_count, status, error_code, source_objects_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (record.sql, record.fingerprint, _now(), record.route.value,
                  record.latency_ms, record.row_count, record.byte_count, record.status,
                  record.error_code, _json(record.source_objects)))
            return int(cursor.lastrowid)

    def query_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValidationError("Query history limit must be between 1 and 500")
        with self._connect() as db:
            rows = db.execute("SELECT * FROM query_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "source_objects": json.loads(row["source_objects_json"])} for row in rows]

    def investigation_put(self, investigation_id: str, title: str, state: str,
                          summary: str = "", session_id: str = "") -> None:
        values = (investigation_id, title, state)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValidationError("Investigation ID, title and state are required")
        if not isinstance(summary, str) or not isinstance(session_id, str):
            raise ValidationError("Investigation summary and session reference must be text")
        if any(len(value) > limit for value, limit in ((investigation_id, 256), (title, 160),
                                                       (state, 40), (summary, 6000), (session_id, 256))):
            raise ValidationError("Investigation metadata exceeds its size limit")
        with self.transaction() as db:
            db.execute("""
                INSERT INTO investigations(investigation_id,title,state,summary,session_id,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(investigation_id) DO UPDATE SET title=excluded.title,
                    state=excluded.state, summary=excluded.summary, session_id=excluded.session_id,
                    updated_at=excluded.updated_at
            """, (investigation_id.strip(), title.strip(), state.strip().upper(),
                  summary.strip(), session_id.strip(), _now()))

    def investigation_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValidationError("Investigation limit must be between 1 and 100")
        with self._connect() as db:
            rows = db.execute("SELECT investigation_id,title,state,summary,session_id,updated_at "
                              "FROM investigations ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def materialization_put(self, value: dict[str, Any]) -> None:
        required = ("materialization_id", "source_name", "state")
        if any(not isinstance(value.get(key), str) or not value[key].strip() for key in required):
            raise ValidationError("Materialization identity, source and state are required")
        state = value["state"].upper()
        if state not in {item.value for item in MaterializationState}:
            raise ValidationError("Materialization state is invalid")
        byte_count = value.get("byte_count", 0)
        if not isinstance(byte_count, int) or byte_count < 0:
            raise ValidationError("Materialization byte count must not be negative")
        now = _now()
        with self.transaction() as db:
            db.execute("""
                INSERT INTO materializations(materialization_id,source_name,source_version,
                    filters_json,columns_json,coverage_json,state,files_json,byte_count,principal,
                    created_at,updated_at,error_code)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(materialization_id) DO UPDATE SET source_name=excluded.source_name,
                    source_version=excluded.source_version, filters_json=excluded.filters_json,
                    columns_json=excluded.columns_json, coverage_json=excluded.coverage_json,
                    state=excluded.state, files_json=excluded.files_json,
                    byte_count=excluded.byte_count, principal=excluded.principal,
                    updated_at=excluded.updated_at, error_code=excluded.error_code
            """, (value["materialization_id"], value["source_name"],
                  str(value.get("source_version", ""))[:200],
                  _json(value.get("filters", [])), _json(value.get("columns", [])),
                  _json(value.get("coverage", {})), state, _json(value.get("files", [])),
                  byte_count, str(value.get("principal", ""))[:256], now, now,
                  str(value.get("error_code", ""))[:100]))

    def materialization_get(self, materialization_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM materializations WHERE materialization_id=?",
                             (materialization_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        for column, key in (("filters_json", "filters"), ("columns_json", "columns"),
                            ("coverage_json", "coverage"), ("files_json", "files")):
            value[key] = json.loads(value.pop(column))
        return value

    def materialization_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValidationError("Materialization limit must be between 1 and 500")
        with self._connect() as db:
            rows = db.execute("SELECT * FROM materializations ORDER BY updated_at DESC LIMIT ?",
                              (limit,)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            for column, key in (("filters_json", "filters"), ("columns_json", "columns"),
                                ("coverage_json", "coverage"), ("files_json", "files")):
                value[key] = json.loads(value.pop(column))
            result.append(value)
        return result

    def operation_put(self, record: OperationRecord) -> None:
        now = _now()
        with self.transaction() as db:
            db.execute("""
                INSERT INTO operations(operation_id, kind, state, payload_json, checkpoint_json,
                    error_code, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(operation_id) DO UPDATE SET state=excluded.state,
                    payload_json=excluded.payload_json, checkpoint_json=excluded.checkpoint_json,
                    error_code=excluded.error_code, updated_at=excluded.updated_at
            """, (record.operation_id, record.kind, record.state.value, _json(record.payload),
                  _json(record.checkpoint), record.error_code, now, now))

    def operation_get(self, operation_id: str) -> OperationRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        return OperationRecord(row["operation_id"], row["kind"],
                               MaterializationState(row["state"]),
                               json.loads(row["payload_json"]),
                               json.loads(row["checkpoint_json"]), row["error_code"])

    def operation_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValidationError("Operation limit must be between 1 and 500")
        with self._connect() as db:
            rows = db.execute("SELECT operation_id,kind,state,payload_json,checkpoint_json,error_code,updated_at "
                              "FROM operations ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"]),
                 "checkpoint": json.loads(row["checkpoint_json"])} for row in rows]
