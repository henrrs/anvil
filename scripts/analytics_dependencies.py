#!/usr/bin/env python3
"""Prepare the release-pinned, isolated Python runtime used by Analytics."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MIN_PYTHON = (3, 11)
PACKAGE_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$")
REQUIRED = {"duckdb", "pyarrow"}


class DependencyError(RuntimeError):
    def __init__(self, dependency: str, message: str) -> None:
        super().__init__(message)
        self.dependency = dependency


def parse_lock(path: Path) -> tuple[str, list[tuple[str, str]]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DependencyError("manifest", "the Analytics dependency manifest is missing") from exc
    release = ""
    packages: list[tuple[str, str]] = []
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("# anvil-release:"):
            release = line.split(":", 1)[1].strip()
        elif line and not line.startswith("#"):
            match = PACKAGE_LINE.fullmatch(line)
            if not match:
                raise DependencyError("manifest", "the Analytics dependency manifest is invalid")
            packages.append((match.group(1).lower().replace("_", "-"), match.group(2)))
    if not release or not REQUIRED.issubset({name for name, _ in packages}):
        raise DependencyError("manifest", "the Analytics dependency manifest is incomplete")
    if len({name for name, _ in packages}) != len(packages):
        raise DependencyError("manifest", "the Analytics dependency manifest contains duplicate packages")
    return release, packages


def runtime_path(lock: Path, data_root: Path, python: str = sys.executable) -> Path:
    _, _ = parse_lock(lock)
    try:
        version = subprocess.run([python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                                 capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise DependencyError("python", "the selected Python runtime could not be inspected") from exc
    if not re.fullmatch(r"\d+\.\d+", version) or tuple(map(int, version.split("."))) < MIN_PYTHON:
        raise DependencyError("python", "Analytics requires Python 3.11 or newer")
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()[:20]
    return data_root / "anvil" / "analytics" / "runtimes" / f"py{version}-{digest}"


def _validate(interpreter: Path, packages: list[tuple[str, str]]) -> bool:
    expected = json.dumps(dict(packages), separators=(",", ":"))
    code = ("import importlib, json; expected=json.loads(" + repr(expected) + "); "
            "mods={'duckdb':'duckdb','pyarrow':'pyarrow'}; "
            "actual={name:importlib.import_module(mod).__version__ for name,mod in mods.items()}; "
            "raise SystemExit(0 if all(actual.get(k)==v for k,v in expected.items()) else 1)")
    try:
        return subprocess.run([str(interpreter), "-c", code], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=10, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def prepare(lock: Path, data_root: Path, python: str = sys.executable) -> Path:
    _, packages = parse_lock(lock)
    destination = runtime_path(lock, data_root, python)
    interpreter = destination / "bin" / "python"
    if destination.is_dir() and _validate(interpreter, packages):
        return interpreter
    root = destination.parent
    for candidate in (data_root, data_root / "anvil", data_root / "anvil" / "analytics",
                      data_root / "anvil" / "analytics" / "runtimes"):
        if candidate.exists() and candidate.is_symlink():
            raise DependencyError("runtime", "Analytics runtime paths must not contain symbolic links")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise DependencyError("runtime", "Analytics runtime directory must not be a symbolic link")
    os.chmod(root, 0o700)
    lock_path = root / ".prepare.lock"
    with lock_path.open("a", encoding="utf-8") as lock_stream:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        if destination.is_dir() and _validate(interpreter, packages):
            return interpreter
        staging = Path(tempfile.mkdtemp(prefix=".runtime-", dir=root))
        shutil.rmtree(staging)
        try:
            subprocess.run([python, "-m", "venv", str(staging)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60, check=True)
            staged_python = staging / "bin" / "python"
            for name, version in packages:
                try:
                    subprocess.run([str(staged_python), "-m", "pip", "install", "--disable-pip-version-check",
                                    "--no-input", "--no-deps", "--only-binary=:all:", f"{name}=={version}"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=900, check=True)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise DependencyError(name, "the pinned package could not be installed") from exc
            if not _validate(staged_python, packages):
                raise DependencyError("duckdb/pyarrow", "Analytics package import/version validation failed")
            os.chmod(staging, 0o700)
            for directory, subdirs, files in os.walk(staging):
                os.chmod(directory, 0o700)
                for filename in files:
                    path = Path(directory) / filename
                    if not path.is_symlink():
                        os.chmod(path, 0o700 if os.access(path, os.X_OK) else 0o600)
            backup = root / f".runtime-previous-{os.getpid()}"
            if backup.exists() or backup.is_symlink():
                shutil.rmtree(backup, ignore_errors=True)
            had_destination = destination.exists() or destination.is_symlink()
            if had_destination:
                os.replace(destination, backup)
            try:
                os.replace(staging, destination)
                published = destination / "bin" / "python"
                if not _validate(published, packages):
                    raise DependencyError("duckdb/pyarrow", "the published Analytics runtime failed validation")
            except BaseException:
                shutil.rmtree(destination, ignore_errors=True)
                if had_destination and backup.exists():
                    os.replace(backup, destination)
                raise
            shutil.rmtree(backup, ignore_errors=True)
            return published
        except DependencyError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise DependencyError("runtime", "the isolated Analytics runtime could not be prepared") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "resolve", "status", "plan"))
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")))
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        target = runtime_path(args.lock, args.data_root, args.python)
        interpreter = prepare(args.lock, args.data_root, args.python) if args.action == "prepare" else target / "bin" / "python"
        _, packages = parse_lock(args.lock)
        ready = _validate(interpreter, packages)
        if args.action == "plan":
            _, release_packages = parse_lock(args.lock)
            print(f"Analytics runtime plan (Anvil {parse_lock(args.lock)[0]})")
            print(f"  interpreter  {interpreter}")
            print(f"  action       {'REUSE VALIDATED ENVIRONMENT' if ready else 'PREPARE ISOLATED ENVIRONMENT'}")
            for name, version in release_packages:
                print(f"  dependency   {name}=={version}")
            print("  service      systemd unit sync, enable/start, runtime readiness check")
            print("  OpenCode     bootstrap and canonical session validation")
            print("  catalog      background metadata refresh; no table rows fetched")
            return 0
        if args.action != "prepare" and not ready:
            raise DependencyError("duckdb/pyarrow", "the prepared Analytics runtime is missing or unhealthy")
        if args.action == "status":
            print(json.dumps({"status": "READY", "python": str(interpreter), "runtime": str(target),
                              "packages": dict(packages)}, sort_keys=True))
        else:
            print(interpreter)
        return 0
    except DependencyError as exc:
        print("Analytics runtime could not be prepared.\n\n"
              f"Dependency:\n{exc.dependency}\n\n"
              "The previous supported installation remains available.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
