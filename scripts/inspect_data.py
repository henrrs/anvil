#!/usr/bin/env python3
"""Read-only, secret-safe inventory for make inspect."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from configure import parse_jsonc


def config_data(path: Path) -> dict:
    try:
        value = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def files(directory: Path, names: tuple[str, ...]) -> list[str]:
    result = []
    for name in names:
        candidate = directory / name
        if candidate.is_dir():
            result.extend(str(p.relative_to(directory)) for p in sorted(candidate.rglob("*.md")) if p.is_file())
        elif candidate.is_file():
            result.append(name)
    return result


def safe_names(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    args = parser.parse_args()

    config_dir: Path = args.config
    main_configs = [config_dir / name for name in ("config.json", "opencode.json", "opencode.jsonc")]
    parsed = [(path, config_data(path)) for path in main_configs if path.is_file()]
    agents = files(config_dir, ("agents", "agent", "modes", "mode"))
    skills = files(config_dir, ("skills", "skill"))
    plugin_dirs = files(config_dir, ("plugins", "plugin"))
    command_files = files(config_dir, ("commands", "command"))
    mcp_names = sorted({str(name) for _, config in parsed for name in (config.get("mcp", {}) if isinstance(config.get("mcp", {}), dict) else {})})
    config_agent_names = sorted({str(name) for _, config in parsed for name in (config.get("agent", {}) if isinstance(config.get("agent", {}), dict) else {})})
    inline_plugins = sum(len(config.get("plugin", [])) for _, config in parsed if isinstance(config.get("plugin", []), list))
    legacy_agents = files(args.home / ".opencode", ("agents", "agent", "modes", "mode"))
    legacy_skills = files(args.home / ".opencode", ("skills", "skill"))
    legacy_plugins = files(args.home / ".opencode", ("plugins", "plugin"))
    claude_skill_dir = args.home / ".claude/skills"
    claude_skills = [str(path.relative_to(args.home)) for path in sorted(claude_skill_dir.glob("*/SKILL.md"))] if claude_skill_dir.is_dir() else []

    print("Global OpenCode configuration")
    print(f"  config files         {safe_names([p.name for p, _ in parsed])}")
    print(f"  global agents        {safe_names(agents + config_agent_names)}")
    print(f"  global skills        {safe_names(skills)}")
    print(f"  global plugins       {len(plugin_dirs) + inline_plugins} configured/installed")
    print(f"  global MCP servers   {safe_names(mcp_names)}")
    print(f"  global commands      {safe_names(command_files)}")
    rule_paths = [config_dir / "AGENTS.md", args.home / ".claude/CLAUDE.md", args.home / ".config/AGENTS.md"]
    found_rules = [str(path) for path in rule_paths if path.is_file()]
    print(f"  global AGENTS.md     {safe_names(found_rules)}")
    cli = config_dir / "cli.json"
    print(f"  CLI config           {'present' if cli.is_file() else 'none'}")
    auth_candidates = [args.data / "opencode/auth.json", args.data / "opencode/opencode.db", args.state / "opencode/auth.json"]
    auth_state = [str(path) for path in auth_candidates if path.exists()]
    print(f"  auth/session state   {'present (contents not read)' if auth_state else 'not found at known paths'}")
    print(f"  installer directory  {'present' if (args.home / '.opencode').exists() else 'none'}")
    print(f"  legacy root agents   {safe_names(legacy_agents)}")
    print(f"  legacy root skills   {safe_names(legacy_skills)}")
    print(f"  legacy root plugins  {safe_names(legacy_plugins)}")
    print(f"  Claude-compatible skills {safe_names(claude_skills)}")

    project_root = args.cwd.resolve()
    git_root = next((parent for parent in (project_root, *project_root.parents) if (parent / ".git").exists()), None)
    stop = git_root or project_root
    project_configs: list[Path] = []
    project_rules: list[Path] = []
    project_agents: list[str] = []
    project_skills: list[str] = []
    project_plugins: list[str] = []
    project_mcp: set[str] = set()
    cursor = project_root
    while True:
        for name in ("opencode.json", "opencode.jsonc"):
            path = cursor / name
            if path.is_file():
                project_configs.append(path)
                data = config_data(path)
                if isinstance(data.get("mcp", {}), dict):
                    project_mcp.update(str(item) for item in data.get("mcp", {}))
                if isinstance(data.get("agent", {}), dict):
                    project_agents.extend(str(item) for item in data.get("agent", {}))
        for name in ("AGENTS.md", "CLAUDE.md"):
            path = cursor / name
            if path.is_file():
                project_rules.append(path)
        project_opencode = cursor / ".opencode"
        if project_opencode.is_dir():
            project_agents.extend(files(project_opencode, ("agents", "agent", "modes", "mode")))
            project_skills.extend(files(project_opencode, ("skills", "skill")))
            project_plugins.extend(files(project_opencode, ("plugins", "plugin")))
            for name in ("opencode.json", "opencode.jsonc"):
                path = project_opencode / name
                if path.is_file():
                    project_configs.append(path)
                    data = config_data(path)
                    if isinstance(data.get("mcp", {}), dict):
                        project_mcp.update(str(item) for item in data.get("mcp", {}))
                    if isinstance(data.get("agent", {}), dict):
                        project_agents.extend(str(item) for item in data.get("agent", {}))
        project_claude = cursor / ".claude"
        if project_claude.is_dir():
            project_skills.extend(files(project_claude, ("skills",)))
        if cursor == stop or cursor.parent == cursor:
            break
        cursor = cursor.parent

    print("Current workspace (repository-provided state)")
    print(f"  project overrides    {safe_names([str(path) for path in project_configs])}")
    print(f"  project AGENTS.md    {safe_names([str(path) for path in project_rules])}")
    print(f"  project agents       {safe_names(project_agents)}")
    print(f"  project skills       {safe_names(project_skills)}")
    print(f"  project plugins      {safe_names(project_plugins)}")
    print(f"  project MCP          {safe_names(sorted(project_mcp))}")

    current = next((config for _, config in parsed if config), {})
    anvil_managed = current.get("default_agent") == "anvil"
    allowed_skill_names = {
        "anvil-memory", "anvil-spark-performance", "anvil-delta-lake",
        "anvil-databricks", "anvil-data-ingestion",
    }
    active_skill_files = [
        name for name in skills
        if not (anvil_managed and len(Path(name).parts) > 1 and Path(name).parts[1] in allowed_skill_names)
    ]
    legacy_entries = len(legacy_agents) + len(legacy_skills) + len(legacy_plugins) + len(claude_skills)
    configured_plugins = len(plugin_dirs) + inline_plugins
    pollution = len(agents) + len(active_skill_files) + configured_plugins + len(mcp_names) + legacy_entries
    project_context = bool(project_configs or project_rules or project_agents or project_skills or project_plugins or project_mcp)
    if pollution >= 12 or len(mcp_names) >= 3 or len(plugin_dirs) >= 4:
        assessment = "HIGH"
    elif pollution >= 5 or project_context:
        assessment = "MEDIUM"
    else:
        assessment = "LOW"
    print(f"\nPotential context pollution: {assessment}")
    print(f"Anvil global state: {'detected' if anvil_managed else 'not installed'}")
    if project_context:
        print("Assessment includes repository-provided state; it does not imply the global configuration is polluted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
