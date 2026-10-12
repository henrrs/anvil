#!/usr/bin/env python3
"""High-signal, read-only checks for Anvil and project-level overrides."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from configure import parse_jsonc


EXPECTED_SKILLS = {
    "anvil-memory", "anvil-spark-performance", "anvil-delta-lake",
    "anvil-databricks", "anvil-data-ingestion",
}
EXPECTED_COMMANDS = {"remember", "recall"}


def load(path: Path) -> dict:
    try:
        value = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    args = parser.parse_args()
    config_dir: Path = args.config_dir
    config = load(config_dir / "opencode.jsonc")
    global_extra_dirs = [
        name for name in ("agents", "agent", "modes", "mode", "plugins", "plugin")
        if (config_dir / name).exists()
    ]
    alternate_configs = [name for name in ("config.json", "opencode.json") if (config_dir / name).is_file()]
    skill_dir = config_dir / "skills"
    skills = {path.name for path in skill_dir.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()} if skill_dir.is_dir() else set()
    claude_skill_dir = Path.home() / ".claude/skills"
    claude_skills = {path.parent.name for path in claude_skill_dir.glob("*/SKILL.md")} if claude_skill_dir.is_dir() else set()
    legacy_root = Path.home() / ".opencode"
    legacy_capabilities = [name for name in ("agents", "agent", "skills", "skill", "plugins", "plugin", "commands", "command") if (legacy_root / name).exists()]
    commands_dir = config_dir / "commands"
    commands = {path.stem for path in commands_dir.glob("*.md")} if commands_dir.is_dir() else set()
    plugins = config.get("plugin", [])
    plugin_count = len(plugins) if isinstance(plugins, list) else 1
    mcp = config.get("mcp", {})
    mcp_count = len(mcp) if isinstance(mcp, dict) else 1

    problems: list[str] = []
    warnings: list[str] = []
    agents = config.get("agent", {})
    if not isinstance(agents, dict):
        agents = {}
    global_agent_names = set(agents)
    anvil_agent = agents.get("anvil", {})
    if not isinstance(anvil_agent, dict):
        anvil_agent = {}
    anvil_permissions = anvil_agent.get("permission", {})
    if not isinstance(anvil_permissions, dict):
        anvil_permissions = {}
    if skills != EXPECTED_SKILLS:
        problems.append(f"Anvil skills differ from expected set: missing={sorted(EXPECTED_SKILLS - skills)}, extra={sorted(skills - EXPECTED_SKILLS)}")
    if commands != EXPECTED_COMMANDS:
        problems.append(f"commands differ from expected set: {sorted(commands)}")
    if plugin_count:
        problems.append(f"global plugins are configured: {plugin_count}")
    if mcp_count:
        problems.append(f"global MCP servers are configured: {mcp_count}")
    if global_extra_dirs:
        problems.append(f"unexpected global capability directories exist: {', '.join(global_extra_dirs)}")
    if global_agent_names != {"build", "plan", "general", "explore", "anvil"}:
        problems.append(f"global agent definitions differ from baseline: {', '.join(sorted(global_agent_names)) or 'none'}")
    if alternate_configs:
        problems.append(f"additional global OpenCode configs are active: {', '.join(alternate_configs)}")
    if claude_skills:
        warnings.append(f"Claude-compatible global skills may also be discovered: {', '.join(sorted(claude_skills))}")
    if legacy_capabilities:
        warnings.append(f"legacy global OpenCode capability paths remain under ~/.opencode: {', '.join(legacy_capabilities)}")

    project_root = args.cwd.resolve()
    git_root = next((parent for parent in (project_root, *project_root.parents) if (parent / ".git").exists()), None)
    stop = git_root or project_root
    project_configs: list[Path] = []
    project_rules: list[Path] = []
    project_dirs: set[str] = set()
    project_mcp: set[str] = set()
    project_agents: set[str] = set()
    project_skills: set[str] = set()
    project_plugins: set[str] = set()
    cursor = project_root
    while True:
        for name in ("opencode.json", "opencode.jsonc"):
            path = cursor / name
            if path.is_file():
                project_configs.append(path)
                data = load(path)
                section = data.get("mcp", {})
                if isinstance(section, dict):
                    project_mcp.update(str(key) for key in section)
                section = data.get("agent", {})
                if isinstance(section, dict):
                    project_agents.update(str(key) for key in section)
        for name in ("AGENTS.md", "CLAUDE.md"):
            if (cursor / name).is_file():
                project_rules.append(cursor / name)
        for name in (".opencode", ".claude", ".agents"):
            if (cursor / name).exists():
                project_dirs.add(name)
        opencode_dir = cursor / ".opencode"
        if opencode_dir.is_dir():
            for name in ("opencode.json", "opencode.jsonc"):
                path = opencode_dir / name
                if path.is_file():
                    project_configs.append(path)
                    data = load(path)
                    section = data.get("mcp", {})
                    if isinstance(section, dict):
                        project_mcp.update(str(key) for key in section)
                    section = data.get("agent", {})
                    if isinstance(section, dict):
                        project_agents.update(str(key) for key in section)
            project_agents.update(path.stem for path in (opencode_dir / "agents").glob("*.md"))
            for folder in (opencode_dir / "skills", opencode_dir / "skill"):
                project_skills.update(path.parent.name for path in folder.glob("*/SKILL.md"))
            for folder in (opencode_dir / "plugins", opencode_dir / "plugin"):
                project_plugins.update(path.name for path in folder.glob("*"))
        for folder in (cursor / ".claude/skills", cursor / ".agents/skills"):
            project_skills.update(path.parent.name for path in folder.glob("*/SKILL.md"))
        if cursor == stop or cursor.parent == cursor:
            break
        cursor = cursor.parent

    global_anvil_file = config_dir / "AGENTS.md"
    memory_dir = args.data_dir / "anvil/memory"
    memory_entries = sum(1 for path in memory_dir.rglob("*.md") if path.is_file()) if memory_dir.is_dir() else 0
    memory_readable = memory_dir.is_dir() and os.access(memory_dir, os.R_OK | os.X_OK)
    memory_writable = memory_dir.is_dir() and os.access(memory_dir, os.W_OK)

    print("Harness")
    print(f"  default agent       {config.get('default_agent', 'missing')}")
    print("  visible primaries   1 (Anvil baseline; project overrides can add agents)")
    print(f"  global agents       {', '.join(sorted(global_agent_names)) or 'none'}")
    print("  model pinned        no" if not config.get("model") and not anvil_agent.get("model") else "  model pinned        yes")
    print("  subagents           denied" if anvil_permissions.get("task") == "deny" else "  subagents           NOT denied")
    print("Capabilities")
    print(f"  global MCP          {mcp_count}")
    print(f"  Anvil skills        {len(skills)}")
    print(f"  unexpected plugins  {plugin_count}")
    print(f"  extra global skills  {len(claude_skills)}")
    print(f"  legacy root paths    {', '.join(legacy_capabilities) or 'none'}")
    print("Memory")
    print(f"  path                {memory_dir}")
    print(f"  entries             {memory_entries}")
    print(f"  readable            {'yes' if memory_readable else 'no'}")
    print(f"  writable            {'yes' if memory_writable else 'no'}")
    print("Context hygiene")
    compact = config.get("compaction", {})
    output = config.get("tool_output", {})
    watcher = config.get("watcher", {})
    if not isinstance(compact, dict): compact = {}
    if not isinstance(output, dict): output = {}
    if not isinstance(watcher, dict): watcher = {}
    print(f"  tool output cap     {'enabled' if output.get('max_lines') and output.get('max_bytes') else 'missing'}")
    print(f"  watcher ignore      {'enabled' if watcher.get('ignore') else 'missing'}")
    print(f"  native compaction   {'enabled' if compact.get('auto') else 'missing'}")
    print("Project overrides")
    print(f"  AGENTS.md            {'yes' if project_rules else 'no'}")
    print(f"  .opencode/.claude     {'yes' if project_dirs else 'no'}")
    print(f"  project config       {'yes' if project_configs else 'no'}")
    print(f"  MCP                  {'yes' if project_mcp else 'no'}")
    print(f"  agents               {', '.join(sorted(project_agents)) or 'none'}")
    print(f"  skills               {', '.join(sorted(project_skills)) or 'none'}")
    print(f"  plugins              {', '.join(sorted(project_plugins)) or 'none'}")
    print(f"  AGENTS paths         {', '.join(str(path) for path in project_rules) or 'none'}")
    print(f"  config paths         {', '.join(str(path) for path in project_configs) or 'none'}")
    if project_configs or project_rules or project_dirs or project_mcp:
        warnings.append("repository-provided OpenCode/agent configuration is active in the current workspace")
    for variable in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT"):
        if os.environ.get(variable):
            warnings.append(f"{variable} overrides the normal Anvil global configuration")
    managed = Path("/etc/opencode")
    if any((managed / name).is_file() for name in ("opencode.json", "opencode.jsonc")):
        warnings.append("system-managed OpenCode configuration may override Anvil")
    if not global_anvil_file.is_file():
        problems.append("global Anvil AGENTS.md is missing")
    if not memory_readable or not memory_writable:
        problems.append("Anvil memory directory is missing or inaccessible")
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
    raise SystemExit(main())
