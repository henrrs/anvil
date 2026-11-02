#!/usr/bin/env python3
"""Capture and restore the facts needed to verify lifecycle rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analytics_service  # noqa: E402
import analytics_schema  # noqa: E402
import runtime_state  # noqa: E402

UNIT_NAME = analytics_service.SERVICE_NAME
UNIT_MARKER = analytics_service.MARKER


def _hash(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _atomic_copy(source: Path, destination: Path, mode: int) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"baseline artifact is missing or unsafe: {source.name}")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".baseline.", dir=destination.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream, source.open("rb") as original:
            shutil.copyfileobj(original, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _atomic_bytes(destination: Path, payload: bytes, mode: int) -> None:
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".baseline-restore.", dir=destination.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("snapshot has no verified pre-operation baseline")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("snapshot pre-operation baseline has an unsupported format")
    return value


def capture(args: argparse.Namespace) -> None:
    backup = args.backup.absolute()
    artifact_dir = backup / "lifecycle-baseline"
    artifact_dir.mkdir(mode=0o700, exist_ok=True)
    config = args.config_dir.absolute()
    install = args.installation.absolute()
    runtime_state_file = args.analytics_runtime_state.absolute()
    context_database = runtime_state_file.parent / "context.db"
    systemd_dir = args.systemd_dir.absolute()
    unit = systemd_dir / UNIT_NAME
    port = args.port

    record: dict[str, Any]
    try:
        record = json.loads(install.read_text(encoding="utf-8")) if install.is_file() else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        record = {}
    if not isinstance(record, dict):
        record = {}
    managed_manifest = config / ".anvil-managed.json"
    manifest_hash = _hash(managed_manifest)

    runtime_observation = runtime_state.discover(args.binary).get("runtime") or {}
    runtime_observation = runtime_observation if isinstance(runtime_observation, dict) else {}
    lock = config / "runtime" / "analytics-requirements.lock"
    active_runtime_path: str | None = None
    dependencies_ready: bool | None = None
    if lock.is_file() and not lock.is_symlink():
        try:
            import analytics_dependencies
            active_runtime = analytics_dependencies.runtime_path(lock, args.data_root, args.python)
            active_runtime_path = str(active_runtime)
            _, packages = analytics_dependencies.parse_lock(lock)
            dependencies_ready = analytics_dependencies._validate(active_runtime / "bin" / "python", packages)
        except (OSError, ValueError, RuntimeError):
            dependencies_ready = False
    else:
        dependencies_ready = None

    service = analytics_service.service_state(config, args.home, systemd_dir, port)
    unit_owned = (unit.is_file() and not unit.is_symlink()
                  and UNIT_MARKER in unit.read_text(encoding="utf-8", errors="replace"))
    unit_hash = _hash(unit)
    unit_mode = stat.S_IMODE(unit.stat().st_mode) if unit_owned else None
    unit_symlink = os.readlink(unit) if unit.is_symlink() else None
    if unit_owned:
        _atomic_copy(unit, artifact_dir / "analytics-service.unit", unit_mode or 0o600)

    runtime_present = runtime_state_file.is_file() and not runtime_state_file.is_symlink()
    runtime_hash = _hash(runtime_state_file) if runtime_present else None
    runtime_mode = stat.S_IMODE(runtime_state_file.stat().st_mode) if runtime_present else None
    runtime_symlink = os.readlink(runtime_state_file) if runtime_state_file.is_symlink() else None
    if runtime_present:
        _atomic_copy(runtime_state_file, artifact_dir / "analytics-runtime.json", runtime_mode or 0o600)
    database_baseline = analytics_schema.capture_rollback_state(context_database, artifact_dir)

    runtime_saved: dict[str, Any] = {}
    if runtime_present:
        try:
            parsed = json.loads(runtime_state_file.read_text(encoding="utf-8"))
            runtime_saved = parsed if isinstance(parsed, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            runtime_saved = {}
    opencode = {
        "status": "READY" if runtime_observation.get("usable") and runtime_observation.get("supported") else
                  "NOT_FOUND" if not runtime_observation.get("executable") else "NOT_READY",
        "executable": runtime_observation.get("executable"),
        "version": runtime_observation.get("version"),
        "generation": runtime_observation.get("generation"),
    }
    baseline = {
        "schema_version": 1,
        "product_release": record.get("anvil_version"),
        "managed_manifest_sha256": manifest_hash,
        "configuration_present": config.is_dir(),
        "configuration_profile_sha256": _hash(config / "opencode.jsonc") if config.is_dir() else None,
        "opencode_runtime": opencode,
        "analytics": {
            "service": {key: service.get(key) for key in ("installed", "unit_installed", "enabled",
                                                            "active", "healthy", "status")},
            "systemd_manager": analytics_service._is_active_user_unit_dir(systemd_dir, args.home)
                               and analytics_service._systemd_available(),
            "service_unit": {"owned": unit_owned, "present": unit_owned,
                             "sha256": unit_hash, "mode": unit_mode,
                             "symlink_target": unit_symlink},
            "runtime_json": {"present": runtime_present, "sha256": runtime_hash,
                             "mode": runtime_mode, "symlink_target": runtime_symlink},
            "runtime_record": {
                "canonical_session": "PRESENT" if runtime_saved.get("canonical_session_id") else "NOT_CREATED",
                "base_url_present": bool(runtime_saved.get("base_url")),
                "executable": runtime_saved.get("executable") or None,
                "version": runtime_saved.get("version") or None,
                "generation": runtime_saved.get("runtime_generation"),
            },
            "dependency_runtime": active_runtime_path,
            "dependencies_ready": dependencies_ready,
            "context_database": database_baseline,
        },
        "artifacts": {
            "service_unit": "lifecycle-baseline/analytics-service.unit" if unit_owned else None,
            "runtime_json": "lifecycle-baseline/analytics-runtime.json" if runtime_present else None,
            "context_database": database_baseline.get("artifact"),
        },
    }
    baseline_path = artifact_dir / "pre-operation-state.json"
    baseline_path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    baseline_path.chmod(0o600)
    print(json.dumps({"baseline": str(baseline_path), "opencode": opencode,
                      "analytics_service": service.get("status"),
                      "dependency_runtime": active_runtime_path}, sort_keys=True))


def _systemctl(*args: str) -> bool:
    try:
        result = subprocess.run(["systemctl", "--user", *args], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def restore(args: argparse.Namespace) -> dict[str, Any]:
    baseline = _load(args.backup / "lifecycle-baseline" / "pre-operation-state.json")
    analytics = baseline["analytics"]
    service_before = analytics["service"]
    systemd_dir = args.systemd_dir.absolute()
    unit = systemd_dir / UNIT_NAME
    config = args.config_dir.absolute()
    unit_artifact = args.backup / "lifecycle-baseline" / "analytics-service.unit"
    runtime_artifact = args.backup / "lifecycle-baseline" / "analytics-runtime.json"
    runtime_state_file = args.analytics_runtime_state.absolute()
    port = args.port

    if analytics.get("systemd_manager"):
        _systemctl("stop", UNIT_NAME)
    else:
        analytics_service._stop_fallback(args.home, port)

    if systemd_dir.is_symlink() or (systemd_dir.exists() and not systemd_dir.is_dir()):
        raise ValueError("Analytics service unit directory became unsafe during rollback")
    current_managed_unit = (unit.is_file() and not unit.is_symlink()
                            and UNIT_MARKER in unit.read_text(encoding="utf-8", errors="replace"))
    if analytics["service_unit"]["present"]:
        if unit_artifact.is_symlink() or not unit_artifact.is_file():
            raise ValueError("verified Analytics service unit snapshot artifact is missing")
        if unit.is_symlink() or (unit.exists() and not current_managed_unit):
            raise ValueError("refusing to replace an unsafe or user-owned Analytics service unit")
        _atomic_copy(unit_artifact, unit, int(analytics["service_unit"].get("mode") or 0o600))
    elif current_managed_unit:
        unit.unlink()

    if analytics["runtime_json"].get("symlink_target") is not None:
        if runtime_state_file.exists() and not runtime_state_file.is_symlink():
            if not runtime_state_file.is_file():
                raise ValueError("Analytics runtime state became a non-file during rollback")
            runtime_state_file.unlink()
        elif runtime_state_file.is_symlink():
            runtime_state_file.unlink()
        runtime_state_file.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        runtime_state_file.symlink_to(str(analytics["runtime_json"]["symlink_target"]))
    elif analytics["runtime_json"]["present"]:
        if runtime_artifact.is_symlink() or not runtime_artifact.is_file():
            raise ValueError("verified Analytics runtime state snapshot artifact is missing")
        _atomic_copy(runtime_artifact, runtime_state_file, int(analytics["runtime_json"].get("mode") or 0o600))
    elif runtime_state_file.exists() or runtime_state_file.is_symlink():
        if runtime_state_file.is_symlink():
            raise ValueError("Analytics runtime state became a symbolic link during rollback")
        runtime_state_file.unlink()

    database_baseline = analytics.get("context_database")
    if isinstance(database_baseline, dict):
        analytics_schema.restore_rollback_state(
            database_baseline, args.backup / "lifecycle-baseline",
            runtime_state_file.parent / "context.db")

    if analytics.get("systemd_manager"):
        if not _systemctl("daemon-reload"):
            raise ValueError("systemd user manager could not reload the restored Analytics unit")
        if service_before.get("enabled"):
            if not _systemctl("enable", UNIT_NAME):
                raise ValueError("could not restore the baseline Analytics service enablement")
        else:
            _systemctl("disable", UNIT_NAME)
        if service_before.get("active"):
            if not unit.is_file() or not current_managed_unit and not analytics["service_unit"]["present"]:
                raise ValueError("baseline Analytics service was active but its managed unit is missing")
            if not _systemctl("set-environment", "ANVIL_ANALYTICS_NO_BOOTSTRAP=1"):
                raise ValueError("could not set no-bootstrap mode for baseline service restoration")
            try:
                if not _systemctl("start", UNIT_NAME):
                    raise ValueError("could not restore the baseline Analytics service active state")
            finally:
                _systemctl("unset-environment", "ANVIL_ANALYTICS_NO_BOOTSTRAP")
    elif service_before.get("active"):
        python = analytics_service._service_runtime(config, args.home, require_ready=False)
        analytics_service._start_fallback(config, args.home, port, python, no_bootstrap=True)
    else:
        analytics_service._stop_fallback(args.home, port)

    return {"baseline": baseline, "service": service_before}


def verify(args: argparse.Namespace, *, strict_configuration: bool = False) -> dict[str, Any]:
    baseline = _load(args.backup / "lifecycle-baseline" / "pre-operation-state.json")
    errors: list[str] = []
    config = args.config_dir.absolute()
    record_path = args.installation.absolute()
    record: dict[str, Any] = {}
    try:
        value = json.loads(record_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            record = value
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    if baseline.get("product_release") != record.get("anvil_version"):
        errors.append("product release differs from the captured baseline")
    if bool(baseline.get("configuration_present")) != config.is_dir():
        errors.append("configuration directory presence differs from the captured baseline")
    manifest_hash = _hash(config / ".anvil-managed.json") if config.is_dir() else None
    if baseline.get("managed_manifest_sha256") != manifest_hash:
        errors.append("managed configuration manifest differs from the captured baseline")
    profile_hash = _hash(config / "opencode.jsonc") if config.is_dir() else None
    if strict_configuration and baseline.get("configuration_profile_sha256") != profile_hash:
        errors.append("OpenCode configuration profile differs from the captured baseline")

    runtime = runtime_state.discover(args.binary).get("runtime") or {}
    runtime = runtime if isinstance(runtime, dict) else {}
    expected_runtime = baseline.get("opencode_runtime") or {}
    actual_status = ("READY" if runtime.get("usable") and runtime.get("supported") else
                     "NOT_FOUND" if not runtime.get("executable") else "NOT_READY")
    for key, actual in (("status", actual_status), ("executable", runtime.get("executable")),
                        ("version", runtime.get("version")), ("generation", runtime.get("generation"))):
        if expected_runtime.get(key) != actual:
            errors.append(f"OpenCode runtime {key} differs from the captured baseline")

    analytics = baseline["analytics"]
    lock = config / "runtime" / "analytics-requirements.lock"
    actual_dependency_runtime: str | None = None
    actual_dependencies_ready: bool | None = None
    if lock.is_file() and not lock.is_symlink():
        try:
            import analytics_dependencies
            runtime = analytics_dependencies.runtime_path(
                lock, Path(os.environ.get("XDG_DATA_HOME", args.home / ".local" / "share")).expanduser())
            actual_dependency_runtime = str(runtime)
            _, packages = analytics_dependencies.parse_lock(lock)
            actual_dependencies_ready = analytics_dependencies._validate(runtime / "bin" / "python", packages)
        except (OSError, ValueError, RuntimeError):
            actual_dependencies_ready = False
    if analytics.get("dependency_runtime") != actual_dependency_runtime:
        errors.append("Analytics runtime pointer differs from the captured baseline")
    if analytics.get("dependencies_ready") != actual_dependencies_ready:
        errors.append("Analytics dependency readiness differs from the captured baseline")

    runtime_record = analytics["runtime_json"]
    actual_runtime_hash = _hash(args.analytics_runtime_state)
    if runtime_record.get("sha256") != actual_runtime_hash:
        errors.append("Analytics runtime state bytes differ from the captured baseline")
    actual_runtime_symlink = (os.readlink(args.analytics_runtime_state)
                              if args.analytics_runtime_state.is_symlink() else None)
    if runtime_record.get("symlink_target") != actual_runtime_symlink:
        errors.append("Analytics runtime state link differs from the captured baseline")
    database_baseline = analytics.get("context_database")
    if isinstance(database_baseline, dict):
        try:
            analytics_schema.verify_restored_state(database_baseline,
                                                   args.analytics_runtime_state.parent / "context.db")
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    unit_record = analytics["service_unit"]
    unit = args.systemd_dir / UNIT_NAME
    actual_unit_hash = _hash(unit) if unit.is_file() and not unit.is_symlink() else None
    if unit_record.get("sha256") != actual_unit_hash:
        errors.append("Analytics service unit bytes differ from the captured baseline")
    actual_unit_symlink = os.readlink(unit) if unit.is_symlink() else None
    if unit_record.get("symlink_target") != actual_unit_symlink:
        errors.append("Analytics service unit link differs from the captured baseline")
    actual_service = analytics_service.service_state(config, args.home, args.systemd_dir, args.port)
    for key in ("installed", "unit_installed", "enabled", "active", "healthy"):
        expected = analytics["service"].get(key)
        if bool(actual_service.get(key)) != bool(expected):
            errors.append(f"Analytics service {key} differs from the captured baseline")

    degraded = (expected_runtime.get("status") != "READY"
                or analytics["service"].get("status") != "READY"
                or analytics["runtime_record"].get("canonical_session") == "NOT_CREATED")
    return {"status": "RESTORATION_FAILED" if errors else
            "RESTORED_DEGRADED_BASELINE" if degraded else "RESTORED",
            "errors": errors, "product_release": baseline.get("product_release"),
            "opencode_runtime": expected_runtime, "analytics_service": analytics["service"],
            "canonical_session": analytics["runtime_record"]["canonical_session"]}


def verify_migration_plan(backup: Path, target_config: Path) -> dict[str, Any]:
    """Prove the target schema transition has its declared rollback input before activation."""
    baseline = _load(backup / "lifecycle-baseline" / "pre-operation-state.json")
    target_config = target_config.absolute()
    if not (target_config / "scripts" / "analytics" / "store.py").is_file():
        return {"status": "NOT_APPLICABLE", "reason": "target release has no Analytics control store"}
    state = baseline.get("analytics", {}).get("context_database")
    if not isinstance(state, dict):
        raise ValueError("snapshot does not record the Analytics schema rollback contract")
    from analytics.store import migration_rollback_policy
    policy = migration_rollback_policy(int(state.get("schema_version", -1)))
    if policy["status"] != "READY" or policy["policy"] != state.get("rollback_policy"):
        raise ValueError("target Analytics schema has no matching safe rollback contract")
    if policy.get("restore_required"):
        analytics_schema.verify_snapshot(state, backup / "lifecycle-baseline" / "context.db")
    return {"status": "PASS", "source_schema": state.get("schema_version"),
            "target_schema": state.get("target_schema_version"), "policy": state.get("rollback_policy"),
            "restore_required": state.get("restore_required")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p_capture = sub.add_parser("capture")
    p_capture.add_argument("--backup", type=Path, required=True)
    p_capture.add_argument("--config-dir", type=Path, required=True)
    p_capture.add_argument("--home", type=Path, required=True)
    p_capture.add_argument("--data-root", type=Path, required=True)
    p_capture.add_argument("--installation", type=Path, required=True)
    p_capture.add_argument("--analytics-runtime-state", type=Path, required=True)
    p_capture.add_argument("--systemd-dir", type=Path, required=True)
    p_capture.add_argument("--binary", default=None)
    p_capture.add_argument("--python", default=sys.executable)
    p_capture.add_argument("--port", type=int, default=8765)
    for action in ("restore", "verify"):
        item = sub.add_parser(action)
        item.add_argument("--backup", type=Path, required=True)
        item.add_argument("--config-dir", type=Path, required=True)
        item.add_argument("--home", type=Path, required=True)
        item.add_argument("--installation", type=Path, required=True)
        item.add_argument("--analytics-runtime-state", type=Path, required=True)
        item.add_argument("--systemd-dir", type=Path, required=True)
        item.add_argument("--binary", default=None)
        item.add_argument("--operation-id", default="")
        item.add_argument("--port", type=int, default=8765)
        if action == "verify":
            item.add_argument("--strict-configuration", action="store_true")
    p_migration = sub.add_parser("verify-plan")
    p_migration.add_argument("--backup", type=Path, required=True)
    p_migration.add_argument("--target-config", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "capture":
            capture(args)
        elif args.action == "verify-plan":
            result = verify_migration_plan(args.backup, args.target_config)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif args.action == "restore":
            print(json.dumps(restore(args), ensure_ascii=False, sort_keys=True))
        else:
            result = verify(args, strict_configuration=args.strict_configuration)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            if result["status"] == "RESTORATION_FAILED":
                for reason in result["errors"]:
                    print(f"  {reason}", file=sys.stderr)
                return 1
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"ERROR LIFECYCLE_BASELINE: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
