#!/usr/bin/env python3
"""Discover and validate the local OpenCode runtime without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def paths() -> dict[str, Path]:
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser()
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local/state"))).expanduser()
    return {
        "home": home,
        "installation": data_home / "anvil/installation.json",
        "state": data_home / "anvil/runtime.json",
        "config": config_home / "opencode",
        "runtime_state": state_home / "anvil/runtime.json",
        "managed": home / ".opencode/bin/opencode",
    }


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?!\d)", value.strip())
    return tuple(map(int, match.groups())) if match else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def in_path(path: Path) -> bool:
    resolved = str(path.resolve())
    found = shutil.which("opencode")
    return bool(found and str(Path(found).resolve()) == resolved)


def candidates() -> list[tuple[Path, str]]:
    locations = paths()
    result: list[tuple[Path, str]] = []
    seen: set[str] = set()

    def add(value: str | Path | None, source: str) -> None:
        if not value:
            return
        path = Path(value).expanduser()
        try:
            absolute = path.resolve(strict=True)
        except OSError:
            absolute = path.absolute()
        key = str(absolute)
        if key not in seen:
            seen.add(key)
            result.append((absolute, source))

    state = read_json(locations["state"])
    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else state
    add(runtime.get("executable"), "validated runtime state")
    install = read_json(locations["installation"])
    add(install.get("binary") or install.get("binary_path"), "Anvil installation record")
    add(locations["managed"], "Anvil managed runtime")
    add(shutil.which("opencode"), "current PATH")
    return result


def inspect_candidate(path: Path, source: str, minimums: dict[str, str], supported: list[int]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "executable": str(path), "source": source, "installed": path.is_file(),
        "usable": False, "version": None, "generation": None, "adapter": "unavailable",
        "supported": False, "minimum_version": None, "path_ready": False,
        "identity": None, "failure": None,
    }
    if not path.is_file() or not os.access(path, os.X_OK):
        item["failure"] = "RUNTIME_NOT_FOUND"
        return item
    try:
        environment = os.environ.copy()
        environment["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True,
                                timeout=10, check=True, env=environment)
    except (OSError, subprocess.SubprocessError):
        item["failure"] = "RUNTIME_UNHEALTHY"
        return item
    output = (result.stdout or result.stderr).strip().splitlines()
    parsed = parse_version(output[0] if output else "")
    if not parsed:
        item["failure"] = "RUNTIME_UNHEALTHY"
        return item
    generation = parsed[0]
    version = ".".join(map(str, parsed))
    minimum_text = minimums.get(str(generation))
    minimum = parse_version(minimum_text or "")
    policy_supported = generation in supported
    version_supported = bool(minimum and parsed >= minimum)
    item.update({
        "usable": True, "version": version, "generation": generation,
        "adapter": f"opencode-v{generation}" if generation in (1, 2) else "unavailable",
        "supported": policy_supported and version_supported,
        "minimum_version": minimum_text, "path_ready": in_path(path),
        "identity": {"size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns,
                     "sha256": sha256(path)},
    })
    if not policy_supported:
        item["failure"] = "RUNTIME_UNSUPPORTED"
    elif not version_supported:
        item["failure"] = "RUNTIME_UNSUPPORTED"
    return item


def discover(binary: str | None = None) -> dict[str, Any]:
    policy = json.loads((ROOT / "config/runtime-policy.json").read_text(encoding="utf-8"))["opencode"]
    if binary:
        inspected = [inspect_candidate(Path(binary).expanduser().absolute(), "explicit lifecycle target",
                                       policy["minimum_versions"], policy["supported_majors"])]
    else:
        inspected = [inspect_candidate(path, source, policy["minimum_versions"], policy["supported_majors"])
                     for path, source in candidates()]
    usable = [item for item in inspected if item["usable"]]
    supported = next((item for item in usable if item["supported"]), None)
    selected = supported or (usable[0] if usable else None)
    return {
        "schema_version": 1,
        "found": selected is not None,
        "runtime": selected,
        "candidates": inspected,
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_state(result: dict[str, Any]) -> None:
    runtime = result.get("runtime")
    if not isinstance(runtime, dict) or not runtime.get("supported"):
        raise ValueError("cannot persist a missing or unsupported OpenCode runtime")
    destination = paths()["state"]
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    record = {"schema_version": 1, "runtime": {
        "kind": "opencode", "executable": runtime["executable"], "version": runtime["version"],
        "generation": runtime["generation"], "adapter": runtime["adapter"],
        "identity": runtime["identity"], "last_verified_at": result["validated_at"],
    }}
    fd, temporary = tempfile.mkstemp(prefix=".runtime.", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("discover", "record"), nargs="?", default="discover")
    parser.add_argument("--format", choices=("json", "text", "path"), default="json")
    parser.add_argument("--binary", help="Validate and persist this explicit absolute runtime path")
    args = parser.parse_args()
    try:
        result = discover(args.binary)
        if args.action == "record":
            write_state(result)
        runtime = result.get("runtime") or {}
        if args.format == "path":
            print(runtime.get("executable") or "")
        elif args.format == "text":
            print("OpenCode Runtime")
            print("────────────────")
            print(f"Installed             {'YES' if runtime.get('installed') else 'NO'}")
            print(f"Usable                {'YES' if runtime.get('usable') else 'NO'}")
            if runtime:
                print(f"Executable            {runtime.get('executable')}")
                print(f"Version               {runtime.get('version')}")
                print(f"Generation            {runtime.get('generation')}")
                print(f"Adapter               {runtime.get('adapter')}")
                print(f"Compatibility         {'SUPPORTED' if runtime.get('supported') else runtime.get('failure')}")
                print(f"PATH integration      {'READY' if runtime.get('path_ready') else 'NOT READY'}")
            else:
                print("Executable            not found")
            print(f"Network required      NO")
        else:
            print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
