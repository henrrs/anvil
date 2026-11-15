#!/usr/bin/env python3
"""Render and audit Anvil's OpenCode runtime configurations."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


BASELINE_SKILLS = {
    "anvil-memory", "anvil-spark-performance", "anvil-delta-lake",
    "anvil-databricks", "anvil-data-ingestion",
}
SKILLS = BASELINE_SKILLS | {"anvil-communication", "anvil-engineering", "anvil-system-design"}
COMMANDS = {"remember", "recall", "distill", "review"}
BUILTINS = {"build", "plan", "general", "explore"}
ANVIL_PLUGIN = "./plugins/anvil-core-v1.ts"
STRUCTURED_SHARED_KEYS = {
    "provider", "providers", "plugin", "plugins", "mcp", "references",
    "compaction", "tool_output", "watcher", "agent", "agents",
}
PROTECTED_SHELL = (
    "git reset --hard*", "git clean -f*", "git checkout -- *", "git restore --worktree*",
    "git push --force*", "git push -f*", "git branch -D*", "git stash drop*", "git stash clear*",
)


def parse_jsonc(text: str, source: str = "<input>") -> Any:
    """Parse JSONC comments and trailing commas without changing string values."""
    out: list[str] = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            end = text.find("*/", i)
            if end < 0:
                raise ValueError(f"{source}: unterminated block comment")
            i = end + 2
            continue
        out.append(ch)
        i += 1
    cleaned = "".join(out)
    out.clear()
    i = 0
    in_string = False
    escaped = False
    while i < len(cleaned):
        ch = cleaned[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < len(cleaned) and cleaned[j].isspace():
                j += 1
            if j < len(cleaned) and cleaned[j] in "]}":
                i += 1
                continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        if not path.is_symlink():
            return {}
        print(f"WARN  Could not read prior provider configuration from {path}: broken symbolic link", file=sys.stderr)
        return {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WARN  Could not read prior provider configuration from {path}: {exc}", file=sys.stderr)
        return {}


def new_providers(config_dir: Path) -> dict[str, Any]:
    """Preserve providers already expressed in the supported OpenCode 1 format."""
    providers: dict[str, Any] = {}
    for name in ("config.json", "opencode.json", "opencode.jsonc"):
        data = _read_config(config_dir / name)
        if isinstance(data.get("provider"), dict):
            providers.update(data["provider"])
    legacy = config_dir / "config"
    if legacy.is_file():
        try:
            data = tomllib.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data.get("provider"), dict):
                providers.update(data["provider"])
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            print(f"WARN  Could not read prior provider configuration from {legacy}: {exc}", file=sys.stderr)
    return providers


def _user_agents(config_dir: Path) -> dict[str, dict[str, Any]]:
    """Carry inline user agents while leaving Anvil's named agents authoritative."""
    prior = _read_config(config_dir / "opencode.jsonc")
    agents = prior.get("agent", {})
    if not isinstance(agents, dict):
        return {}
    manifest_path = config_dir / ".anvil-managed.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"managed agent ownership manifest cannot be read: {exc}") from exc
        config_ownership = manifest.get("config", {}) if isinstance(manifest, dict) else None
        if not isinstance(config_ownership, dict):
            raise ValueError("managed agent ownership manifest has an invalid config section")
        recorded_agents = config_ownership.get("managed_agents")
        if recorded_agents is not None:
            if not isinstance(recorded_agents, list) or any(not isinstance(name, str) or not name for name in recorded_agents):
                raise ValueError("managed agent ownership manifest has an invalid managed_agents list")
            reserved = set(recorded_agents) | {"anvil"}
        else:
            reserved = BUILTINS | {"anvil"}
    else:
        reserved = BUILTINS | {"anvil"}
    return {name: copy.deepcopy(definition) for name, definition in agents.items()
            if name not in reserved and isinstance(name, str) and isinstance(definition, dict)}

def _merge_user_mapping(previous: Any, target: Any) -> Any:
    """Merge shared config with the previous user value winning conflicts."""
    if not isinstance(previous, dict) or not isinstance(target, dict):
        return copy.deepcopy(previous if previous is not None else target)
    result = copy.deepcopy(target)
    for key, value in previous.items():
        if key in result and isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = _merge_user_mapping(value, result[key])
        else:
            result[key] = copy.deepcopy(value)
    return result


def _is_anvil_plugin(value: Any) -> bool:
    if isinstance(value, str):
        return value in {ANVIL_PLUGIN, "./plugins/anvil-core", "anvil-core"}
    if isinstance(value, dict):
        return any(isinstance(value.get(key), str)
                   and value[key] in {ANVIL_PLUGIN, "./plugins/anvil-core", "anvil-core"}
                   for key in ("id", "name", "path", "plugin"))
    return False


