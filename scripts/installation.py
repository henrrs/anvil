#!/usr/bin/env python3
"""Write Anvil's private, atomic installation and migration record."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from semver import parse as parse_version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, help="Installed config root whose Anvil manifest is recorded")
    parser.add_argument("--opencode-version", required=True)
    parser.add_argument("--opencode-major", type=int)
    parser.add_argument("--anvil-version", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--release-json", type=Path)
    parser.add_argument("--anvil-only", action="store_true", help="Update Anvil metadata while preserving the recorded runtime provenance")
    parser.add_argument("--runtime-only", action="store_true", help="Update runtime provenance while preserving the installed Anvil release")
    parser.add_argument("--migration-status", required=True)
    parser.add_argument("--previous-anvil-version", default="")
    parser.add_argument("--previous-opencode-version", default="")
    parser.add_argument("--from-generation", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--backup", default="")
    args = parser.parse_args()
    if args.anvil_only and args.runtime_only:
        parser.error("--anvil-only and --runtime-only cannot be combined")
    runtime_major = args.opencode_major or int(args.opencode_version.split(".", 1)[0])
    if runtime_major not in (1, 2) or int(args.opencode_version.split(".", 1)[0]) != runtime_major:
        parser.error("OpenCode version and runtime major do not match a supported adapter")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    destination = args.destination
    if args.anvil_only:
        try:
            record = json.loads(destination.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                record = {}
        except (OSError, ValueError, json.JSONDecodeError):
            record = {}
        record.update({
            "schema_version": max(3, int(record.get("schema_version", 1) or 1)),
            "anvil_version": args.anvil_version,
            "runtime_major": runtime_major,
            "runtime_profile": f"opencode-v{runtime_major}",
            "version": args.opencode_version,
            "binary": args.binary,
            "installed_utc": now,
            "previous_anvil_version": args.previous_anvil_version or None,
            "previous_opencode_version": args.opencode_version,
            "migration": {
                "status": args.migration_status,
                "from_runtime_major": runtime_major,
                "from_anvil": args.previous_anvil_version or None,
                "from_opencode": args.opencode_version,
                "backup": args.backup or None,
                "completed_utc": now,
            },
        })
    else:
        if args.release_json is None:
            parser.error("runtime lifecycle operations require --release-json")
        try:
            release = json.loads(args.release_json.read_text(encoding="utf-8"))
            if not isinstance(release, dict) or release.get("version") != args.opencode_version:
                raise ValueError("release record does not match the installed OpenCode version")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"invalid release record: {exc}")
        asset = release.get("asset") if isinstance(release.get("asset"), dict) else {}
        if args.runtime_only:
            try:
                record = json.loads(destination.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    record = {}
            except (OSError, ValueError, json.JSONDecodeError):
                record = {}
            prior_major = record.get("runtime_major", record.get("generation", args.from_generation))
            prior_version = record.get("version") or args.previous_opencode_version or None
            record.update({
                "schema_version": max(3, int(record.get("schema_version", 1) or 1)),
                "runtime_major": runtime_major,
                "runtime_profile": f"opencode-v{runtime_major}",
                "version": args.opencode_version,
                "binary": args.binary,
                "release_url": release.get("release_url"),
                "release_channel": release.get("channel"),
                "published_at": release.get("published_at"),
                "artifact_name": asset.get("name"),
                "artifact_integrity": asset.get("integrity"),
                "artifact_digest": asset.get("integrity"),
                "installed_utc": now,
                "previous_opencode_version": prior_version,
                "migration": {
                    "status": args.migration_status,
                    "from_runtime_major": prior_major or runtime_major,
                    "from_anvil": record.get("anvil_version"),
                    "from_opencode": prior_version,
                    "backup": args.backup or None,
                    "completed_utc": now,
                },
            })
        else:
            record = {
                "schema_version": 3,
                "anvil_version": args.anvil_version,
                "runtime_major": runtime_major,
                "runtime_profile": f"opencode-v{runtime_major}",
                "version": args.opencode_version,
                "binary": args.binary,
                "release_url": release.get("release_url"),
                "release_channel": release.get("channel"),
                "published_at": release.get("published_at"),
                "artifact_name": asset.get("name"),
                "artifact_integrity": asset.get("integrity"),
                "artifact_digest": asset.get("integrity"),
                "installed_utc": now,
                "previous_anvil_version": args.previous_anvil_version or None,
                "previous_opencode_version": args.previous_opencode_version or None,
                "migration": {
                    "status": args.migration_status,
                    "from_runtime_major": args.from_generation or None,
                    "from_anvil": args.previous_anvil_version or None,
                    "from_opencode": args.previous_opencode_version or None,
                    "backup": args.backup or None,
                    "completed_utc": now,
                },
            }
    if args.config_dir is not None:
        manifest_path = args.config_dir / ".anvil-managed.json"
        if manifest_path.is_file():
            try:
                digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            except OSError as exc:
                parser.error(f"could not read installed managed config manifest: {exc}")
            record["managed_config_manifest_sha256"] = digest
        elif (parse_version(record.get("anvil_version")) or (0, 0, 0)) >= (2, 8, 0):
            parser.error("this installed Anvil release requires a managed config manifest")
        else:
            record.pop("managed_config_manifest_sha256", None)
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".installation.", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
