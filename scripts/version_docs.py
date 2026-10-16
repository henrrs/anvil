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
    release_doc = f"docs/versions/v{version.rsplit('.', 1)[0]}.md"
    required = {
        "CHANGELOG.md": [f"## [{version}]"],
        release_doc: [f"# Anvil {version}"],
        "docs/versions/README.md": ["| Capability | Anvil V1 | Anvil 2.x + OpenCode 1 | Anvil 2.x + OpenCode 2 |", "make upgrade", "source registry", "Native Reference", "/distill", "native stats", "Runtime-major migration command"],
        "docs/versions/v2.1.md": ["Runtime Independence", "make upgrade", "migrate-runtime", "make capabilities", "/distill", "stale"],
        "docs/migrations/v1-to-v2.md": ["make upgrade", "migrate-runtime", "rollback", "rehearsal"],
        "docs/migrations/v2-to-v2.1.md": ["make upgrade", "migrate-runtime", "OPENCODE_MAJOR", "rollback", "runtime policy"],
        "docs/runtime-compatibility.md": ["1.18.18", "opencode-v1", "opencode-v2", "tested candidate"],
        "docs/RELEASING.md": ["PATCH", "MINOR", "MAJOR", "make test", "runtime compatibility"],
        "docs/opencode-compatibility.md": ["2.x.y", "dist-tag", "migrate-v1", "npm", "OpenCode 1.x and 2.x"],
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
