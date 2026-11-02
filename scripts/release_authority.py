#!/usr/bin/env python3
"""Preflight that protects production installs from uncommitted release artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import managed_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify",))
    args = parser.parse_args()
    changed = managed_config.release_checkout_changes()
    if changed:
        print("Target release cannot be verified against the committed checkout.", file=sys.stderr)
        print(f"{len(changed)} release source/control file(s) differ from HEAD:", file=sys.stderr)
        for relative in changed[:30]:
            print(f"  {relative}", file=sys.stderr)
        if len(changed) > 30:
            print(f"  ... {len(changed) - 30} more path(s)", file=sys.stderr)
        print("Commit or revert these release changes before running a production upgrade.", file=sys.stderr)
        return 2
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    print(f"PASS target release {version} matches committed release artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
