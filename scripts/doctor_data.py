#!/usr/bin/env python3
"""Read-only Anvil runtime, memory and workspace health checks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from configure import _audit_v1, audit, parse_jsonc
import memory
import source_registry


EXPECTED_SKILLS = {
    "anvil-memory", "anvil-spark-performance", "anvil-delta-lake",
    "anvil-databricks", "anvil-data-ingestion",
}
EXPECTED_COMMANDS = {"remember", "recall", "distill"}


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def read_config(path: Path) -> dict:
    try:
        value = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}


def project_overrides(cwd: Path) -> list[str]:
    project = cwd.resolve()
    root = next((p for p in (project, *project.parents) if (p / ".git").exists()), project)
    found: list[str] = []
    cursor = project
    while True:
        for name in ("opencode.json", "opencode.jsonc", "AGENTS.md", "CLAUDE.md"):
            path = cursor / name
            if path.is_file():
                found.append(str(path))
        for name in (".opencode", ".claude", ".agents"):
            path = cursor / name
            if path.is_dir():
                found.append(str(path))
        if cursor == root or cursor.parent == cursor:
            break
        cursor = cursor.parent
    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True, help="XDG data home")
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--runtime-major", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()

    config_path = args.config_dir / "opencode.jsonc"
    config = read_config(config_path)
    runtime_major = args.runtime_major
    config_audit = _audit_v1 if runtime_major == 1 else audit
    problems = config_audit(config_path) if config else ["Anvil runtime config is missing or invalid"]
    warnings: list[str] = []
    agents_key = "agent" if runtime_major == 1 else "agents"
    agents = config.get(agents_key, {}) if isinstance(config.get(agents_key), dict) else {}
    anvil = agents.get("anvil", {}) if isinstance(agents.get("anvil"), dict) else {}
    if runtime_major == 1:
        legacy_permissions = anvil.get("permission", {}) if isinstance(anvil.get("permission"), dict) else {}
        rules = {
            (action, resource): effect
            for action, rule in legacy_permissions.items()
            for resource, effect in (rule.items() if isinstance(rule, dict) else [("*", rule)])
        }
    else:
        permissions = anvil.get("permissions", []) if isinstance(anvil.get("permissions"), list) else []
        rules = {
            (rule.get("action"), rule.get("resource")): rule.get("effect")
            for rule in permissions if isinstance(rule, dict)
        }
    skills_dir = args.config_dir / "skills"
    skills = {
        path.name for path in skills_dir.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    } if skills_dir.is_dir() else set()
    commands_dir = args.config_dir / "commands"
    commands = {path.stem for path in commands_dir.glob("*.md")} if commands_dir.is_dir() else set()
    plugin_dir = args.config_dir / "plugins" / "anvil-core"
    plugin_file = plugin_dir / "index.ts"
    plugin_key = "plugin" if runtime_major == 1 else "plugins"
    plugin_entries = config.get(plugin_key, []) if isinstance(config.get(plugin_key), list) else []
    expected_plugin = "./plugins/anvil-core" if runtime_major == 2 else None
    unexpected_plugins = [item for item in plugin_entries if item != expected_plugin]
    mcp_config = config.get("mcp", {}) if isinstance(config.get("mcp"), dict) else {}
    mcp_servers = mcp_config.get("servers", {}) if isinstance(mcp_config.get("servers"), dict) else {}
    compaction = config.get("compaction", {}) if isinstance(config.get("compaction"), dict) else {}
    output = config.get("tool_output", {}) if isinstance(config.get("tool_output"), dict) else {}
    reference_config = config.get("references", {}) if runtime_major == 2 else {}
    reference = reference_config.get("anvil-knowledge", {}) if isinstance(reference_config, dict) else {}
    reference_path = reference.get("path") if isinstance(reference, dict) else None
    knowledge_root = Path(reference_path) if isinstance(reference_path, str) and reference_path else None
    data_root = args.data_dir / "anvil"
    memory_root = data_root / "memory"
    memory_audit = memory.audit()
    registry_audit = source_registry.audit()
    installation = read_json(data_root / "installation.json")
    migration = installation.get("migration", {})
    if not isinstance(migration, dict):
        migration = {}
    overrides = project_overrides(args.cwd)

    if skills != EXPECTED_SKILLS:
        problems.append(f"Anvil skill set mismatch: missing={sorted(EXPECTED_SKILLS - skills)}, extra={sorted(skills - EXPECTED_SKILLS)}")
    if commands != EXPECTED_COMMANDS:
        problems.append(f"Anvil command set mismatch: missing={sorted(EXPECTED_COMMANDS - commands)}, extra={sorted(commands - EXPECTED_COMMANDS)}")
    if runtime_major == 2 and (not plugin_file.is_file() or "anvil_memory_search" not in plugin_file.read_text(encoding="utf-8", errors="replace")):
        problems.append("anvil-core memory search plugin entrypoint is missing")
    if unexpected_plugins:
        warnings.append(f"additional global plugins are configured: {unexpected_plugins}")
    if mcp_servers:
        warnings.append(f"global MCP servers are configured: {sorted(mcp_servers)}")
    if memory_audit["invalid"]:
        warnings.append(f"invalid Markdown memory files: {memory_audit['invalid']}")
    if registry_audit["invalid"]:
        warnings.append(f"invalid source registry records: {registry_audit['invalid']}")
    if registry_audit["drifted"]:
        warnings.append(f"source files changed or are missing since distillation: {registry_audit['drifted']}")
    if runtime_major == 2 and (knowledge_root is None or not knowledge_root.is_dir()):
        warnings.append("anvil-knowledge reference root is missing or inaccessible")
    if not memory_root.is_dir() or not os.access(memory_root, os.R_OK | os.X_OK | os.W_OK):
        problems.append("Anvil memory root is missing or inaccessible")
    if overrides:
        warnings.append("project-level OpenCode instructions or overrides are active")

    print(f"OpenCode {runtime_major} configuration")
    print(f"  runtime config         {'valid' if not config_audit(config_path) else 'invalid'}")
    print(f"  default agent          {config.get('default_agent', 'missing')}")
    print(f"  model pinned           {'yes' if config.get('model') or anvil.get('model') else 'no'}")
    denied_subagents = rules.get(("task", "*")) == "deny" if runtime_major == 1 else rules.get(("subagent", "*")) == "deny"
    print(f"  subagents denied       {'yes' if denied_subagents else 'no'}")
    print(f"  anvil-core configured  {'yes' if runtime_major == 2 and './plugins/anvil-core' in plugin_entries and plugin_file.is_file() else 'no (runtime fallback)'}")
    print(f"  memory search tool     {'native plugin' if runtime_major == 2 else 'file helper fallback'}")
    print(f"  global MCP count       {len(mcp_servers)}")
    print(f"  unexpected plugins     {len(unexpected_plugins)}")
    print(f"  native compaction      {'enabled' if compaction.get('auto') else 'missing'}")
    print(f"  tool output cap        {output.get('max_lines', 'not available')} lines / {output.get('max_bytes', 'not available')} bytes")
    print("Memory and knowledge")
    print(f"  memory root            {memory_root}")
    print(f"  valid / invalid        {memory_audit['valid']} / {memory_audit['invalid']}")
    if runtime_major == 2:
        print(f"  knowledge reference    {knowledge_root or 'missing'} ({'present' if knowledge_root and knowledge_root.is_dir() else 'missing'})")
    else:
        print("  knowledge access       direct file paths (References not supported)")
    print(f"  source registry        {registry_audit['sources']} records, {registry_audit['invalid']} invalid, {registry_audit['drifted']} drifted")
    print("Migration and workspace")
    print(f"  previous Anvil version {installation.get('previous_anvil_version') or migration.get('from_anvil') or 'unknown'}")
    print(f"  migration state        {migration.get('status', 'not recorded')}")
    print(f"  project overrides      {', '.join(overrides) if overrides else 'none'}")
    for problem in problems:
        print(f"ERROR {problem}")
    for warning in warnings:
        print(f"WARN  {warning}")
    if problems:
        print("Status: BROKEN")
        return 1
    if warnings:
        print("Status: WARNING")
        return 2
    print("Status: HEALTHY")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
