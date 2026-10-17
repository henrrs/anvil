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
    patch_release_doc = f"docs/versions/v{version}.md"
    release_doc = patch_release_doc if (ROOT / patch_release_doc).is_file() else f"docs/versions/v{version.rsplit('.', 1)[0]}.md"
    required = {
        "CHANGELOG.md": [f"## [{version}]"],
        release_doc: [f"# Anvil {version}", "make update-runtime", "exact validated", "Network required"],
        "docs/versions/README.md": ["Anvil 2.2 + OpenCode 1", "Anvil 2.2 + OpenCode 2", "Anvil 2.3 + OpenCode 1", "Anvil 2.3 + OpenCode 2", "Anvil 2.4 + OpenCode 1", "Anvil 2.4 + OpenCode 2", "Databricks live system catalog and FinOps", "Topology-aware Databricks auth setup", "Runtime quiescing during Anvil upgrade", "Runtime-major migration command", "do not require OpenCode 2"],
        "docs/versions/v2.1.md": ["Runtime Independence", "make upgrade", "migrate-runtime", "make capabilities", "/distill", "stale"],
        "docs/migrations/v1-to-v2.md": ["make upgrade", "migrate-runtime", "rollback", "rehearsal"],
        "docs/migrations/v2-to-v2.1.md": ["make upgrade", "migrate-runtime", "OPENCODE_MAJOR", "rollback", "runtime policy"],
        "docs/migrations/v2.1-to-v2.2.md": ["make upgrade", "DRY_RUN=1", "Databricks", "rollback", "OpenCode major"],
        "docs/migrations/v2.2-to-v2.3.md": ["make databricks-setup", "DRY_RUN=1", "SDK fallback", "rollback", "OpenCode major"],
        "docs/migrations/v2.3-to-v2.3.1.md": ["make upgrade", "make update-runtime", "OpenCode release endpoint", "Network required NO", "rollback"],
        "docs/migrations/v2.3.1-to-v2.4.0.md": ["make upgrade DRY_RUN=1", "SIGTERM", "SIGKILL", "make databricks-setup", "OUTPUT=json", "external terminal"],
        "docs/migrations/v2.5.0-to-v2.6.0.md": ["make upgrade", "make doctor", "make capabilities", "schema 3", "read-only"],
        "docs/runtime-compatibility.md": ["1.18.18", "2.0.0", "opencode-v1", "opencode-v2", "offline profile fixture", "minimum supported CLI", "1.0.0", "make update-runtime", "exact validated OpenCode executable"],
        "docs/RELEASING.md": ["PATCH", "MINOR", "MAJOR", "make test", "offline", "runtime compatibility", "runtime independence"],
        "docs/opencode-compatibility.md": ["dist-tag", "migrate-v1", "npm", "OpenCode 1.x and 2.x", "local CLI fixtures"],
        "docs/architecture.md": ["Databricks capability", "official CLI", "live workspace discovery", "make update-runtime", "Network required", "Anvil-scoped backup", "Public command presentation", "auth_strategy.py", "SIGTERM"],
        "docs/databricks/README.md": ["official Databricks CLI", "make databricks-setup", "OpenCode 2"],
        "docs/databricks/setup.md": ["make databricks-setup OUTPUT=json", "Azure CLI device-code", "internal to Anvil", "NOT_CONFIGURED"],
        "docs/databricks/authentication.md": ["OAuth U2M", "0600", "secure credential storage", "make databricks-setup", "azure-cli", "device-code", "does not copy tokens"],
        "docs/databricks/execution.md": ["Command Execution API", "Statement Execution API", "100-row cap", "approval"],
        "docs/databricks/system-tables.md": ["2026-10-16", "SHOW SCHEMAS", "live schema", "read-only"],
        "docs/databricks/finops.md": ["Evidence Confidence Score", "shared all-purpose", "not a total cloud bill"],
        "docs/databricks/security.md": ["token", "system-table", "silently", "credential"],
        "docs/databricks/testing.md": ["offline", "tests/fixtures/bin/databricks", "do not resolve/download OpenCode", "topology-aware auth selection", "human/JSON presentation"],
        "docs/databricks/readiness.md": ["CONFIGURED", "AUTHENTICATED", "WORKSPACE_VALIDATED", "CAPABILITIES_DISCOVERED", "CLI_PROCESS_TIMEOUT", "15 minutes", "process-group"],
        "docs/decisions/ADR-0013-databricks-readiness-provider-validation.md": ["same production provider", "schema-3", "permission denials", "MINOR"],
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
