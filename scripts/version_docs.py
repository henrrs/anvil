#!/usr/bin/env python3
"""Check that the active SemVer release has matching durable documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("VERSION must contain one SemVer version")
    major = version.split(".", 1)[0]
    required = {
        "CHANGELOG.md": [f"## [{version}]"],
        f"docs/versions/v{major}.md": [f"# Anvil {version}"],
        "docs/versions/README.md": ["| Capability | V1 | V2 |", "make upgrade", "Migration rehearsal", "Memory search tool", "Knowledge References", "/distill", "make stats"],
        "docs/migrations/v1-to-v2.md": ["make upgrade", "rollback", "rehearsal"],
        "docs/RELEASING.md": ["PATCH", "MINOR", "MAJOR", "make test"],
        "docs/opencode-compatibility.md": ["2.x.y", "dist-tag", "migrate-v1", "npm"],
    }
    errors = []
    for relative, phrases in required.items():
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase.casefold() not in text.casefold():
                errors.append(f"{relative} is missing {phrase!r}")
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(f"OK Anvil {version} has matching changelog, version history, capability matrix and migration/release docs")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
