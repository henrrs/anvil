#!/usr/bin/env python3
"""Durable marker for lifecycle changes that need snapshot-based recovery."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def paths() -> tuple[Path, Path]:
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().absolute()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser().absolute()
    root = data_home / "anvil"
    return root / "lifecycle-transaction.json", root / "backups"


@contextmanager
def _transaction_lock():
    journal, _ = paths()
    journal.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(journal.parent, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read() -> dict[str, Any] | None:
    journal, _ = paths()
    if not journal.exists():
        return None
    value = json.loads(journal.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("lifecycle transaction journal has an unsupported shape")
    return value


def inspect() -> dict[str, Any]:
    journal, backup_root = paths()
    try:
        value = _read()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {"pending": True, "valid": False, "journal": str(journal), "error": str(exc)}
    if value is None:
        return {"pending": False, "valid": True, "journal": str(journal)}
    owner_pid = value.get("owner_pid")
    owner_active = False
    if isinstance(owner_pid, int) and owner_pid > 0:
        try:
            os.kill(owner_pid, 0)
            owner_active = True
        except ProcessLookupError:
            pass
        except PermissionError:
            owner_active = True
    backup_text = value.get("backup")
    backup = Path(backup_text).expanduser().absolute() if isinstance(backup_text, str) and backup_text else None
    backup_valid = False
    backup_error = "journal has no snapshot path"
    if backup is not None:
        try:
            resolved_root = backup_root.resolve(strict=False)
            resolved_backup = backup.resolve(strict=True)
            if resolved_backup == resolved_root or resolved_root not in resolved_backup.parents:
                raise ValueError("snapshot is outside the current Anvil backup root")
            import state
            state.verify(resolved_backup)
            backup_valid = True
            backup_error = ""
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            backup_error = str(exc)
    return {**value, "pending": True, "valid": True, "owner_active": owner_active, "journal": str(journal),
            "backup_valid": backup_valid, "backup_error": backup_error}


def _write(value: dict[str, Any]) -> None:
    journal, _ = paths()
    journal.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(journal.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".lifecycle-transaction.", dir=journal.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, journal)
        directory_fd = os.open(journal.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def begin(operation: str, backup: str, source: str, target: str, owner_pid: int) -> None:
    with _transaction_lock():
        if _read() is not None:
            raise ValueError("another lifecycle transaction is already pending recovery")
        data = {"schema_version": 1, "operation": operation, "backup": str(Path(backup).absolute()),
                "source_version": source or None, "target_version": target or None,
                "owner_pid": owner_pid,
                "phase": "snapshot-verified", "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _write(data)


def phase(value: str) -> None:
    with _transaction_lock():
        current = _read()
        if current is None:
            raise ValueError("cannot update a missing lifecycle transaction journal")
        current["phase"] = value
        current["updated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write(current)


def clear() -> None:
    journal, _ = paths()
    with _transaction_lock():
        journal.unlink(missing_ok=True)
        if journal.parent.is_dir():
            directory_fd = os.open(journal.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("inspect")
    p_begin = sub.add_parser("begin")
    p_begin.add_argument("--operation", required=True)
    p_begin.add_argument("--backup", required=True)
    p_begin.add_argument("--source-version", default="")
    p_begin.add_argument("--target-version", default="")
    p_begin.add_argument("--owner-pid", type=int, default=os.getppid())
    p_phase = sub.add_parser("phase")
    p_phase.add_argument("value")
    sub.add_parser("clear")
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            print(json.dumps(inspect(), ensure_ascii=False))
        elif args.action == "begin":
            begin(args.operation, args.backup, args.source_version, args.target_version, args.owner_pid)
        elif args.action == "phase":
            phase(args.value)
        else:
            clear()
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR LIFECYCLE_TRANSACTION: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
