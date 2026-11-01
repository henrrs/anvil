"""Canonical and child OpenCode session lifecycle for Analytics."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import fcntl

from .context import ContextResolver
from .errors import ConflictError, IntegrityError, ProviderError, ValidationError
from .models import KnowledgeItem
from .opencode import OpenCodeRuntimePort
from .paths import AnalyticsPaths
from .store import ContextStore

CANONICAL_TITLE = "anvil-global-analytics"


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink():
        raise IntegrityError("Analytics runtime lock must not be a symlink")
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_state(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise IntegrityError("Analytics runtime state must not be a symlink")
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityError("Analytics runtime state is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise IntegrityError("Analytics runtime state has an unsupported format")
    return value


def _write_state(path: Path, value: dict[str, Any], paths: AnalyticsPaths) -> None:
    paths.validate(create=True)
    fd, temporary = tempfile.mkstemp(prefix=".runtime.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        paths.secure_file(path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class AnalyticsSessionManager:
    def __init__(self, runtime: Any, store: ContextStore,
                 *, paths: AnalyticsPaths | None = None,
                 context: ContextResolver | None = None) -> None:
        self.runtime = runtime
        self.store = store
        self.paths = paths or runtime.paths
        self.context = context or ContextResolver(store)

    def ensure_canonical(self) -> dict[str, Any]:
        with exclusive_lock(self.paths.state / "runtime.lock"):
            runtime_state = self.runtime.ensure(lock=False)
            adapter: OpenCodeRuntimePort = self.runtime.adapter
            current = _read_state(self.paths.runtime)
            canonical_id = current.get("canonical_session_id")
            session = adapter.get_session(canonical_id) if isinstance(canonical_id, str) and canonical_id else None
            created = False
            recovered = False
            if not session or session.get("title") != CANONICAL_TITLE:
                session = self._find_canonical(adapter)
                if session is None:
                    session = adapter.create_session(CANONICAL_TITLE)
                    created = True
                else:
                    recovered = True
                canonical_id = str(session["id"])
                adapter.add_context(canonical_id, self.context.rehydration_text())
            else:
                canonical_id = str(session["id"])

            session_id = str(session.get("id") or "")
            if not session_id:
                raise ProviderError("OpenCode returned a canonical session without an identifier")
            self.context.session_record(session_id, role="canonical", title=CANONICAL_TITLE)
            persisted = {
                "schema_version": 1,
                "workspace": str(self.paths.workspace),
                "base_url": runtime_state["base_url"],
                "executable": runtime_state.get("executable", ""),
                "version": runtime_state.get("version", ""),
                "runtime_generation": runtime_state.get("generation"),
                "canonical_session_id": session_id,
                "last_validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _write_state(self.paths.runtime, persisted, self.paths)
            return {"session_id": session_id, "created": created, "recovered": recovered,
                    "workspace": str(self.paths.workspace), "runtime_generation": persisted["runtime_generation"]}

    def recover_canonical(self) -> dict[str, Any]:
        return self.ensure_canonical()

    @staticmethod
    def _find_canonical(adapter: OpenCodeRuntimePort) -> dict[str, Any] | None:
        candidates = [row for row in adapter.list_sessions()
                      if row.get("title") == CANONICAL_TITLE and row.get("id")]
        if not candidates:
            return None
        candidates.sort(key=lambda row: str(row.get("time", {}).get("updated")
                                             if isinstance(row.get("time"), dict)
                                             else row.get("updatedAt", "")), reverse=True)
        return candidates[0]

    def create_task_session(self, title: str = "Analytics investigation") -> dict[str, Any]:
        clean_title = " ".join(title.split())[:120]
        if not clean_title:
            raise ValidationError("Task session title is required")
        if clean_title == CANONICAL_TITLE:
            raise ValidationError("The canonical Analytics session title is reserved")
        canonical = self.ensure_canonical()
        with exclusive_lock(self.paths.state / "runtime.lock"):
            adapter: OpenCodeRuntimePort = self.runtime.adapter
            task = adapter.create_session(clean_title, parent_id=canonical["session_id"])
            task_id = str(task.get("id") or "")
            if not task_id:
                raise ProviderError("OpenCode did not return a task session identifier")
            self.context.session_record(task_id, role="task", title=clean_title,
                                        parent_session_id=canonical["session_id"])
            return {"session_id": task_id, "parent_session_id": canonical["session_id"],
                    "title": clean_title}

    def finish_task_session(self, task_session_id: str, *, summary: str,
                            findings: list[KnowledgeItem] | None = None) -> dict[str, Any]:
        task = self.store_session(task_session_id)
        canonical = _read_state(self.paths.runtime).get("canonical_session_id")
        if not task or task.get("role") != "task" or task.get("parent_session_id") != canonical:
            raise ConflictError("Task session is not a child of the current Analytics session")
        summary = summary.strip()
        if not summary:
            raise ValidationError("A concise task summary is required for distillation")
        items = list(findings or [])
        items.append(KnowledgeItem("investigation", task.get("title", task_session_id), summary,
                                   source="anvil-analytics-task"))
        ids = [self.store.knowledge_add(item) for item in items]
        self.store.investigation_put(task_session_id, task.get("title", "Analytics investigation"),
                                     "COMPLETED", summary, task_session_id)
        with self.store.transaction() as db:
            db.execute("UPDATE runtime_sessions SET state='COMPLETED', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE session_id=?",
                       (task_session_id,))
        return {"session_id": task_session_id, "distilled_items": len(ids), "knowledge_ids": ids}

    def store_session(self, session_id: str) -> dict[str, Any] | None:
        return self.context.session_get(session_id)
