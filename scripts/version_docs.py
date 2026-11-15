#!/usr/bin/env python3
"""Check the current OpenCode 1 release artifacts and the small supported doc set."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    "README.md",
    "docs/architecture.md",
    "docs/lifecycle.md",
    "docs/capabilities.md",
    "docs/development.md",
)


def main() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    import managed_config
    from semver import parse

    errors: list[str] = []
    try:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if parse(version) is None:
            errors.append("VERSION is not semantic version text")

        inventory = json.loads((ROOT / "config/managed-inventory.json").read_text(encoding="utf-8"))
        if inventory.get("managed_artifacts", {}).get("release") != version:
            errors.append("managed artifact inventory release does not match VERSION")
        policy = json.loads((ROOT / "config/runtime-policy.json").read_text(encoding="utf-8"))
        if policy.get("opencode", {}).get("supported_majors") != [1]:
            errors.append("runtime policy must support only OpenCode 1.x")

        for category, directory, suffix in (
            ("skills", ROOT / "config/skills", ""),
            ("commands", ROOT / "config/commands", ".md"),
        ):
            declared = inventory.get(category)
            actual = ({path.name for path in directory.iterdir() if path.is_dir()}
                      if not suffix else {path.stem for path in directory.glob("*.md")})
            if not isinstance(declared, dict) or set(declared) != actual:
                errors.append(f"managed inventory {category} do not match shipped files")
                continue
            for name, introduced in declared.items():
                if not isinstance(introduced, str) or not re.fullmatch(r"\d+\.\d+\.\d+", introduced):
                    errors.append(f"managed inventory has an invalid introduction release for {category}/{name}")
                elif parse(version) is not None and parse(introduced) > parse(version):
                    errors.append(f"{category}/{name} is marked newer than VERSION")

        artifacts = managed_config._release_artifacts_for_major(1)
        declared_artifacts = inventory.get("managed_artifacts", {}).get("files", {})
        if set(artifacts) != set(declared_artifacts):
            missing = sorted(set(artifacts) ^ set(declared_artifacts))
            errors.append("managed release artifact membership differs from the current Anvil profile"
                          + (f": {missing[0]}" if missing else ""))
        for relative, digest in artifacts.items():
            if digest is not None:
                try:
                    managed_config._verify_release_artifact(relative, version, 1)
                except (OSError, ValueError, RuntimeError) as exc:
                    errors.append(f"managed artifact {relative} failed verification: {exc}")
                    break

        for relative in DOCS:
            if not (ROOT / relative).is_file():
                errors.append(f"required document is missing: {relative}")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        errors.append(str(exc))

    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(f"OK Anvil {version}: OpenCode 1 artifacts, inventory and core documentation are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
