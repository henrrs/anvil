#!/usr/bin/env python3
"""Refuse lifecycle mutation while this installation's runtime is active."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime_processes import discover  # noqa: E402


def main() -> int:
    try:
        runtime = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "runtime_state.py"), "discover", "--format", "json"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        runtime_record = json.loads(runtime.stdout)
        runtime_value = runtime_record.get("runtime") or {}
        binary = runtime_value.get("executable")
        if not binary or not os.access(binary, os.X_OK):
            print("No validated OpenCode executable is installed; no runtime process can be scoped.")
            return 0
        value = discover(binary)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR RUNTIME_DISCOVERY_FAILED: {exc}", file=sys.stderr)
        return 2
    if value["uncertain"]:
        print("ERROR OpenCode process identity could not be fully verified; lifecycle mutation is unsafe.", file=sys.stderr)
        return 2
    if value["processes"]:
        print("OpenCode is running against this installation's configured data paths:")
        for process in value["processes"]:
            suffix = " (this lifecycle command is running inside it)" if process["self_ancestor"] else ""
            print(f"  pid {process['pid']}{suffix}")
        return 1
    print("No OpenCode process is using the configured Anvil data paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
