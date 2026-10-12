#!/usr/bin/env python3
"""Create and safely restore OpenCode config snapshots without following symlinks."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def create(source: Path, archive: Path, arcname: str) -> None:
    if not source.exists() and not source.is_symlink():
        raise FileNotFoundError(source)
    if Path(arcname).name != arcname or arcname in ("", ".", ".."):
        raise ValueError("archive root must be a simple directory name")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz", dereference=False) as output:
        output.add(source, arcname=arcname, recursive=True)
    os.chmod(archive, 0o600)


def _validated_members(bundle: tarfile.TarFile, expected_root: str) -> list[tarfile.TarInfo]:
    members = bundle.getmembers()
    names: dict[str, tarfile.TarInfo] = {}
    for member in members:
        raw = PurePosixPath(member.name)
        if raw.is_absolute() or any(part in ("..", "") for part in raw.parts):
            raise ValueError(f"unsafe path in backup: {member.name!r}")
        parts = tuple(part for part in raw.parts if part not in (".", ""))
        if not parts or parts[0] != expected_root:
            raise ValueError(f"unexpected backup root: {member.name!r}")
        normalized = "/".join(parts)
        if normalized in names:
            raise ValueError(f"duplicate archive path: {normalized}")
        if not (member.isdir() or member.isfile() or member.issym()):
            raise ValueError(f"unsupported archive entry type: {normalized}")
        names[normalized] = member

    for normalized, member in names.items():
        parts = normalized.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            parent_member = names.get(parent)
            if parent_member and not parent_member.isdir():
                raise ValueError(f"archive writes through a non-directory entry: {parent}")
    return members


def safe_restore(archive: Path, target: Path, present: bool) -> None:
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if target.name not in {"opencode", ".opencode"}:
        raise ValueError("restore target must be the OpenCode config or install directory")
    temporary = Path(tempfile.mkdtemp(prefix=".anvil-restore-", dir=parent))
    try:
        staged = temporary / target.name
        if present:
            with tarfile.open(archive, "r:gz") as bundle:
                members = _validated_members(bundle, target.name)
                directories = [m for m in members if m.isdir()]
                files = [m for m in members if m.isfile()]
                links = [m for m in members if m.issym()]
                for member in sorted(directories, key=lambda item: len(PurePosixPath(item.name).parts)):
                    dest = temporary.joinpath(*PurePosixPath(member.name).parts)
                    dest.mkdir(parents=True, exist_ok=True)
                    os.chmod(dest, member.mode & 0o777)
                for member in files:
                    dest = temporary.joinpath(*PurePosixPath(member.name).parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    source = bundle.extractfile(member)
                    if source is None:
                        raise ValueError(f"missing archived content: {member.name}")
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    if hasattr(os, "O_NOFOLLOW"):
                        flags |= os.O_NOFOLLOW
                    fd = os.open(dest, flags, member.mode & 0o777)
                    with os.fdopen(fd, "wb") as output, source:
                        shutil.copyfileobj(source, output)
                    os.chmod(dest, member.mode & 0o777)
                for member in links:
                    dest = temporary.joinpath(*PurePosixPath(member.name).parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(member.linkname, dest)
                if not staged.exists() and not staged.is_symlink():
                    raise ValueError("backup did not contain its expected root directory")
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        if present:
            os.replace(staged, target)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p_create = sub.add_parser("create")
    p_create.add_argument("source", type=Path)
    p_create.add_argument("archive", type=Path)
    p_create.add_argument("arcname")
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("archive", type=Path)
    p_restore.add_argument("target", type=Path)
    p_restore.add_argument("present", choices=("yes", "no"))
    args = parser.parse_args()
    if args.action == "create":
        create(args.source, args.archive, args.arcname)
    else:
        safe_restore(args.archive, args.target, args.present == "yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
