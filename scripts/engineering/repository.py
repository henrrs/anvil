"""Observe only named repository evidence; never scan a project to classify it."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .contracts import relative_path, require
from .errors import EngineeringError


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def no_symlinks(path: Path) -> None:
    absolute = path.absolute()
    for item in (absolute, *absolute.parents):
        if item.is_symlink():
            raise EngineeringError("UNSAFE_PATH", "Engineering evidence/state must not traverse symbolic links.")


def file_path(root: Path, relative: str) -> Path:
    relative_path(relative)
    path = root / relative
    no_symlinks(path)
    require(path.resolve().is_relative_to(root.resolve()), "Evidence path escaped the repository.", "UNSAFE_PATH")
    return path


def hashes(root: Path, paths: list[str]) -> dict[str, str | None]:
    result = {}
    for relative in sorted(set(paths)):
        path = file_path(root, relative)
        require(not path.exists() or path.is_file(), f"Evidence must name files: {relative}")
        result[relative] = digest(path) if path.is_file() else None
    return result


def git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, timeout=5, check=False,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def identity(root: Path) -> dict:
    root = root.resolve(strict=True)
    require(root.is_dir(), "Repository must be a directory.")
    top = git(root, "rev-parse", "--show-toplevel")
    require(top is None or Path(top).resolve() == root, "Use the repository root, not a nested source directory.")
    return {"root": str(root), "id": hashlib.sha256(str(root).encode()).hexdigest()[:24],
            "branch": git(root, "symbolic-ref", "--short", "-q", "HEAD"),
            "head": git(root, "rev-parse", "HEAD")}


def specification(path: Path) -> dict:
    no_symlinks(path)
    require(path.is_file() and path.stat().st_size <= 2 * 1024 * 1024, "Specification must be a named regular file up to 2 MiB.")
    return {"path": str(path.absolute()), "sha256": digest(path)}


def observe(root: Path, models: dict, spec: Path) -> dict:
    from .invariants import scope
    paths = [path for task in models["work"]["tasks"] for path in task["paths"]]
    for invariant in models["architecture"].get("invariants", []):
        paths.extend(scope(root, invariant["paths"]))
    return {"repository": identity(root), "files": hashes(root, paths), "specification": specification(spec)}


def drift(anchor: dict, root: Path, models: dict) -> dict:
    spec = Path(anchor["specification"]["path"])
    if not spec.exists():
        current = {"repository": identity(root), "files": hashes(root, list(anchor["files"])),
                   "specification": {"path": str(spec), "sha256": None}}
    else:
        current = observe(root, models, spec)
    old = anchor["repository"]
    changed_files = sorted(path for path in set(anchor["files"]) | set(current["files"])
                           if anchor["files"].get(path) != current["files"].get(path))
    spec_changed = anchor["specification"]["sha256"] != current["specification"]["sha256"]
    git_changed = {key: {"previous": old[key], "current": current["repository"][key]}
                   for key in ("branch", "head") if old[key] != current["repository"][key]}
    return {"stale": bool(changed_files or spec_changed or git_changed), "changed_files": changed_files,
            "specification_changed": spec_changed, "git_changes": git_changed, "current": current}
