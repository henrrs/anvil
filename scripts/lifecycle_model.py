"""Read-only, typed boundary for persisted lifecycle state.

The documents here describe *observed* state. They never repair or write it.
Each consumer can distinguish absence, legacy data, invalid data and a newer
schema without guessing from an empty dictionary.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class DocumentStatus(str, Enum):
    NOT_PRESENT = "NOT_PRESENT"
    CURRENT = "CURRENT"
    LEGACY = "LEGACY"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class Document:
    status: DocumentStatus
    schema_version: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class InstallationState:
    document: Document
    product_version: str | None = None
    runtime_version: str | None = None
    runtime_major: int | None = None
    binary: str | None = None
    managed_manifest_sha256: str | None = None


@dataclass(frozen=True)
class ManagedManifestState:
    document: Document
    product_version: str | None = None
    owned_files: int = 0


@dataclass(frozen=True)
class RuntimeState:
    document: Document
    executable: str | None = None
    version: str | None = None
    generation: int | None = None
    adapter: str | None = None


@dataclass(frozen=True)
class AnalyticsSessionState:
    document: Document
    canonical_session_present: bool = False
    runtime_generation: int | None = None


@dataclass(frozen=True)
class DatabricksState:
    document: Document
    configured: bool = False
    provider: str | None = None
    readiness: str | None = None


@dataclass(frozen=True)
class MemoryState:
    document: Document
    source_manifests: int = 0


@dataclass(frozen=True)
class PersistedState:
    """Normalized on-disk state domains; only safe facts are exposed."""

    installation: InstallationState
    managed_manifest: ManagedManifestState
    runtime: RuntimeState
    analytics_session: AnalyticsSessionState
    databricks: DatabricksState
    memory: MemoryState

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read(path: Path) -> tuple[Any, Document | None]:
    if path.is_symlink():
        return None, Document(DocumentStatus.INVALID, reason="symbolic link")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, Document(DocumentStatus.NOT_PRESENT)
    except (OSError, UnicodeError):
        return None, Document(DocumentStatus.INVALID, reason="unreadable file")
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, Document(DocumentStatus.INVALID, reason="invalid JSON")


def _object(path: Path, current_schema: int) -> tuple[dict[str, Any], Document]:
    value, failure = _read(path)
    if failure is not None:
        return {}, failure
    if not isinstance(value, dict):
        return {}, Document(DocumentStatus.LEGACY, reason="legacy non-object JSON")
    schema = value.get("schema_version", 1)
    if type(schema) is not int or schema < 1:
        return {}, Document(DocumentStatus.INVALID, reason="invalid schema version")
    if schema > current_schema:
        return {}, Document(DocumentStatus.UNSUPPORTED, schema, "newer schema version")
    return value, Document(DocumentStatus.CURRENT if schema == current_schema else DocumentStatus.LEGACY, schema)


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _major(value: Any) -> int | None:
    return value if type(value) is int and value in (1, 2) else None


def normalize_installation(path: Path) -> InstallationState:
    value, document = _object(path, 3)
    return InstallationState(document, _string(value.get("anvil_version")),
                             _string(value.get("version")),
                             _major(value.get("runtime_major", value.get("generation"))),
                             _string(value.get("binary", value.get("binary_path"))),
                             _string(value.get("managed_config_manifest_sha256")))


def normalize_managed_manifest(path: Path) -> ManagedManifestState:
    value, document = _object(path, 1)
    files = value.get("files")
    if value and not isinstance(files, dict):
        document = Document(DocumentStatus.INVALID, document.schema_version, "invalid managed files inventory")
    return ManagedManifestState(document, _string(value.get("anvil_version")), len(files) if isinstance(files, dict) else 0)


def normalize_runtime(path: Path) -> RuntimeState:
    value, document = _object(path, 1)
    runtime = value.get("runtime", value)
    if not isinstance(runtime, dict):
        return RuntimeState(Document(DocumentStatus.INVALID, document.schema_version, "invalid runtime record"))
    return RuntimeState(document, _string(runtime.get("executable")), _string(runtime.get("version")),
                        _major(runtime.get("generation")), _string(runtime.get("adapter")))


def normalize_analytics_session(path: Path) -> AnalyticsSessionState:
    value, document = _object(path, 1)
    return AnalyticsSessionState(document, bool(_string(value.get("canonical_session_id"))),
                                 _major(value.get("runtime_generation")))


def normalize_databricks(path: Path) -> DatabricksState:
    value, document = _object(path, 3)
    profile = value.get("profile")
    readiness = value.get("readiness")
    if profile is not None and not isinstance(profile, dict):
        document = Document(DocumentStatus.INVALID, document.schema_version, "invalid profile record")
    if readiness is not None and not isinstance(readiness, dict):
        document = Document(DocumentStatus.INVALID, document.schema_version, "invalid readiness record")
    provider = readiness.get("provider") if isinstance(readiness, dict) else None
    return DatabricksState(document, bool(_string(value.get("selected_profile")) or
                                           (isinstance(profile, dict) and _string(profile.get("name")))),
                            _string(provider.get("selected")) if isinstance(provider, dict) else None,
                            _string(readiness.get("overall")) if isinstance(readiness, dict) else None)


def normalize_memory(path: Path) -> MemoryState:
    if path.is_symlink():
        return MemoryState(Document(DocumentStatus.INVALID, reason="symbolic link"))
    if not path.exists():
        return MemoryState(Document(DocumentStatus.NOT_PRESENT))
    if not path.is_dir():
        return MemoryState(Document(DocumentStatus.INVALID, reason="not a directory"))
    registry = path / "sources"
    return MemoryState(Document(DocumentStatus.CURRENT), sum(1 for _ in registry.glob("*.json")) if registry.is_dir() else 0)


def resolve_persisted(home: Path, config_home: Path, data_home: Path) -> PersistedState:
    anvil_data = data_home / "anvil"
    return PersistedState(
        normalize_installation(anvil_data / "installation.json"),
        normalize_managed_manifest(config_home / "opencode" / ".anvil-managed.json"),
        normalize_runtime(anvil_data / "runtime.json"),
        normalize_analytics_session(home / ".anvil" / "analytics" / "runtime.json"),
        normalize_databricks(config_home / "anvil" / "databricks.json"),
        normalize_memory(anvil_data / "memory"),
    )
