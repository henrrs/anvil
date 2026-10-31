#!/usr/bin/env python3
"""Check that the active SemVer release has matching durable documentation."""

from __future__ import annotations

import re
import sys
import json
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
        "README.md": [f"Anvil {version}", "make upgrade DRY_RUN=1", "make reforge", "docs/system-map.md", "docs/quality-audit.md", "docs/analytical-intelligence.md"],
        release_doc: [f"# Anvil {version}", "make update-runtime", "exact validated", "Network required"],
        "docs/versions/README.md": ["Anvil 2.2 + OpenCode 1", "Anvil 2.2 + OpenCode 2", "Anvil 2.3 + OpenCode 1", "Anvil 2.3 + OpenCode 2", "Anvil 2.4 + OpenCode 1", "Anvil 2.4 + OpenCode 2", "Anvil 2.7 + OpenCode 1", "Anvil 2.7 + OpenCode 2", "Communication & artifact intelligence", "Binary PPTX/DOCX/PDF rendering", "Databricks live system catalog and FinOps", "Topology-aware Databricks auth setup", "Runtime quiescing during Anvil upgrade", "Runtime-major migration command", "do not require OpenCode 2"],
        "docs/versions/v2.7.0.md": ["Communication & Artifact Intelligence", "OpenCode 1.x and 2.x", "make upgrade", "exact validated", "Binary PPTX", "Network required"],
        "docs/communication-artifact-intelligence.md": ["Evidence → Finding → Analysis → Insight → Decision Relevance", "percentage-point change", "PENDING_MODEL", "pdftotext", "PASS_WITH_WARNINGS", "does not write to Anvil memory", "visual_intent", "critique PLAN.json"],
        "docs/decisions/ADR-0015-communication-artifact-intelligence.md": ["Status:** Accepted", "runtime-independent", "PENDING_MODEL", "No third-party Python package"],
        "docs/decisions/ADR-0019-analytical-editorial-visual-intelligence.md": ["Status:** Accepted", "renderer-independent", "SCENARIO", "PENDING_MODEL_REVIEW", "NOT RELEASE READY"],
        "docs/communication-intelligence-v2.11-report.md": ["Current Architecture Assessment", "Editorial Intelligence", "Motion Intelligence", "NOT RELEASE READY", "baseline SHA-256", "PPTX/GIF"],
        "docs/versions/v2.1.md": ["Runtime Independence", "make upgrade", "migrate-runtime", "make capabilities", "/distill", "stale"],
        "docs/migrations/v1-to-v2.md": ["make upgrade", "migrate-runtime", "rollback", "rehearsal"],
        "docs/migrations/v2-to-v2.1.md": ["make upgrade", "migrate-runtime", "OPENCODE_MAJOR", "rollback", "runtime policy"],
        "docs/migrations/v2.1-to-v2.2.md": ["make upgrade", "DRY_RUN=1", "Databricks", "rollback", "OpenCode major"],
        "docs/migrations/v2.2-to-v2.3.md": ["make databricks-setup", "DRY_RUN=1", "SDK fallback", "rollback", "OpenCode major"],
        "docs/migrations/v2.3-to-v2.3.1.md": ["make upgrade", "make update-runtime", "OpenCode release endpoint", "Network required NO", "rollback"],
        "docs/migrations/v2.3.1-to-v2.4.0.md": ["make upgrade DRY_RUN=1", "SIGTERM", "SIGKILL", "make databricks-setup", "OUTPUT=json", "external terminal"],
        "docs/migrations/v2.5.0-to-v2.6.0.md": ["make upgrade", "make doctor", "make capabilities", "schema 3", "read-only"],
        "docs/runtime-compatibility.md": ["1.18.18", "2.0.0", "opencode-v1", "opencode-v2", "offline profile fixture", "minimum supported CLI", "1.0.0", "make update-runtime", "exact validated OpenCode executable", "communication/artifact workflow"],
        "docs/RELEASING.md": ["PATCH", "MINOR", "MAJOR", "make test", "offline", "runtime compatibility", "runtime independence"],
        "docs/opencode-compatibility.md": ["dist-tag", "migrate-v1", "npm", "OpenCode 1.x and 2.x", "local CLI fixtures"],
        "docs/architecture.md": ["Databricks capability", "official CLI", "live workspace discovery", "make update-runtime", "Network required", "Anvil-scoped backup", "Public command presentation", "auth_strategy.py", "SIGTERM", "Communication and artifact intelligence", "semantic_claim_review"],
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
        "docs/versions/v2.8.0.md": ["MIGRATION_REQUIRED", "STALE", "managed-file", "RECOVERY_REQUIRED", "make upgrade DRY_RUN=1", "exact validated", "Network required", "disabled in the source profile", "writable config parent"],
        "docs/migrations/v2.7.1-to-v2.8.0.md": ["RECOVERY_REQUIRED", "DRY_RUN=1", "make update-runtime", "make migrate-runtime", "rollback"],
        "docs/decisions/ADR-0016-lifecycle-state-and-managed-file-migration.md": ["Status:** Accepted", "MIGRATION_REQUIRED", "managed-file", "durable transaction journal", "downgrade"],
        "docs/command-contracts.md": ["MIGRATION_REQUIRED", "UNSUPPORTED", "RECOVERY_REQUIRED", "source-to-target plan"],
        "docs/versions/v2.9.0.md": ["Requirements Model", "Architecture Model", "Work Model", "exact validated", "Network required", "make update-runtime", "READY WITH KNOWN LIMITATIONS"],
        "docs/migrations/v2.8.0-to-v2.9.0.md": ["make upgrade DRY_RUN=1", "WORK_STATE_STALE", "separate", "make update-runtime", "rollback"],
        "docs/versions/v2.10.0.md": ["Adaptive Engineering Execution", "Requirements", "Architecture", "Work", "make update-runtime", "exact validated", "Network required", "READY WITH KNOWN LIMITATIONS", "2.6.x", "18/18"],
        "docs/migrations/v2.9.0-to-v2.10.0.md": ["make upgrade DRY_RUN=1", "schema 1", "DIRECT", "EXPAND", "--milestone", "2.6.x", "rollback"],
        "docs/versions/v2.11.0.md": ["Analytical, Editorial & Visual Communication Intelligence", "SCENARIO", "financial", "artifacts.py critique", "static renderer fallback", "NOT RELEASE READY", "2.6.x", "Network required"],
        "docs/migrations/v2.10.0-to-v2.11.0.md": ["make upgrade DRY_RUN=1", "artifacts.py critique", "SCENARIO", "2.6.x", "rollback", "No runtime or persistent-data migration"],
        "docs/versions/v2.12.0.md": ["Editorial Intelligence & Local Environment Preservation", "six prior minor releases", "external plugins", "MCP servers", "scoped", "NOT RELEASE READY", "3,511", "878"],
        "docs/migrations/v2.11.0-to-v2.12.0.md": ["make upgrade DRY_RUN=1", "shared OpenCode profile", "scoped", "rollback", "NOT RELEASE READY"],
        "docs/decisions/ADR-0020-editorial-intelligence-and-local-config-preservation.md": ["Status:** Accepted", "Anvil-owned top-level keys", "Snapshot only", "NOT RELEASE READY"],
        "docs/environment-preservation-v2.12-report.md": ["Current Architecture Assessment", "OpenCode plugin preservation", "Enterprise/local configuration preservation", "Baseline vs candidate observations", "Performance impact", "NOT RELEASE READY"],
        "docs/versions/v2.13.0.md": ["Intent Compilation & Analytical Intelligence", "make update-runtime", "exact validated", "Network required", "NOT RELEASE READY", "FAST (4 operations) at **151.3 ms**", "STANDARD (12) at **189.6 ms**", "DEEP (20) at **235.7 ms**", "live-model"],
        "docs/migrations/v2.12.0-to-v2.13.0.md": ["make upgrade DRY_RUN=1", "scripts/analyze.py", "same-major", "seven prior minor releases", "NOT RELEASE READY"],
        "docs/intent-analytical-report-v2.13.0.md": ["Architecture assessment", "missed material findings", "two source scans", "Anti-overengineering review", "Release recommendation", "NOT READY"],
        "docs/analytical-intelligence.md": ["scripts/analyze.py profile", "FAST", "STANDARD", "DEEP", "source_sha256", "Pareto", "Correlation is association only", "make capabilities"],
        "docs/intent-analytical-architecture-assessment.md": ["Anvil 2.12.0", "scripts/analysis", "No runtime profile change", "artifact-independent analytical result"],
        "docs/decisions/ADR-0021-intent-compilation-and-analytical-intelligence.md": ["Status:** Accepted", "scripts/analysis", "artifact-independent", "No network"],
        "docs/system-map.md": ["Anvil 2.13.0 candidate", "Intent and analytical intelligence", "scripts/analysis", "tests/run.sh"],
        "docs/versions/README.md": ["Anvil 2.13 + OpenCode 1", "Anvil 2.13 + OpenCode 2", "Anvil 2.13 adds task-local intent compilation"],
        "docs/adaptive-engineering.md": ["requested change", "next safe", "repository size", "no numeric risk score", "completion gates", "NOT MEASURED"],
        "docs/decisions/ADR-0018-adaptive-engineering-execution.md": ["Status:** Accepted", "task-local", "milestone-scoped", "scoring engine", "OpenCode 1/2"],
        "docs/versions/README.md": ["Anvil 2.10 + OpenCode 1", "Anvil 2.10 + OpenCode 2", "Anvil 2.11 + OpenCode 1", "Anvil 2.11 + OpenCode 2", "Anvil 2.12 + OpenCode 1", "Anvil 2.12 + OpenCode 2", "Adaptive task-local activation", "Milestone-scoped architecture checks", "Anvil 2.11.0 adds the next layer", "Anvil 2.12 refines comparison context"],
        "docs/engineering.md": ["IMPLEMENTED", "VERIFIED", "XDG_STATE_HOME", "resume", "durable memory"],
        "docs/engineering-internals.md": ["atomic", "revision", "semantic", "24 KiB", "Requirements", "Architecture", "Work"],
        "docs/engineering-evaluation.md": ["baseline", "candidate", "ingestion", "scheduler", "not measured", "OpenCode 1.19.3"],
        "docs/decisions/ADR-0017-progressive-engineering-state.md": ["Status:** Accepted", "three separate models", "one model-neutral", "atomic"],
    }
    errors = []
    inventory_path = ROOT / "config/managed-inventory.json"
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        actual_skills = {path.name for path in (ROOT / "config/skills").iterdir() if path.is_dir()}
        actual_commands = {path.stem for path in (ROOT / "config/commands").glob("*.md")}
        for category, actual in (("skills", actual_skills), ("commands", actual_commands)):
            declared = inventory.get(category, {})
            if not isinstance(declared, dict) or set(declared) != actual:
                errors.append(f"config/managed-inventory.json {category} do not match the shipped set")
                continue
            for name, introduced in declared.items():
                if not re.fullmatch(r"\d+\.\d+\.\d+", str(introduced)):
                    errors.append(f"config/managed-inventory.json has an invalid introduction version for {category}/{name}")
                elif tuple(map(int, str(introduced).split("."))) > tuple(map(int, version.split("."))):
                    errors.append(f"config/managed-inventory.json introduction for {category}/{name} is newer than VERSION")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        errors.append(f"config/managed-inventory.json is unreadable or invalid: {exc}")
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
