#!/usr/bin/env python3
"""Find running OpenCode executables without stopping or modifying them."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def effective_paths(home: str, config_home: str | None, data_home: str | None, state_home: str | None) -> set[str]:
    root = Path(home).expanduser().resolve()
    config = Path(config_home).expanduser() if config_home else root / ".config"
    data = Path(data_home).expanduser() if data_home else root / ".local" / "share"
    state = Path(state_home).expanduser() if state_home else root / ".local" / "state"
    return {str((path / "opencode").resolve()) for path in (config, data, state)}


def process_environment(pid: int) -> dict[str, str] | None:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes().split(bytes([0]))
    except OSError:
        return None
    values: dict[str, str] = {}
    for item in raw:
        key, separator, value = item.partition(b"=")
        if separator:
            values[key.decode(errors="ignore")] = value.decode(errors="ignore")
    return values


def active_processes() -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    proc_root = Path("/proc")
    if proc_root.is_dir():
        target_home = os.environ.get("HOME", str(Path.home()))
        target_paths = effective_paths(
            target_home, os.environ.get("XDG_CONFIG_HOME"), os.environ.get("XDG_DATA_HOME"),
            os.environ.get("XDG_STATE_HOME"),
        )
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid != os.geteuid():
                    continue
                executable = os.readlink(entry / "exe")
                if Path(executable.removesuffix(" (deleted)")).name.lower() == "opencode":
                    environment = process_environment(int(entry.name))
                    if environment is None:
                        result.append((int(entry.name), executable))
                        continue
                    process_home = environment.get("HOME", target_home)
                    process_paths = effective_paths(
                        process_home, environment.get("XDG_CONFIG_HOME"), environment.get("XDG_DATA_HOME"),
                        environment.get("XDG_STATE_HOME"),
                    )
                    if target_paths & process_paths:
                        result.append((int(entry.name), executable))
            except (OSError, ValueError):
                continue
        return sorted(result)
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,comm="], capture_output=True, text=True, timeout=5, check=True
        )
        for line in completed.stdout.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) == 2 and fields[0].isdigit() and Path(fields[1]).name.lower() == "opencode":
                # macOS does not expose a procfs environment. Conservatively
                # treat a same-user OpenCode process as active there.
                result.append((int(fields[0]), fields[1]))
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("cannot safely determine whether OpenCode is running")
    return sorted(result)


def main() -> int:
    try:
        active = active_processes()
    except RuntimeError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    if active:
        print("OpenCode is running; close its TUI and service before Anvil upgrade:")
        for pid, executable in active:
            print(f"  pid {pid}: {executable}")
        return 1
    print("No OpenCode process is using the configured Anvil data paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
