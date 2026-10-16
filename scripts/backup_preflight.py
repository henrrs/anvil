#!/usr/bin/env python3
"""Check local Anvil backup readiness without creating files."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def tree_size(root: Path) -> int:
    if not root.exists():
        return 0
    if root.is_file():
        return root.stat().st_size
    total = 0
    for entry in root.rglob("*"):
        if entry.is_symlink():
            continue
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def check(config: Path, data: Path) -> tuple[bool, str]:
    destination = data / "anvil" / "backups"
    for path in (config, data, data / "anvil", destination):
        if path.is_symlink():
            return False, f"backup preflight found a symbolic-link path: {path}"
    if not config.is_dir() or not os.access(config, os.R_OK | os.X_OK):
        return False, f"Anvil configuration is not a readable directory: {config}"
    probe = destination
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir() or not os.access(probe, os.W_OK | os.X_OK):
        return False, f"backup destination is not writable: {destination}"
    if destination.exists() and not destination.is_dir():
        return False, f"backup destination is not a safe directory: {destination}"
    needed = max(8 * 1024 * 1024, tree_size(config) + tree_size(data / "anvil" / "installation.json") + tree_size(data / "anvil" / "runtime.json") + 1024 * 1024)
    try:
        space = os.statvfs(probe)
        available = space.f_bavail * space.f_frsize
    except OSError:
        return False, "could not verify local free space for the Anvil backup"
    if available < needed:
        return False, f"insufficient local free space for backup (need about {needed} bytes)"
    return True, "backup destination and local space are ready"


def main() -> int:
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser()
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))).expanduser()
    okay, message = check(config_home / "opencode", data_home)
    print(message)
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
