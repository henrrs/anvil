#!/usr/bin/env python3
"""Read-only Anvil runtime, memory and workspace health checks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from configure import _audit_v1, audit, parse_jsonc
import memory
import managed_config
import runtime
import source_registry


EXPECTED_SKILLS = {
    "anvil-memory", "anvil-spark-performance", "anvil-delta-lake",
    "anvil-databricks", "anvil-data-ingestion", "anvil-communication",
}
EXPECTED_COMMANDS = {"remember", "recall", "distill", "review"}


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
    stale_ids = memory.stale_memory_ids()
    registry_audit = source_registry.audit()
    installation = read_json(data_root / "installation.json")
    migration = installation.get("migration", {})
    if not isinstance(migration, dict):
        migration = {}
    overrides = project_overrides(args.cwd)
    capabilities = runtime.capabilities(requested_major=runtime_major)
    release_check = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().with_name("version_docs.py"))],
        capture_output=True, text=True, check=False,
    )

    missing_skills = EXPECTED_SKILLS - skills
    missing_commands = EXPECTED_COMMANDS - commands
    if missing_skills:
        problems.append(f"Anvil managed skills are missing: {sorted(missing_skills)}")
    if missing_commands:
        problems.append(f"Anvil managed commands are missing: {sorted(missing_commands)}")
    if installation.get("anvil_version"):
        try:
            managed_config.validate_installed(
                args.config_dir, installation.get("anvil_version"), installation.get("anvil_version"),
                installation.get("managed_config_manifest_sha256"),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            problems.append(f"managed configuration integrity check failed: {exc}")
    if runtime_major == 2 and (not plugin_file.is_file() or "anvil_memory_search" not in plugin_file.read_text(encoding="utf-8", errors="replace")):
        problems.append("anvil-core memory search plugin entrypoint is missing")
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
    if release_check.returncode != 0:
        detail = release_check.stderr.strip() or release_check.stdout.strip() or "unknown documentation check failure"
        warnings.append(f"release documentation check failed: {detail}")

    print("Harness")
    print(f"OpenCode {runtime_major} configuration")
    print(f"  runtime config         {'valid' if not config_audit(config_path) else 'invalid'}")
    print(f"  default agent          {config.get('default_agent', 'missing')}")
    print(f"  model pinned           {'yes' if anvil.get('model') or anvil.get('variant') else 'no'}")
    print(f"  user model preference  {'set' if config.get('model') else 'not set'}")
    denied_subagents = rules.get(("task", "*")) == "deny" if runtime_major == 1 else rules.get(("subagent", "*")) == "deny"
    print(f"  subagents denied       {'yes' if denied_subagents else 'no'}")
    print(f"  primary agents         {1 if anvil.get('mode') == 'primary' else 0}")
    print(f"  anvil-core configured  {'yes' if runtime_major == 2 and './plugins/anvil-core' in plugin_entries and plugin_file.is_file() else 'no (runtime fallback)'}")
    print("Capabilities")
    print(f"  /remember              {'YES' if commands >= {'remember'} else 'NO'}")
    print(f"  /recall                {'YES' if commands >= {'recall'} else 'NO'}")
    print(f"  /distill               {'YES' if commands >= {'distill'} else 'NO'}")
    print(f"  memory search backend  {capabilities['memory']['search_backend']}")
    print(f"  native References      {'YES' if capabilities['knowledge']['native_references'] else 'NO'}")
    print("Stats")
    print(f"  native stats           {'YES' if capabilities['stats']['native_stats'] else 'NO'}")
    print(f"  structured stats       {'YES' if capabilities['stats']['structured_native_stats'] else 'NO'}")
    print(f"  global MCP servers     {len(mcp_servers)} configured")
    print(f"  user plugins           {len(unexpected_plugins)} configured")
    print(f"  native compaction      {'enabled' if compaction.get('auto') else 'missing'}")
    print(f"  tool output cap        {output.get('max_lines', 'not available')} lines / {output.get('max_bytes', 'not available')} bytes")
    print("Memory")
    print(f"  memory root            {memory_root}")
    print(f"  valid / invalid        {memory_audit['valid']} / {memory_audit['invalid']}")
    print(f"  stale-source entries   {len(stale_ids)}")
    print(f"  search backend         {capabilities['memory']['search_backend']}")
    print(f"  source registry        {registry_audit['sources']} records, {registry_audit['invalid']} invalid, {registry_audit['drifted']} drifted")
    print("Knowledge")
    if runtime_major == 2:
        print(f"  native References      {'active' if capabilities['knowledge']['native_references'] else 'unavailable'}")
        print(f"  knowledge reference    {knowledge_root or 'missing'} ({'present' if knowledge_root and knowledge_root.is_dir() else 'missing'})")
    else:
        print("  native References      unavailable")
        print("  fallback               direct file paths")
    print("Migration and workspace")
    print(f"  previous Anvil version {installation.get('previous_anvil_version') or migration.get('from_anvil') or 'unknown'}")
    print(f"  migration state        {migration.get('status', 'not recorded')}")
    print("Project overrides")
    print(f"  active                 {', '.join(overrides) if overrides else 'none'}")
    print("Version documentation")
    print(f"  release consistency    {'valid' if release_check.returncode == 0 else 'check failed'}")
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
