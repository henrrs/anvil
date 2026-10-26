#!/usr/bin/env python3
"""Evaluate Anvil-managed installation and rollback state for public commands."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime_state  # noqa: E402
import state as backup_state  # noqa: E402
import managed_config  # noqa: E402
import lifecycle_transaction  # noqa: E402
from semver import compare as compare_versions, parse as parse_version, supported_migration  # noqa: E402


def paths() -> dict[str, Path]:
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().absolute()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser().absolute()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser().absolute()
    return {
        "home": home,
        "config": config_home / "opencode",
        "data": data_home / "anvil",
        "record": data_home / "anvil" / "installation.json",
        "runtime_state": data_home / "anvil" / "runtime.json",
        "install_root": home / ".opencode",
        "install_bin": home / ".opencode" / "bin",
        "managed_binary": home / ".opencode" / "bin" / "opencode",
        "memory": data_home / "anvil" / "memory",
        "backups": data_home / "anvil" / "backups",
    }


def _read_json(path: Path) -> tuple[dict[str, Any] | None, bool]:
    if not path.exists():
        return None, True
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, False
    return (value, isinstance(value, dict))


def _audit_config(path: Path, *, allow_older_skill_set: bool = False) -> int | None:
    if not path.is_file():
        return None
    suffix = "-compatible" if allow_older_skill_set else ""
    for command, major in ((f"audit-v1{suffix}", 1), (f"audit{suffix}", 2)):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "configure.py"), command, str(path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if result.returncode == 0:
            return major
    return 0


def _profile_major(path: Path) -> int | None:
    try:
        config = managed_config.parse_jsonc(path.read_text(encoding="utf-8"), str(path))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict):
        return None
    if isinstance(config.get("agent"), dict) and "anvil" in config["agent"]:
        return 1
    if isinstance(config.get("agents"), dict) and "anvil" in config["agents"]:
        return 2
    return None


def _backup_inventory(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        return {"present": False, "valid_count": 0, "latest": None}
    valid: list[Path] = []
    for candidate in root.iterdir():
        if not candidate.is_dir():
            continue
        try:
            backup_state.verify(candidate)
            valid.append(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    valid.sort(key=lambda item: item.name, reverse=True)
    return {"present": True, "valid_count": len(valid), "latest": str(valid[0]) if valid else None}


def evaluate() -> dict[str, Any]:
    locations = paths()
    version_path = ROOT / "VERSION"
    try:
        repository_version = version_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        repository_version = ""
    repository_valid = parse_version(repository_version) is not None

    record, record_valid = _read_json(locations["record"])
    runtime_saved, runtime_state_valid = _read_json(locations["runtime_state"])
    record_exists = locations["record"].exists()
    runtime_state_exists = locations["runtime_state"].exists()
    config_path = locations["config"] / "opencode.jsonc"
    recorded_version = record.get("anvil_version") if isinstance(record, dict) else None
    recorded_version = recorded_version if isinstance(recorded_version, str) and recorded_version else None
    recorded_version_valid = recorded_version is None or parse_version(recorded_version) is not None
    version_relation = compare_versions(recorded_version, repository_version)
    legacy_unversioned = record_exists and recorded_version is None
    if version_relation is not None and version_relation > 0:
        config_major = _profile_major(config_path)
    else:
        config_major = _audit_config(config_path, allow_older_skill_set=(version_relation != 0))
    runtime_result = runtime_state.discover()
    runtime = runtime_result.get("runtime") or {}
    runtime_usable = bool(runtime.get("usable") and runtime.get("supported"))
    runtime_major = runtime.get("generation")
    config_present = locations["config"].exists() or locations["config"].is_symlink()
    config_valid = config_major in {1, 2}
    managed_binary_present = locations["managed_binary"].exists() or locations["managed_binary"].is_symlink()
    managed_binary_usable = (managed_binary_present
                             and os.access(locations["managed_binary"], os.X_OK)
                             and runtime_usable)
    memory_present = locations["memory"].is_dir()
    backup_inventory = _backup_inventory(locations["backups"])
    managed_config_result: dict[str, Any] | None = None
    managed_config_error: str | None = None
    if config_present and locations["config"].is_dir():
        try:
            managed_config_result = managed_config.validate_installed(
                locations["config"], recorded_version if recorded_version_valid else None, repository_version,
                record.get("managed_config_manifest_sha256") if isinstance(record, dict) else None,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            managed_config_error = str(exc)

    record_shape_valid = not record_exists or (record_valid and isinstance(record, dict))
    runtime_record = (runtime_saved.get("runtime") if isinstance(runtime_saved, dict)
                      and isinstance(runtime_saved.get("runtime"), dict) else runtime_saved)
    runtime_record_valid = (not runtime_state_exists or (runtime_state_valid and isinstance(runtime_record, dict)
                            and isinstance(runtime_record.get("executable"), str)
                            and isinstance(runtime_record.get("version"), str)))

    managed_artifacts = bool(config_present or record_exists or runtime_state_exists
                             or locations["install_root"].exists() or locations["install_root"].is_symlink()
                             or managed_binary_present)
    blockers: list[str] = []
    warnings: list[str] = []
    corrupted = not repository_valid or not record_shape_valid or not runtime_record_valid
    if not repository_valid:
        blockers.append("Repository VERSION is missing or invalid.")
    if not record_shape_valid:
        blockers.append("Anvil installation metadata is malformed.")
    if not runtime_record_valid:
        blockers.append("Anvil runtime metadata is malformed.")
    partial_legacy_config = (not runtime.get("installed") and managed_config_error
                             and managed_config_error.startswith("source profile is missing files required by its own release:"))
    if managed_config_error and not partial_legacy_config:
        corrupted = True
        blockers.append(managed_config_error)
    if config_present and config_major == 0 and not (version_relation is not None and version_relation > 0):
        corrupted = True
        blockers.append("The managed OpenCode config failed Anvil's supported profile audit.")
    unsafe_path = next((path for path in (locations["config"], locations["config"] / "opencode.jsonc",
                                           locations["install_root"], locations["install_bin"])
                        if path.is_symlink()), None)
    if unsafe_path is not None:
        corrupted = True
        blockers.append("A managed config or OpenCode install directory is a symbolic link.")
    if managed_binary_present and (not os.access(locations["managed_binary"], os.X_OK)
                                   or not managed_binary_usable):
        if runtime.get("installed") and not runtime.get("supported"):
            blockers.append("The installed OpenCode runtime is outside Anvil's supported runtime policy.")
        else:
            corrupted = True
            blockers.append("The managed OpenCode executable is not usable under the current runtime policy.")
    if config_valid and runtime_usable and runtime_major != config_major:
        corrupted = True
        blockers.append("The active OpenCode runtime major does not match the managed Anvil config.")

    transaction = ({"pending": False, "valid": True, "postflight": True}
                   if os.environ.get("ANVIL_TRANSACTION_POSTFLIGHT") == "1"
                   else lifecycle_transaction.inspect())
    pending_transaction = transaction.get("pending") is True
    if pending_transaction:
        if transaction.get("owner_active"):
            lifecycle = "TRANSITION_IN_PROGRESS"
            blockers.append("A lifecycle transaction is currently running; wait for it to finish before starting another.")
        else:
            lifecycle = "RECOVERY_REQUIRED"
            blockers.append("A lifecycle transaction was interrupted; its verified snapshot must be restored before other changes.")
            if transaction.get("valid") is not True or transaction.get("backup_valid") is not True:
                blockers.append("The recovery journal or its snapshot failed validation; automatic restore is unavailable.")
    elif corrupted:
        lifecycle = "CORRUPTED"
    elif not managed_artifacts:
        lifecycle = "REPOSITORY_ONLY"
        warnings.append("No Anvil-managed installation state exists in this HOME/XDG environment.")
    elif recorded_version and not recorded_version_valid:
        lifecycle = "UNSUPPORTED"
        blockers.append("The installed Anvil release is not a recognized numeric semantic version.")
    elif version_relation is not None and version_relation > 0:
        lifecycle = "UNSUPPORTED"
        blockers.append(f"Installed Anvil {recorded_version} is newer than checkout {repository_version}; refusing a downgrade.")
    elif runtime.get("installed") and not runtime.get("supported"):
        lifecycle = "UNSUPPORTED"
        blockers.append(f"Installed OpenCode {runtime.get('version') or 'unknown'} is outside the supported runtime policy.")
    elif not config_valid or not runtime_usable:
        lifecycle = "PARTIALLY_INSTALLED"
        if not config_valid:
            blockers.append("A valid managed OpenCode config is not present.")
        if not runtime_usable:
            blockers.append("A supported, usable OpenCode runtime is not available.")
    elif version_relation is not None and version_relation < 0:
        if not supported_migration(recorded_version, repository_version):
            lifecycle = "UNSUPPORTED"
            blockers.append(f"Anvil {recorded_version} is outside the supported migration window for {repository_version}.")
        elif parse_version(recorded_version)[1] == parse_version(repository_version)[1]:
            lifecycle = "STALE"
            warnings.append(f"Anvil {recorded_version} is a supported prior patch release; upgrade to {repository_version} when ready.")
        else:
            lifecycle = "MIGRATION_REQUIRED"
            warnings.append(f"Anvil {recorded_version} is valid for its release and can migrate to {repository_version}.")
            if not memory_present:
                warnings.append("The Anvil memory directory is absent; it will initialize during migration.")
    elif legacy_unversioned:
        lifecycle = "MIGRATION_REQUIRED"
        warnings.append("Installation metadata has no Anvil version; the recognized legacy profile can be migrated.")
    elif not record_exists:
        lifecycle = "MIGRATION_REQUIRED"
        warnings.append("Installation release metadata is missing; the recognized profile can be migrated.")
    elif not memory_present:
        lifecycle = "DEGRADED"
        warnings.append("The Anvil memory directory is absent; memory features will initialize it when needed.")
    elif version_relation == 0:
        lifecycle = "READY"
    else:
        lifecycle = "INSTALLED"

    if not backup_inventory["latest"]:
        warnings.append("No verified rollback snapshot is available yet.")

    return {
        "schema_version": 1,
        "lifecycle": lifecycle,
        "repository": {"version": repository_version or None, "valid": repository_valid},
        "installation": {"managed_artifacts": managed_artifacts,
                          "record_present": record_exists,
                          "recorded_version": recorded_version,
                          "record_valid": record_shape_valid},
        "transition": {"source_version": recorded_version or ("legacy/unrecorded" if legacy_unversioned or not record_exists else None),
                        "target_version": repository_version or None,
                        "version_relation": ("older" if version_relation is not None and version_relation < 0 else
                                             "current" if version_relation == 0 else
                                             "newer" if version_relation is not None and version_relation > 0 else
                                             "unknown"),
                        "migration_required": lifecycle == "MIGRATION_REQUIRED",
                        "upgrade_available": lifecycle in {"STALE", "MIGRATION_REQUIRED"},
                        "migration_supported": (supported_migration(recorded_version, repository_version)
                                                if version_relation is not None and version_relation < 0 else
                                                version_relation == 0)},
        "configuration": {"present": config_present, "valid": config_valid,
                           "runtime_major": config_major or None,
                           "path": str(locations["config"])},
        "managed_config": {"valid": managed_config_error is None and managed_config_result is not None,
                            "manifest_present": bool(managed_config_result and managed_config_result.get("manifest_present")),
                            "owned_files": len(managed_config_result.get("owned_files", [])) if managed_config_result else 0,
                            "user_files": managed_config_result.get("user_files", []) if managed_config_result else [],
                            "error": managed_config_error},
        "transaction": transaction,
        "runtime": {"present": bool(runtime.get("installed")), "usable": runtime_usable,
                    "supported": bool(runtime.get("supported")), "version": runtime.get("version"),
                    "major": runtime_major, "executable": runtime.get("executable"),
                    "path_ready": bool(runtime.get("path_ready"))},
        "memory": {"present": memory_present, "path": str(locations["memory"])},
        "backups": backup_inventory,
        "blockers": blockers,
        "warnings": warnings,
    }


def _human(value: dict[str, Any]) -> str:
    names = {"REPOSITORY_ONLY": "NOT_INSTALLED", "PARTIALLY_INSTALLED": "PARTIALLY_INSTALLED",
             "INSTALLED": "INSTALLED", "READY": "READY", "DEGRADED": "DEGRADED",
             "STALE": "STALE", "MIGRATION_REQUIRED": "MIGRATION_REQUIRED", "UNSUPPORTED": "UNSUPPORTED",
             "TRANSITION_IN_PROGRESS": "TRANSITION_IN_PROGRESS",
             "RECOVERY_REQUIRED": "RECOVERY_REQUIRED",
             "CORRUPTED": "CORRUPTED"}
    lines = ["Anvil lifecycle", "────────────────", f"Status                {names.get(value['lifecycle'], value['lifecycle'])}",
             f"Installed release     {value['transition']['source_version'] or 'unknown'}",
             f"Target release        {value['transition']['target_version'] or 'invalid'}",
             f"Managed config        {'valid' if value['configuration']['valid'] else 'not available'}",
             f"Managed file manifest {'present' if value['managed_config']['manifest_present'] else 'legacy/unrecorded'}",
             f"OpenCode runtime      {value['runtime']['version'] or 'not available'}",
             f"Memory directory     {'present' if value['memory']['present'] else 'not initialized'}",
             f"Rollback snapshots   {value['backups']['valid_count']} verified"]
    for label, values in (("Reason", value["blockers"]), ("Note", value["warnings"])):
        if values:
            lines.extend(["", label])
            lines.extend(f"  {item}" for item in values)
    if value["lifecycle"] == "MIGRATION_REQUIRED":
        lines.extend(["", "Next step", "  Run make upgrade to migrate this valid installation."])
    elif value["lifecycle"] == "STALE":
        lines.extend(["", "Next step", "  Run make upgrade to install the newer compatible Anvil patch release."])
    elif value["lifecycle"] == "RECOVERY_REQUIRED":
        if value["transaction"].get("valid") is True and value["transaction"].get("backup_valid") is True:
            next_step = "Close OpenCode, then rerun the interrupted lifecycle command to recover from its verified snapshot."
        else:
            next_step = "Preserve the current files and review the lifecycle journal and rollback snapshots manually."
        lines.extend(["", "Next step", f"  {next_step}"])
    elif value["lifecycle"] == "TRANSITION_IN_PROGRESS":
        lines.extend(["", "Next step", "  Wait for the active lifecycle command to finish before starting another operation."])
    elif value["lifecycle"] == "UNSUPPORTED":
        lines.extend(["", "Next step", "  Use a compatible Anvil checkout/runtime; automatic downgrade is blocked."])
    elif value["lifecycle"] in {"REPOSITORY_ONLY", "PARTIALLY_INSTALLED", "CORRUPTED"}:
        lines.extend(["", "Next step"])
        if value["lifecycle"] == "REPOSITORY_ONLY":
            lines.append("  Run make reforge to install Anvil.")
        else:
            lines.append("  Review the reported state; run make reforge to rebuild recoverable Anvil files.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "require-installed", "require-current", "latest-backup"), nargs="?", default="inspect")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    value = evaluate()
    if args.action == "latest-backup":
        latest = value["backups"].get("latest")
        if latest:
            print(latest)
            return 0
        if value["lifecycle"] in {"REPOSITORY_ONLY", "PARTIALLY_INSTALLED"}:
            print("BLOCKED: No Anvil rollback snapshot exists in this environment. Run make reforge to complete installation and create the initial snapshot.", file=sys.stderr)
        else:
            print("BLOCKED: No verified Anvil rollback snapshot is available. Run make upgrade or make reforge to create a snapshot before rollback.", file=sys.stderr)
        return 1
    if args.action == "require-installed":
        if value["lifecycle"] in {"INSTALLED", "READY", "DEGRADED", "STALE", "MIGRATION_REQUIRED"}:
            return 0
        print(_human(value), file=sys.stderr)
        if value["lifecycle"] == "UNSUPPORTED":
            print("\nBLOCKED: This checkout cannot safely modify the installed Anvil/runtime version.", file=sys.stderr)
        else:
            print("\nBLOCKED: This operation requires a usable Anvil installation. Review the state above before running make reforge.", file=sys.stderr)
        return 1
    if args.action == "require-current":
        if value["lifecycle"] in {"READY", "INSTALLED", "DEGRADED"}:
            return 0
        print(_human(value), file=sys.stderr)
        if value["lifecycle"] == "MIGRATION_REQUIRED":
            print("\nBLOCKED: Run make upgrade to bring Anvil to this checkout before changing the OpenCode runtime.", file=sys.stderr)
        elif value["lifecycle"] == "RECOVERY_REQUIRED":
            print("\nBLOCKED: Recover the interrupted Anvil operation before changing the OpenCode runtime.", file=sys.stderr)
        else:
            print("\nBLOCKED: Runtime changes require a current, usable Anvil installation.", file=sys.stderr)
        return 1
    print(json.dumps(value, ensure_ascii=False, indent=2) if args.format == "json" else _human(value))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Anvil lifecycle inspection failed: {type(exc).__name__}. Run with DEBUG=1 for details.", file=sys.stderr)
        if os.environ.get("DEBUG") == "1":
            raise
        raise SystemExit(1)
