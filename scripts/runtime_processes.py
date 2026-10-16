#!/usr/bin/env python3
"""Read-only discovery of this Anvil installation's exact OpenCode processes."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


def effective_paths(environment: dict[str, str]) -> set[str]:
    home_value = environment.get("HOME") or str(Path.home())
    home = Path(home_value).expanduser().resolve()
    values = (
        environment.get("XDG_CONFIG_HOME") or str(home / ".config"),
        environment.get("XDG_DATA_HOME") or str(home / ".local/share"),
        environment.get("XDG_STATE_HOME") or str(home / ".local/state"),
    )
    result = set()
    for value in values:
        if value == "~":
            value = str(home)
        elif value.startswith("~/"):
            value = str(home / value[2:])
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            continue
        result.add(str((candidate / "opencode").resolve()))
    return result


def read_stat(pid: int) -> dict[str, Any] | None:
    if Path("/proc").is_dir():
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            closing = raw.rfind(")")
            fields = raw[closing + 2:].split()
            return {"state": fields[0], "ppid": int(fields[1]), "start_time": fields[19]}
        except (OSError, ValueError, IndexError):
            return None
    try:
        result = subprocess.run(["ps", "-o", "stat=,ppid=,lstart=", "-p", str(pid)],
                                capture_output=True, text=True, timeout=3, check=True)
        fields = result.stdout.strip().split(None, 2)
        if len(fields) != 3:
            return None
        return {"state": fields[0], "ppid": int(fields[1]), "start_time": fields[2]}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def read_environment(pid: int) -> dict[str, str] | None:
    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(bytes([0]))
    except OSError:
        return None
    result: dict[str, str] = {}
    # Consume only path identity fields. Other inherited values are discarded
    # immediately and are never logged or persisted.
    for entry in entries:
        key, separator, value = entry.partition(b"=")
        if separator and key in {b"HOME", b"XDG_CONFIG_HOME", b"XDG_DATA_HOME", b"XDG_STATE_HOME"}:
            result[key.decode()] = value.decode(errors="ignore")
    return result


def canonical_argument(value: str) -> str | None:
    if not value.startswith("/"):
        return None
    try:
        return str(Path(value).resolve(strict=False))
    except OSError:
        return None


def is_script(path: str) -> bool:
    try:
        with open(path, "rb") as stream:
            return stream.read(2) == b"#!"
    except OSError:
        return False


def process_candidate(pid: int, binary: str, target_paths: set[str], self_ancestors: set[int]) -> dict[str, Any] | None:
    try:
        process_stat = read_stat(pid)
        if process_stat is None or str(process_stat["state"]).startswith("Z"):
            return None
        if Path(f"/proc/{pid}").stat().st_uid != os.geteuid():
            return None
        executable_link = os.readlink(f"/proc/{pid}/exe")
        executable = str(Path(executable_link.removesuffix(" (deleted)")).resolve(strict=False))
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().split(bytes([0]))
        arguments = [item.decode(errors="ignore") for item in raw if item]
    except (OSError, ValueError):
        return None

    scope = "exact-executable" if executable == binary else None
    if scope is None:
        if is_script(binary) and len(arguments) > 1 and canonical_argument(arguments[1]) == binary:
            scope = "validated-runtime-script"
    if scope is None:
        return None

    process_environment = read_environment(pid)
    if process_environment is None:
        return {"pid": pid, "executable": binary, "scope": scope, "identity_verified": False,
                "start_time": process_stat["start_time"], "self_ancestor": pid in self_ancestors}
    matches = bool(target_paths & effective_paths(process_environment))
    if not matches:
        return None
    return {"pid": pid, "executable": binary, "scope": scope, "identity_verified": True,
            "start_time": process_stat["start_time"], "self_ancestor": pid in self_ancestors}


def ancestor_pids(pid: int) -> set[int]:
    result: set[int] = set()
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        process = read_stat(pid)
        if process is None:
            break
        pid = int(process["ppid"])
        if pid > 1:
            result.add(pid)
    return result


def discover_linux(binary: str) -> list[dict[str, Any]]:
    expected = str(Path(binary).expanduser().resolve(strict=True))
    target_paths = effective_paths(dict(os.environ))
    self_ancestors = ancestor_pids(os.getpid()) | {os.getpid()}
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            process = process_candidate(int(entry.name), expected, target_paths, self_ancestors)
            if process:
                found.append(process)
    return sorted(found, key=lambda item: int(item["pid"]))


def discover_ps(binary: str) -> list[dict[str, Any]]:
    """Use `ps` on systems without procfs; never guess from a process name."""
    expected = str(Path(binary).expanduser().resolve(strict=True))
    listing = subprocess.run(["ps", "-axo", "pid=,uid=,ppid=,comm="], capture_output=True,
                             text=True, timeout=5, check=True)
    self_ancestors: set[int] = set()
    parent = os.getpid()
    for _ in range(256):
        try:
            result = subprocess.run(["ps", "-o", "ppid=", "-p", str(parent)], capture_output=True,
                                    text=True, timeout=3, check=True)
            parent = int(result.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            break
        if parent <= 1 or parent in self_ancestors:
            break
        self_ancestors.add(parent)
    found = []
    for line in listing.stdout.splitlines():
        fields = line.split(None, 3)
        if len(fields) != 4 or not fields[0].isdigit() or int(fields[1]) != os.geteuid():
            continue
        pid = int(fields[0])
        try:
            detail = subprocess.run(["ps", "eww", "-p", str(pid), "-o", "command="], capture_output=True,
                                    text=True, timeout=3, check=True).stdout.strip()
            tokens = shlex.split(detail)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        if not tokens:
            continue
        arguments = tokens[:]
        env_start = next((i for i, token in enumerate(tokens) if token.startswith(("HOME=", "XDG_CONFIG_HOME=", "XDG_DATA_HOME=", "XDG_STATE_HOME="))), len(tokens))
        env = dict(token.split("=", 1) for token in tokens[env_start:] if "=" in token)
        argv = tokens[:env_start]
        process_stat = read_stat(pid)
        if process_stat is None or process_stat["state"].startswith("Z"):
            continue
        process_path = canonical_argument(argv[0]) if argv else None
        scope = "exact-executable" if process_path == expected else None
        if scope is None and is_script(expected) and len(argv) > 1 and canonical_argument(argv[1]) == expected:
            scope = "validated-runtime-script"
        if scope is None or not (effective_paths(env) & effective_paths(dict(os.environ))):
            continue
        found.append({"pid": pid, "executable": expected, "scope": scope, "identity_verified": True,
                      "start_time": process_stat["start_time"], "self_ancestor": pid in self_ancestors})
    return sorted(found, key=lambda item: int(item["pid"]))


def discover(binary: str) -> dict[str, Any]:
    expected = str(Path(binary).expanduser().resolve(strict=True))
    if not os.access(expected, os.X_OK):
        raise ValueError("validated OpenCode executable is not executable")
    if Path("/proc").is_dir():
        processes = discover_linux(expected)
    else:
        processes = discover_ps(expected)
    return {"schema_version": 1, "runtime_executable": expected, "processes": processes,
            "count": len(processes), "uncertain": any(not item["identity_verified"] for item in processes),
            "self_ancestor": any(item["self_ancestor"] for item in processes)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args()
    try:
        value = discover(args.binary)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"ERROR RUNTIME_DISCOVERY_FAILED: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(value, indent=2))
    else:
        print(f"OpenCode processes    {value['count']} running")
        for item in value["processes"]:
            suffix = " (upgrade is running inside this process)" if item["self_ancestor"] else ""
            print(f"  pid {item['pid']}{suffix}")
        if value["uncertain"]:
            print("Process identity could not be fully verified; no process should be signaled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