def _merge_plugin_values(previous: Any, target: Any) -> Any:
    if previous is None:
        return copy.deepcopy(target)
    if target is None:
        target = [] if isinstance(previous, list) else {}
    if isinstance(previous, list) and isinstance(target, list):
        result = []
        for value in [*(item for item in previous if not _is_anvil_plugin(item)), *target]:
            if value not in result:
                result.append(copy.deepcopy(value))
        return result
    if isinstance(previous, dict) and isinstance(target, dict):
        user_values = {key: value for key, value in previous.items() if not _is_anvil_plugin(key)}
        return _merge_user_mapping(user_values, target)
    if previous == target:
        return copy.deepcopy(target)
    raise ValueError("existing OpenCode plugin configuration has an incompatible shape; it was not replaced")

def merge_prior_configuration(data: dict[str, Any], prior_config_dir: Path) -> None:
    """Merge user-owned OpenCode 1 settings while keeping Anvil fields authoritative."""
    previous_path = prior_config_dir / "opencode.jsonc"
    try:
        previous = parse_jsonc(previous_path.read_text(encoding="utf-8"), str(previous_path))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        if previous_path.exists():
            raise ValueError(f"existing OpenCode configuration cannot be safely merged: {exc}") from exc
        previous = {}
    if not isinstance(previous, dict):
        raise ValueError("existing OpenCode configuration root is not an object; it was not replaced")

    providers = new_providers(prior_config_dir)
    if providers:
        data["provider"] = providers
    data["agent"].update(_user_agents(prior_config_dir))
    if "plugin" in previous:
        data["plugin"] = _merge_plugin_values(previous["plugin"], data.get("plugin"))
    if isinstance(previous.get("mcp"), dict):
        data["mcp"] = _merge_user_mapping(previous["mcp"], data.get("mcp", {}))
    if isinstance(previous.get("references"), dict):
        external = {key: value for key, value in previous["references"].items() if key != "anvil-knowledge"}
        data["references"] = _merge_user_mapping(external, data.get("references", {}))
    for key in ("compaction", "tool_output", "watcher"):
        if isinstance(previous.get(key), dict):
            data[key] = _merge_user_mapping(previous[key], data.get(key, {}))
    for key, value in previous.items():
        if key not in data and key not in STRUCTURED_SHARED_KEYS:
            data[key] = copy.deepcopy(value)

    prior_agents = previous.get("agent", {})
    prior_anvil = prior_agents.get("anvil", {}) if isinstance(prior_agents, dict) else {}
    permission = prior_anvil.get("permission", {}) if isinstance(prior_anvil, dict) else {}
    skill_rules = permission.get("skill", {}) if isinstance(permission, dict) else {}
    custom_skills = {name for name, effect in skill_rules.items()
                     if name != "*" and effect == "allow" and name not in SKILLS
                     and (prior_config_dir / "skills" / name / "SKILL.md").is_file()}
    data["agent"]["anvil"]["permission"]["skill"].update({name: "allow" for name in sorted(custom_skills)})

def extract_user_configuration(prior_config_dir: Path) -> dict[str, Any]:
    """Return user-owned portions for ownership-aware rollback merging."""
    path = prior_config_dir / "opencode.jsonc"
    if not path.is_file():
        return {}
    try:
        previous = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing OpenCode configuration cannot be safely merged: {exc}") from exc
    if not isinstance(previous, dict):
        raise ValueError("existing OpenCode configuration root is not an object; it was not replaced")
    agents = previous.get("agent", {})
    if not isinstance(agents, dict) or not isinstance(agents.get("anvil"), dict):
        return copy.deepcopy(previous)

    result: dict[str, Any] = {}
    providers = new_providers(prior_config_dir)
    if providers:
        result["provider"] = providers
    custom_agents = _user_agents(prior_config_dir)
    if custom_agents:
        result["agent"] = custom_agents
    plugins = previous.get("plugin")
    if isinstance(plugins, list):
        plugins = [value for value in plugins if not _is_anvil_plugin(value)]
    elif isinstance(plugins, dict):
        plugins = {key: value for key, value in plugins.items() if not _is_anvil_plugin(key)}
    if plugins:
        result["plugin"] = copy.deepcopy(plugins)
    if isinstance(previous.get("mcp"), dict):
        result["mcp"] = copy.deepcopy(previous["mcp"])
    if isinstance(previous.get("references"), dict):
        references = {key: value for key, value in previous["references"].items() if key != "anvil-knowledge"}
        if references:
            result["references"] = references
    for key in ("compaction", "tool_output", "watcher"):
        if key in previous:
            result[key] = copy.deepcopy(previous[key])
    anvil_owned = {"$schema", "default_agent", "agent", "agents", "mcp", "plugin", "plugins",
                   "provider", "providers", "references", "compaction", "tool_output", "watcher"}
    for key, value in previous.items():
        if key not in anvil_owned:
            result[key] = copy.deepcopy(value)
    return result

