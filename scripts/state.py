#!/usr/bin/env python3
"""Create, validate, and select Anvil's checksum-protected rollback manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def hash_files(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.name not in {"manifest.json", "checksums.sha256"}:
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def safe_rel(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or any(part in ("..", "") for part in path.parts):
        raise ValueError(f"unsafe checksum path: {value}")
    return path


def create_manifest(args: argparse.Namespace) -> None:
    root: Path = args.backup
    checksums = hash_files(root)
    manifest = {
        "format_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidate_version": args.candidate_version,
        "previous": {
            "config_dir": args.config_dir,
            "config_present": args.config_present == "yes",
            "installer_dir": args.installer_dir,
            "installer_present": args.installer_present == "yes",
            "executable_path": args.executable_path or None,
            "executable_resolved": args.executable_resolved or None,
            "executable_version": args.executable_version or None,
            "path_update": {
                "file": args.path_file or None,
                "line": args.path_line or None,
                "added": args.path_added == "yes",
                "file_preexisted": args.path_file_preexisted == "yes",
            },
            "authentication_and_session_state": "preserved in place; not copied or rewritten",
        },
        "artifacts": {
            "config_archive": "config.tar.gz" if (root / "config.tar.gz").is_file() else None,
            "installer_archive": "opencode-root.tar.gz" if (root / "opencode-root.tar.gz").is_file() else None,
            "inspect": "inspect.txt",
            "binary_copy": "previous-opencode-binary" if (root / "previous-opencode-binary").is_file() else None,
            "previous_installation": "previous-installation.json" if (root / "previous-installation.json").is_file() else None,
        },
        "checksums": checksums,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    lines = [f"{value}  {name}" for name, value in checksums.items()]
    (root / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    import os
    os.chmod(root / "manifest.json", 0o600)
    os.chmod(root / "checksums.sha256", 0o600)


def verify(root: Path) -> dict:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1 or not isinstance(manifest.get("checksums"), dict):
        raise ValueError("unsupported or invalid backup manifest")
    for relative, expected in manifest["checksums"].items():
        path = root / safe_rel(relative)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"backup artifact is missing or unsafe: {relative}")
        if digest(path) != expected:
            raise ValueError(f"checksum mismatch: {relative}")
    checksum_path = root / "checksums.sha256"
    if not checksum_path.is_file():
        raise ValueError("checksums.sha256 is missing")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match or manifest["checksums"].get(match.group(2)) != match.group(1):
            raise ValueError("checksums.sha256 does not match manifest")
    return manifest


def latest(root: Path) -> Path:
    if not root.is_dir():
        raise FileNotFoundError(f"backup directory does not exist: {root}")
    candidates = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    for candidate in candidates:
        try:
            verify(candidate)
            return candidate
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"WARN  Skipping invalid backup {candidate.name}: {exc}", file=sys.stderr)
    raise FileNotFoundError("no valid Anvil backups were found")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p_create = sub.add_parser("create")
    p_create.add_argument("backup", type=Path)
    p_create.add_argument("--config-dir", required=True)
    p_create.add_argument("--config-present", choices=("yes", "no"), required=True)
    p_create.add_argument("--installer-dir", required=True)
    p_create.add_argument("--installer-present", choices=("yes", "no"), required=True)
    p_create.add_argument("--candidate-version", required=True)
    p_create.add_argument("--executable-path", default="")
    p_create.add_argument("--executable-resolved", default="")
    p_create.add_argument("--executable-version", default="")
    p_create.add_argument("--path-file", default="")
    p_create.add_argument("--path-line", default="")
    p_create.add_argument("--path-added", choices=("yes", "no"), default="no")
    p_create.add_argument("--path-file-preexisted", choices=("yes", "no"), default="no")
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("backup", type=Path)
    p_latest = sub.add_parser("latest")
    p_latest.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "create":
            create_manifest(args)
            verify(args.backup)
            return 0
        if args.action == "verify":
            data = verify(args.backup)
            print(f"Valid backup: {args.backup}")
            print(f"Candidate version: {data.get('candidate_version', 'unknown')}")
            return 0
        print(latest(args.root))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
