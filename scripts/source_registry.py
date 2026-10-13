#!/usr/bin/env python3
"""Private, file-based source registry for explicit Anvil distillation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def root() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return data_home / "anvil" / "sources"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_values(path: Path) -> tuple[str | None, str | None, str | None]:
    try:
        repo = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        commit = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        relative = path.relative_to(Path(repo)).as_posix()
        return repo, commit, relative
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None, None


def source_id(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def read_manifest(manifest: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def inspect_source(source: Path) -> dict[str, Any]:
    if source.is_symlink():
        raise ValueError("source registry will not follow a symbolic link")
    path = source.resolve(strict=True)
    if not path.is_file():
        raise ValueError("source must be a regular file")
    repo, commit, relative = git_values(path)
    origin = f"repo:{relative}" if repo and relative else f"file:{path}"
    identity = f"repo:{repo}:{relative}" if repo and relative else f"file:{path}"
    identifier = source_id(identity)
    digest = sha256(path)
    previous = read_manifest(root() / f"{identifier}.json")
    previous_hash = previous.get("sha256") if previous else None
    return {
        "source_id": identifier,
        "origin": origin,
        "path": relative if relative else str(path),
        "absolute_path": str(path),
        "sha256": digest,
        "repository": repo,
        "commit": commit,
        "registry_status": "new" if previous is None else ("unchanged" if previous_hash == digest else "changed"),
        "previous_sha256": previous_hash,
        "first_distilled": previous.get("first_distilled") if previous else None,
        "last_distilled": previous.get("last_distilled") if previous else None,
        "memory_ids": previous.get("memory_ids", []) if previous else [],
    }


def record(raw: Any) -> Path:
    if not isinstance(raw, dict):
        raise ValueError("registry input must be a JSON object")
    required = {"source_id", "origin", "path", "sha256", "memory_ids"}
    if required - raw.keys() or set(raw) - (required | {
        "repository", "commit", "absolute_path", "registry_status", "previous_sha256",
        "first_distilled", "last_distilled",
    }):
        raise ValueError("registry record has missing or unsupported fields")
    identifier = raw["source_id"]
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{24}", identifier):
        raise ValueError("source_id must be a 24-character lowercase hex ID")
    if not isinstance(raw["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", raw["sha256"]):
        raise ValueError("sha256 must be a 64-character lowercase digest")
    if not isinstance(raw["memory_ids"], list) or len(raw["memory_ids"]) > 100:
        raise ValueError("memory_ids must be a list with at most 100 values")
    ids = []
    for item in raw["memory_ids"]:
        if not isinstance(item, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", item):
            raise ValueError("memory_ids may contain only safe memory IDs")
        ids.append(item)
    for key in ("origin", "path", "repository", "commit", "absolute_path"):
        if key in raw and raw[key] is not None and (not isinstance(raw[key], str) or len(raw[key]) > 2000):
            raise ValueError(f"{key} must be text of at most 2000 characters")

    registry = root()
    registry.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(registry, 0o700)
    target = registry / f"{identifier}.json"
    existing = read_manifest(target)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous_hashes = list(existing.get("previous_hashes", [])) if existing else []
    if existing and existing.get("sha256") != raw["sha256"]:
        prior = existing.get("sha256")
        if isinstance(prior, str) and prior not in previous_hashes:
            previous_hashes.append(prior)
        previous_hashes = previous_hashes[-10:]
    data = {
        "schema_version": 1,
        "source_id": identifier,
        "origin": raw["origin"],
        "path": raw["path"],
        "absolute_path": raw.get("absolute_path"),
        "sha256": raw["sha256"],
        "repository": raw.get("repository"),
        "commit": raw.get("commit"),
        "first_distilled": existing.get("first_distilled", now) if existing else now,
        "last_distilled": now,
        "memory_ids": list(dict.fromkeys(ids)),
        "previous_hashes": previous_hashes,
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{identifier}.", suffix=".tmp", dir=registry)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    os.chmod(target, 0o600)
    return target


def audit() -> dict[str, int]:
    registry = root()
    files = list(registry.glob("*.json")) if registry.is_dir() else []
    invalid = 0
    drifted = 0
    for manifest_file in files:
        manifest = read_manifest(manifest_file)
        if (
            not manifest
            or manifest.get("schema_version") != 1
            or not re.fullmatch(r"[a-f0-9]{24}", str(manifest.get("source_id", "")))
            or manifest.get("source_id") != manifest_file.stem
            or not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("sha256", "")))
            or not isinstance(manifest.get("origin"), str)
            or not isinstance(manifest.get("path"), str)
            or not isinstance(manifest.get("memory_ids"), list)
            or any(not isinstance(item, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", item) for item in manifest.get("memory_ids", []))
        ):
            invalid += 1
            continue
        absolute = manifest.get("absolute_path")
        if absolute:
            path = Path(absolute)
            if not path.is_file() or path.is_symlink() or sha256(path) != manifest.get("sha256"):
                drifted += 1
    return {"sources": len(files), "invalid": invalid, "drifted": drifted}


def distill_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        raise ValueError("distill plan input must be a non-empty list of inspect results")
    statuses = []
    for item in value:
        if not isinstance(item, dict) or item.get("registry_status") not in {"new", "unchanged", "changed"}:
            raise ValueError("each source must be an inspect result with a valid registry_status")
        statuses.append(item["registry_status"])
    if all(status == "unchanged" for status in statuses):
        return {"action": "skip", "created": 0, "updated": 0, "duplicate_memories": 0}
    return {"action": "distill", "created": None, "updated": None, "duplicate_memories": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and record explicitly distilled sources")
    sub = parser.add_subparsers(dest="action", required=True)
    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("source", type=Path)
    sub.add_parser("audit")
    sub.add_parser("record")
    sub.add_parser("plan", help="decide whether unchanged registered sources can be skipped")
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            print(json.dumps(inspect_source(args.source), ensure_ascii=False, indent=2))
        elif args.action == "audit":
            print(json.dumps(audit()))
        elif args.action == "plan":
            print(json.dumps(distill_plan(json.load(sys.stdin))))
        else:
            print(record(json.load(sys.stdin)))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
