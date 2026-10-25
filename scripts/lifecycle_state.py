#!/usr/bin/env python3
"""Evaluate Anvil-managed installation and rollback state for public commands."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime_state  # noqa: E402
import state as backup_state  # noqa: E402


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


def _audit_config(path: Path) -> int | None:
    if not path.is_file():
        return None
    for command, major in (("audit-v1", 1), ("audit", 2)):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "configure.py"), command, str(path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if result.returncode == 0:
            return major
    return 0


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
    repository_valid = bool(re.fullmatch(r"\d+\.\d+\.\d+", repository_version))

    record, record_valid = _read_json(locations["record"])
    runtime_saved, runtime_state_valid = _read_json(locations["runtime_state"])
    config_path = locations["config"] / "opencode.jsonc"
    config_major = _audit_config(config_path)
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
    record_exists = locations["record"].exists()
    runtime_state_exists = locations["runtime_state"].exists()
    memory_present = locations["memory"].is_dir()
    backup_inventory = _backup_inventory(locations["backups"])

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
    if config_present and config_major == 0:
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
        corrupted = True
        blockers.append("The managed OpenCode executable is not usable under the current runtime policy.")
    if config_valid and runtime_usable and runtime_major != config_major:
        corrupted = True
        blockers.append("The active OpenCode runtime major does not match the managed Anvil config.")

    if corrupted:
        lifecycle = "CORRUPTED"
    elif not managed_artifacts:
        lifecycle = "REPOSITORY_ONLY"
        warnings.append("No Anvil-managed installation state exists in this HOME/XDG environment.")
    elif not config_valid or not runtime_usable:
        lifecycle = "PARTIALLY_INSTALLED"
        if not config_valid:
            blockers.append("A valid managed OpenCode config is not present.")
        if not runtime_usable:
            blockers.append("A supported, usable OpenCode runtime is not available.")
    elif not memory_present:
        lifecycle = "DEGRADED"
        warnings.append("The Anvil memory directory is absent; memory features will initialize it when needed.")
    elif isinstance(record, dict) and record.get("anvil_version") == repository_version:
        lifecycle = "READY"
    else:
        lifecycle = "INSTALLED"
        if record_exists and record and not record.get("anvil_version"):
            warnings.append("Installation metadata does not record an Anvil release; runtime and config checks passed.")
        elif record_exists and record and record.get("anvil_version") != repository_version:
            warnings.append("A newer or older Anvil repository release is available for this installation.")
        elif not record_exists:
            warnings.append("Installation metadata is missing; runtime and config checks passed.")

    if not backup_inventory["latest"]:
        warnings.append("No verified rollback snapshot is available yet.")

    return {
        "schema_version": 1,
        "lifecycle": lifecycle,
        "repository": {"version": repository_version or None, "valid": repository_valid},
        "installation": {"managed_artifacts": managed_artifacts,
                          "record_present": record_exists,
                          "recorded_version": record.get("anvil_version") if isinstance(record, dict) else None,
                          "record_valid": record_shape_valid},
        "configuration": {"present": config_present, "valid": config_valid,
                           "runtime_major": config_major or None,
                           "path": str(locations["config"])},
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
             "CORRUPTED": "CORRUPTED"}
    lines = ["Anvil lifecycle", "────────────────", f"Status                {names.get(value['lifecycle'], value['lifecycle'])}",
             f"Repository release    {value['repository']['version'] or 'invalid'}",
             f"Managed config        {'valid' if value['configuration']['valid'] else 'not available'}",
             f"OpenCode runtime      {value['runtime']['version'] or 'not available'}",
             f"Memory directory     {'present' if value['memory']['present'] else 'not initialized'}",
             f"Rollback snapshots   {value['backups']['valid_count']} verified"]
    for label, values in (("Reason", value["blockers"]), ("Note", value["warnings"])):
        if values:
            lines.extend(["", label])
            lines.extend(f"  {item}" for item in values)
    if value["lifecycle"] in {"REPOSITORY_ONLY", "PARTIALLY_INSTALLED", "CORRUPTED"}:
        lines.extend(["", "Next step"])
        if value["lifecycle"] == "REPOSITORY_ONLY":
            lines.append("  Run make reforge to install Anvil.")
        else:
            lines.append("  Review the reported state; run make reforge to rebuild recoverable Anvil files.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "require-installed", "latest-backup"), nargs="?", default="inspect")
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
        if value["lifecycle"] in {"INSTALLED", "READY", "DEGRADED"}:
            return 0
        print(_human(value), file=sys.stderr)
        print("\nBLOCKED: This operation requires an installed Anvil runtime and valid managed config. Run make reforge first.", file=sys.stderr)
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
