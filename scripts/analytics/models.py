"""Small, dependency-free Analytics domain contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class QueryRoute(str, Enum):
    AUTO = "AUTO"
    LOCAL = "LOCAL"
    DATABRICKS = "DATABRICKS"


class MaterializationState(str, Enum):
    PLANNED = "PLANNED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    VALIDATING = "VALIDATING"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CatalogObjectType(str, Enum):
    CATALOG = "CATALOG"
    SCHEMA = "SCHEMA"
    TABLE = "TABLE"
    VIEW = "VIEW"


@dataclass(frozen=True)
class CatalogObject:
    full_name: str
    object_type: CatalogObjectType
    workspace_id: str = ""
    parent_name: str = ""
    comment: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    columns: tuple[dict[str, Any], ...] = ()
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeItem:
    kind: str
    subject: str
    content: str
    confidence: float = 1.0
    source: str = "user"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryRecord:
    sql: str
    fingerprint: str
    route: QueryRoute
    status: str
    latency_ms: int = 0
    row_count: int | None = None
    byte_count: int | None = None
    error_code: str = ""
    source_objects: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    kind: str
    state: MaterializationState
    payload: dict[str, Any] = field(default_factory=dict)
    checkpoint: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
