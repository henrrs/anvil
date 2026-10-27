"""Private JSON generations with atomic replacement, locking and revision checks."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterator

from .contracts import MAX_STATE_BYTES, identifier, relative_path, require, safe_content, validate_models
from .errors import EngineeringError
from .repository import identity, no_symlinks


def state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "anvil/engineering"


def task_path(repository: Path, task_id: str) -> Path:
    identifier(task_id)
    return state_root() / identity(repository)["id"] / task_id / "state.json"


def _directory(path: Path) -> None:
    no_symlinks(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Parent Anvil paths may also contain OpenCode state; change only our subtree.
    for item in (path, path.parent, path.parent.parent):
        os.chmod(item, 0o700)


def _encode(value: dict) -> bytes:
    safe_content(value)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    envelope = {"sha256": hashlib.sha256(payload).hexdigest(), "state": value}
    data = (json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    require(len(data) <= MAX_STATE_BYTES * 2, "Serialized engineering state exceeds its size limit.")
    return data


def _validate_evidence_hashes(values: dict) -> None:
    require(isinstance(values, dict), "Missing file observation map.")
    for path, value in values.items():
        relative_path(path)
        require(value is None or (isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)), "Invalid evidence hash.")


def _atomic(path: Path, data: bytes) -> None:
    no_symlinks(path)
    fd, temporary = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validate_state(state: dict) -> None:
    safe_content(state)
    require(state["schema_version"] == 1, "Engineering state uses an unsupported schema; use a compatible helper.", "WORK_STATE_UNSUPPORTED")
    require(type(state["revision"]) is int and state["revision"] >= 1, "Invalid engineering state revision.")
    identifier(state["id"])
    require(state["status"] in {"ACTIVE", "COMPLETE", "ARCHIVED"}, "Invalid project state.")
    validate_models(state["models"])
    require(isinstance(state["verification"], list) and isinstance(state["events"], list), "Missing evidence/history.")
    require(isinstance(state["anchor"]["repository"]["root"], str) and isinstance(state["anchor"]["specification"]["path"], str), "Missing repository/specification anchor.")
    _validate_evidence_hashes(state["anchor"]["files"])
    for record in state["verification"]:
        require(isinstance(record, dict) and record.get("result") in {"PASS", "FAIL", "UNKNOWN"}
                and type(record.get("valid")) is bool and record.get("kind"), "Invalid verification record.")
        identifier(record["id"])
        require(sum(bool(record.get(key)) for key in ("check_id", "invariant_id", "decision_id")) == 1, "Evidence must identify one declared check/invariant/decision.")
        _validate_evidence_hashes(record["files"])


def load(path: Path) -> dict:
    no_symlinks(path)
    try:
        require(path.stat().st_size <= MAX_STATE_BYTES * 2, "State exceeds its size limit.")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        state = envelope["state"]
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        require(hashlib.sha256(payload).hexdigest() == envelope["sha256"], "State checksum mismatch.")
        _validate_state(state)
        return state
    except FileNotFoundError:
        raise EngineeringError("WORK_STATE_MISSING", "No engineering state exists for this task.", "Use the direct workflow or initialize explicit models for a complex task.") from None
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, EngineeringError) and exc.code == "WORK_STATE_UNSUPPORTED":
            raise
        raise EngineeringError("WORK_STATE_CORRUPTED", "Engineering state could not be validated; it was left unchanged.",
                               "Inspect the private state file. Use recover only after reviewing the previous generation; revalidate recovered work.") from exc


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    _directory(path.parent)
    lock_path = path.with_suffix(".lock")
    no_symlinks(lock_path)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def save(path: Path, state: dict, expected_revision: int | None) -> dict:
    with locked(path):
        existing = load(path) if path.exists() else None
        actual = existing["revision"] if existing else None
        require(actual == expected_revision, "Task state changed in another process; reload before updating.", "WORK_STATE_STALE")
        return _publish(path, state, existing)


def _publish(path: Path, state: dict, existing: dict | None) -> dict:
    state = json.loads(json.dumps(state))
    state["revision"] = (existing["revision"] if existing else 0) + 1
    _validate_state(state)
    data = _encode(state)
    if existing:
        _atomic(path.with_suffix(".previous.json"), _encode(existing))
    _atomic(path, data)
    return state


def update(path: Path, expected_revision: int, mutation) -> tuple[dict, object]:
    """Hold the task lock across explicit verification too; stale callers execute nothing."""
    with locked(path):
        state = load(path)
        require(state["revision"] == expected_revision, "Task state changed; reload before executing an update.", "WORK_STATE_STALE")
        previous = json.loads(json.dumps(state))
        result = mutation(state)
        return _publish(path, state, previous), result


def recover(path: Path, expected_revision: int) -> dict:
    with locked(path):
        previous = load(path.with_suffix(".previous.json"))
        require(previous["revision"] == expected_revision, "Previous generation changed; inspect it before recovery.", "WORK_STATE_STALE")
        try:
            load(path)
        except EngineeringError as exc:
            require(exc.code in {"WORK_STATE_CORRUPTED", "WORK_STATE_MISSING"}, "State is not recoverable automatically.")
        else:
            raise EngineeringError("RECOVERY_NOT_NEEDED", "Current state is valid; it was left unchanged.")
        # An explicit recovery never trusts old completion evidence automatically.
        for item in previous["verification"]:
            item["valid"] = False
        previous["status"] = "ACTIVE"
        previous["recovery_required"] = True
        previous["revision"] += 1
        for task in previous["models"]["work"]["tasks"]:
            if task["status"] == "VERIFIED":
                task["status"] = "IMPLEMENTED"
        for requirement in previous["models"]["requirements"]["items"]:
            if requirement["status"] == "VERIFIED":
                requirement["status"] = "IMPLEMENTED"
        from .engine import refresh
        refresh(previous)
        _validate_state(previous)
        _atomic(path, _encode(previous))
        return previous