def build(source: Path, destination: Path, prior_config_dir: Path | None, preserve_cli: bool) -> None:
    template = source / "runtimes/opencode-v1.jsonc"
    data = parse_jsonc(template.read_text(encoding="utf-8"), str(template))
    if not isinstance(data, dict):
        raise ValueError("Anvil OpenCode 1 config must be a JSON object")
    if prior_config_dir is not None:
        merge_prior_configuration(data, prior_config_dir)
    destination.mkdir(parents=True, exist_ok=True)
    if preserve_cli and prior_config_dir is not None:
        for name in ("cli.json", "tui.json", "tui.jsonc"):
            path = prior_config_dir / name
            if path.is_file():
                (destination / name).write_bytes(path.read_bytes())
                os.chmod(destination / name, 0o600)
    output = destination / "opencode.jsonc"
    temporary = output.with_name(output.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)


def _audit_v1(path: Path, *, source_compatible: bool = False) -> list[str]:
    """Audit a current V1 profile or its security-critical source compatibility."""
    errors: list[str] = []
    try:
        data = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"config is unreadable or invalid JSONC: {exc}"]
    if not isinstance(data, dict):
        return ["config root must be an object"]
    agents = data.get("agent", {})
    if not isinstance(agents, dict):
        errors.append("agent must be an object")
        agents = {}
    if (not ({"build", "plan", "general", "explore", "anvil"} <= set(agents))
            if not source_compatible else "anvil" not in agents):
        errors.append("unexpected global agent definitions")
    if data.get("default_agent") != "anvil":
        errors.append("default_agent is not anvil")
    if source_compatible:
        for name in BUILTINS & set(agents):
            agent = agents[name]
            if not isinstance(agent, dict) or agent.get("disable") is not True:
                errors.append(f"Anvil-owned built-in agent {name} is not disabled")
    else:
        for name in BUILTINS:
            if not isinstance(agents.get(name), dict) or agents[name].get("disable") is not True:
                errors.append(f"built-in agent {name} is not disabled")
    anvil = agents.get("anvil", {})
    if not isinstance(anvil, dict) or anvil.get("mode") != "primary":
        errors.append("anvil primary agent is missing")
        anvil = {}
    if any(key in anvil for key in ("model", "variant", "prompt")):
        errors.append("anvil unexpectedly pins a model or replaces the provider prompt")
    permission = anvil.get("permission", {})
    if not isinstance(permission, dict) or permission.get("*") != "deny" or permission.get("task") != "deny":
        errors.append("V1 permissions do not deny arbitrary tools and subagents")
        permission = {}
    read = permission.get("read", {})
    if not isinstance(read, dict) or read.get("*") != "allow" or read.get("*.env") != "ask" or read.get("*.env.*") != "ask" or read.get("*.env.example") != "allow":
        errors.append("V1 sensitive .env read prompts are missing")
    shell = permission.get("bash", {})
    if not isinstance(shell, dict) or shell.get("*") != "allow" or any(shell.get(pattern) != "ask" for pattern in PROTECTED_SHELL):
        errors.append("V1 destructive Git shell prompts are missing")
    skill = permission.get("skill", {})
    allowed_skills = {k for k, v in skill.items() if k != "*" and v == "allow"} if isinstance(skill, dict) else set()
    skill_root = path.parent / "skills"
    custom_skills = allowed_skills - SKILLS
    custom_skills_present = all((skill_root / name / "SKILL.md").is_file() for name in custom_skills)
    skills_valid = (all(isinstance(name, str) and name for name in allowed_skills) and custom_skills_present
                    if source_compatible else SKILLS <= allowed_skills and custom_skills_present)
    if not isinstance(skill, dict) or skill.get("*") != "deny" or not skills_valid:
        errors.append("V1 skill allowlist does not match a supported Anvil profile")
    expected_tool_permissions = {"anvil_memory_search": "allow"}
    if not source_compatible and any(permission.get(name) != effect
                                     for name, effect in expected_tool_permissions.items()):
        errors.append("V1 Anvil plugin tool permissions are incomplete")
    if data.get("mcp") is not None and not isinstance(data.get("mcp"), dict):
        errors.append("V1 MCP configuration must be an object")
    if data.get("plugin") is not None and not isinstance(data.get("plugin"), (list, dict)):
        errors.append("V1 plugin configuration has an unsupported shape")
    compact = data.get("compaction", {})
    if not isinstance(compact, dict) or not isinstance(compact.get("auto"), bool):
        errors.append("V1 compaction settings are invalid")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p_build = sub.add_parser("build")
    p_build.add_argument("--source", type=Path, required=True)
    p_build.add_argument("--destination", type=Path, required=True)
    p_build.add_argument("--prior-config-dir", type=Path)
    p_build.add_argument("--preserve-cli", action="store_true")
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("config", type=Path)
    p_compatible = sub.add_parser("audit-compatible")
    p_compatible.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "build":
            build(args.source, args.destination, args.prior_config_dir, args.preserve_cli)
            return 0
        errors = _audit_v1(args.config, source_compatible=args.action == "audit-compatible")
        for error in errors:
            print(f"ERROR {error}")
        if not errors:
            message = ("OK config meets a supported OpenCode 1 Anvil profile"
                       if args.action == "audit-compatible"
                       else "OK config meets the current OpenCode 1 Anvil baseline")
            print(message)
        return 1 if errors else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
