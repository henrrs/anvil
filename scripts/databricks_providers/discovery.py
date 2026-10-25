"""Bounded discovery of supported Databricks tools and auth profiles."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from . import owned_config, process, timeouts
from .state import data_root


MIN_CLI = (1, 0, 0)
OFFICIAL_VSCODE_EXTENSION = "databricks.databricks"
_VSCODE_CACHE: tuple[tuple[str | None, str], dict[str, Any]] | None = None
_CLI_CACHE: dict[tuple[str, int, int, str], dict[str, Any]] = {}


def parse_version(text: str) -> tuple[int, int, int] | None:
    import re
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?!\d)", text)
    return tuple(map(int, match.groups())) if match else None


def _check_cli(path: str, *, discovered_by: str) -> dict[str, Any]:
    executable = Path(path).expanduser()
    try:
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return {"status": "NOT_INSTALLED", "installed": False, "executable": None,
                    "version": None, "discovered_by": discovered_by, "path_visible": False}
        absolute = str(executable.resolve(strict=True))
        stat_result = executable.stat()
        cache_key = (absolute, stat_result.st_mtime_ns, stat_result.st_size,
                     os.environ.get("ANVIL_DATABRICKS_CLI_VERSION", ""))
        cached = _CLI_CACHE.get(cache_key)
        if cached:
            result = dict(cached)
            path_command = shutil.which("databricks")
            result["path_visible"] = bool(path_command and Path(path_command).resolve() == Path(absolute))
            result["discovered_by"] = discovered_by
            return result
        result = process.run([absolute, "-v"], timeout=timeouts.seconds_for("cli_version"),
                             env=owned_config.child_environment())
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        version = parse_version(output)
        path_command = shutil.which("databricks")
        path_visible = bool(path_command and Path(path_command).resolve() == Path(absolute))
        if result.returncode != 0 or version is None:
            status = "BROKEN"
            version_text = None
        elif version < MIN_CLI:
            status = "UNSUPPORTED_VERSION"
            version_text = ".".join(map(str, version))
        else:
            status = "READY"
            version_text = ".".join(map(str, version))
        checked = {"status": status, "installed": True, "executable": absolute,
                   "version": version_text or (output[:80] if output else None),
                   "discovered_by": discovered_by, "path_visible": path_visible,
                   "absolute_usable": status == "READY"}
        _CLI_CACHE[cache_key] = dict(checked)
        return checked
    except (OSError, process.ProcessFailure, ValueError):
        return {"status": "BROKEN", "installed": True, "executable": str(executable),
                "version": None, "discovered_by": discovered_by, "path_visible": False,
                "absolute_usable": False}


def discover_cli(state: dict[str, Any]) -> dict[str, Any]:
    cached = state.get("providers", {}).get("cli", {}) if isinstance(state.get("providers"), dict) else {}
    candidates: list[tuple[str, str]] = []
    test_override = os.environ.get("ANVIL_DATABRICKS_CLI")
    if test_override:
        candidates.append((test_override, "test-override"))
    old_path = cached.get("executable") if isinstance(cached, dict) else None
    if isinstance(old_path, str) and Path(old_path).is_absolute():
        candidates.append((old_path, "verified-state"))
    by_path = shutil.which("databricks")
    if by_path:
        candidates.append((by_path, "path"))
    if platform.system() == "Linux":
        candidates.extend((str(path), "known-location") for path in (
            Path("/usr/local/bin/databricks"), Path("/usr/bin/databricks"),
            Path.home() / ".local" / "bin" / "databricks",
            data_root() / "bin" / "databricks",
        ))
    elif platform.system() == "Darwin":
        candidates.extend((str(path), "known-location") for path in (
            Path("/usr/local/bin/databricks"), Path("/opt/homebrew/bin/databricks"),
            Path.home() / ".local" / "bin" / "databricks", data_root() / "bin" / "databricks",
        ))
    seen: set[str] = set()
    installed_but_unusable = None
    for path, source in candidates:
        try:
            absolute = str(Path(path).expanduser().resolve(strict=False))
        except OSError:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        checked = _check_cli(absolute, discovered_by=source)
        if checked.get("status") == "READY":
            return checked
        if checked.get("installed") and installed_but_unusable is None:
            installed_but_unusable = checked
    if installed_but_unusable:
        return installed_but_unusable
    return {"status": "NOT_INSTALLED", "installed": False, "executable": None,
            "version": None, "discovered_by": None, "path_visible": False,
            "absolute_usable": False}


def python_version(python: str) -> str | None:
    try:
        result = process.run([python, "-c", "import importlib.metadata as m; print(m.version('databricks-sdk'))"],
                             timeout=8, env=owned_config.child_environment())
    except (OSError, process.ProcessFailure, ValueError):
        return None
    if result.returncode:
        return None
    return result.stdout.strip()[:80] or None


def discover_sdk(state: dict[str, Any]) -> dict[str, Any]:
    recorded = state.get("providers", {}).get("sdk", {}) if isinstance(state.get("providers"), dict) else {}
    candidates: list[tuple[str, str]] = []
    if isinstance(recorded, dict) and isinstance(recorded.get("python"), str):
        candidates.append((recorded["python"], "verified-state"))
    root = data_root() / "venv"
    candidates.append((str(root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")), "anvil-venv"))
    candidates.append((sys.executable, "system-python"))
    seen: set[str] = set()
    for python, source in candidates:
        try:
            # Keep the invocation path. Resolving venv/bin/python can replace
            # the environment entrypoint with its system-interpreter target.
            absolute = str(Path(python).expanduser().absolute())
            if not Path(absolute).is_file() or not os.access(absolute, os.X_OK):
                continue
        except OSError:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        if source == "system-python":
            try:
                version = importlib.metadata.version("databricks-sdk")
            except importlib.metadata.PackageNotFoundError:
                version = None
        else:
            version = python_version(absolute)
        if version:
            return {"status": "READY", "installed": True, "python": absolute,
                    "version": version, "environment": source,
                    "isolated": source == "anvil-venv"}
    return {"status": "NOT_INSTALLED", "installed": False, "python": None,
            "version": None, "environment": None, "isolated": False}


def _module_available(python: str, module: str) -> bool:
    code = "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)"
    try:
        return process.run([python, "-c", code, module], timeout=8,
                           env=owned_config.child_environment()).returncode == 0
    except (OSError, process.ProcessFailure, ValueError):
        return False


def _vscode() -> dict[str, Any]:
    global _VSCODE_CACHE
    override = os.environ.get("ANVIL_VSCODE_CLI")
    code = (override if Path(override).is_file() and os.access(override, os.X_OK) else None) if override else shutil.which("code")
    key = (code, os.environ.get("PATH", "") + "|" + str(override))
    if _VSCODE_CACHE and _VSCODE_CACHE[0] == key:
        return dict(_VSCODE_CACHE[1])
    if not code:
        result = {"status": "UNKNOWN", "available": False, "extension": "UNKNOWN", "code": None}
        _VSCODE_CACHE = (key, result)
        return dict(result)
    try:
        result = process.run([code, "--list-extensions"], timeout=12,
                             env=owned_config.child_environment())
    except (OSError, process.ProcessFailure, ValueError):
        result = {"status": "UNKNOWN", "available": True, "extension": "UNKNOWN", "code": str(Path(code).resolve())}
        _VSCODE_CACHE = (key, result)
        return dict(result)
    if result.returncode:
        value = {"status": "UNKNOWN", "available": True, "extension": "UNKNOWN", "code": str(Path(code).resolve())}
        _VSCODE_CACHE = (key, value)
        return dict(value)
    ids = {line.strip().casefold() for line in result.stdout.splitlines() if line.strip()}
    present = OFFICIAL_VSCODE_EXTENSION in ids
    value = {"status": "AVAILABLE" if present else "NOT_INSTALLED", "available": True,
             "extension": "YES" if present else "NO", "extension_id": OFFICIAL_VSCODE_EXTENSION,
             "code": str(Path(code).resolve())}
    _VSCODE_CACHE = (key, value)
    return dict(value)


def profile_file() -> Path:
    configured = os.environ.get("DATABRICKS_CONFIG_FILE")
    return Path(configured).expanduser() if configured else Path.home() / ".databrickscfg"


def config_profiles(path: Path | str | None = None) -> list[dict[str, Any]]:
    path = Path(path).expanduser() if path is not None else profile_file()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError):
        return []
    profiles: dict[str, dict[str, Any]] = {}
    section: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            if section and section != "__settings__":
                profiles.setdefault(section, {"name": section, "host": "", "valid": False})
            continue
        if section and "=" in stripped:
            key, value = stripped.split("=", 1)
            if key.strip().casefold() == "host":
                profiles[section]["host"] = value.strip()
    return list(profiles.values())


def discover_specialized(python: str | None) -> dict[str, dict[str, Any]]:
    connect = sql_connector = {"status": "NOT_INSTALLED", "installed": False}
    python = python or sys.executable
    for module, target in (("databricks.connect", "connect"), ("databricks.sql", "sql_connector")):
        if python == sys.executable:
            try:
                installed = importlib.util.find_spec(module) is not None
            except (ImportError, ModuleNotFoundError, ValueError):
                installed = False
        else:
            installed = _module_available(python, module)
        value = {"status": "READY" if installed else "NOT_INSTALLED", "installed": installed, "python": python}
        if target == "connect":
            connect = value
        else:
            sql_connector = value
    return {"connect": connect, "sql_connector": sql_connector, "vscode": _vscode()}
