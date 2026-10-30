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
ANVIL_PLUGIN = "./plugins/anvil-core"
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
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WARN  Could not read prior provider configuration from {path}: {exc}", file=sys.stderr)
        return {}


def _move_model(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    model = dict(raw)
    if "id" in model and "modelID" not in model:
        model["modelID"] = model.pop("id")
    if "options" in model:
        settings = model.pop("options")
        if isinstance(settings, dict):
            model["settings"] = {**settings, **(model.get("settings") if isinstance(model.get("settings"), dict) else {})}
    if model.pop("status", None) == "deprecated":
        model["disabled"] = True
    if "tool_call" in model:
        capabilities = model.setdefault("capabilities", {})
        if isinstance(capabilities, dict):
            capabilities.setdefault("tools", bool(model.pop("tool_call")))
    variants = model.get("variants")
    if isinstance(variants, dict):
        model["variants"] = [{"id": name, "settings": value if isinstance(value, dict) else {}} for name, value in variants.items()]
    return model


def _move_provider(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    provider = dict(raw)
    result: dict[str, Any] = {}
    for key in ("name", "env", "npm", "package", "headers", "body", "models", "options", "settings", "compatibility"):
        if key in provider:
            result[key] = provider[key]
    package = result.pop("npm", None)
    if package is not None and "package" not in result:
        if isinstance(package, str) and package.startswith("@ai-sdk/"):
            package = "aisdk:" + package
        result["package"] = package
    settings = result.pop("options", {})
    settings = settings if isinstance(settings, dict) else {}
    settings = {**settings, **(result.get("settings") if isinstance(result.get("settings"), dict) else {})}
    if "api" in provider:
        settings.setdefault("baseURL", provider["api"])
    if "headers" in settings and "headers" not in result:
        result["headers"] = settings.pop("headers")
    if "body" in settings and "body" not in result:
        result["body"] = settings.pop("body")
    compatibility = result.get("compatibility")
    if settings.pop("setCacheKey", None) is True:
        compatibility = dict(compatibility) if isinstance(compatibility, dict) else {}
        compatibility["supportsPromptCacheKey"] = True
        result["compatibility"] = compatibility
    if settings:
        result["settings"] = settings
    if isinstance(result.get("models"), dict):
        result["models"] = {model_id: _move_model(model) for model_id, model in result["models"].items()}
    if "api" in provider and "settings" not in result:
        result["settings"] = {"baseURL": provider["api"]}
    # V1 custom provider adapters sometimes use unstandardized model options.
    # Preserve unknown values under settings so supported provider packages can still consume them.
    known = {"name", "env", "npm", "package", "api", "options", "settings", "headers", "body", "models", "compatibility", "id", "whitelist", "blacklist"}
    extra = {key: value for key, value in provider.items() if key not in known}
    if extra:
        target = result.setdefault("settings", {})
        if isinstance(target, dict):
            target.update(extra)
    return result


def _old_model(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    model = dict(raw)
    if "modelID" in model and "id" not in model:
        model["id"] = model.pop("modelID")
    settings = model.pop("settings", None)
    if isinstance(settings, dict):
        model["options"] = {**settings, **(model.get("options") if isinstance(model.get("options"), dict) else {})}
    variants = model.get("variants")
    if isinstance(variants, list):
        model["variants"] = {
            item["id"]: item.get("settings", {})
            for item in variants if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
    return model


def _old_provider(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    provider = dict(raw)
    result: dict[str, Any] = {}
    for key in ("name", "env", "models", "options", "whitelist", "blacklist"):
        if key in provider:
            result[key] = provider[key]
    package = provider.get("package")
    if isinstance(package, str):
        result["npm"] = package.removeprefix("aisdk:")
    settings = provider.get("settings", {})
    legacy_options = result.get("options", {})
    legacy_options = dict(legacy_options) if isinstance(legacy_options, dict) else {}
    if isinstance(settings, dict):
        settings = dict(settings)
        if "baseURL" in settings:
            result["api"] = settings.pop("baseURL")
        if settings:
            legacy_options = {**settings, **legacy_options}
    for key in ("headers", "body"):
        if key in provider:
            legacy_options.setdefault(key, provider[key])
    if legacy_options:
        result["options"] = legacy_options
    if isinstance(provider.get("models"), dict):
        result["models"] = {model_id: _old_model(model) for model_id, model in provider["models"].items()}
    known = {"name", "env", "headers", "body", "models", "options", "whitelist", "blacklist", "package", "settings"}
    extra = {key: value for key, value in provider.items() if key not in known}
    if extra:
        result.setdefault("options", {}).update(extra)
    return result


def old_providers(config_dir: Path) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for name in ("config.json", "opencode.json", "opencode.jsonc"):
        path = config_dir / name
        if not path.is_file():
            continue
        data = _read_config(path)
        if isinstance(data.get("providers"), dict):
            providers.update(data["providers"])
        if isinstance(data.get("provider"), dict):
            providers.update({key: _move_provider(value) for key, value in data["provider"].items()})
    legacy = config_dir / "config"
    if legacy.is_file():
        try:
            data = tomllib.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data.get("providers"), dict):
                providers.update(data["providers"])
            if isinstance(data.get("provider"), dict):
                providers.update({key: _move_provider(value) for key, value in data["provider"].items()})
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            print(f"WARN  Could not read prior provider configuration from {legacy}: {exc}", file=sys.stderr)
    return providers


def new_providers(config_dir: Path) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for name in ("config.json", "opencode.json", "opencode.jsonc"):
        path = config_dir / name
        if not path.is_file():
            continue
        data = _read_config(path)
        if isinstance(data.get("provider"), dict):
            providers.update(data["provider"])
        if isinstance(data.get("providers"), dict):
            providers.update({key: _old_provider(value) for key, value in data["providers"].items()})
    return providers


def _user_agents(config_dir: Path, major: int) -> dict[str, dict[str, Any]]:
    """Carry user-defined inline agents across config rebuilds.

    Anvil owns its named baseline agents and its primary agent. Additional
    inline agents remain user-owned. Preserve active/disabled state and
    normalize only the generation-specific disable key.
    """
    prior = _read_config(config_dir / "opencode.jsonc")
    key = "agent" if isinstance(prior.get("agent"), dict) else "agents"
    agents = prior.get(key, {})
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
            # Manifests created before inline config ownership was recorded
            # use the shipped baseline as the best available legacy signal.
            reserved = BUILTINS | {"anvil"}
    else:
        reserved = BUILTINS | {"anvil"}
    disabled_key = "disable" if key == "agent" else "disabled"
    alternate_disabled_key = "disabled" if disabled_key == "disable" else "disable"
    target_disabled_key = "disable" if major == 1 else "disabled"
    result: dict[str, dict[str, Any]] = {}
    for name, definition in agents.items():
        if name in reserved or not isinstance(name, str) or not isinstance(definition, dict):
            continue
        copied = copy.deepcopy(definition)
        disabled = copied.get(disabled_key, copied.get(alternate_disabled_key))
        copied.pop("disable", None)
        copied.pop("disabled", None)
        if disabled is not None:
            copied[target_disabled_key] = disabled
        result[name] = copied
    return result


def _config_major(config: dict[str, Any]) -> int:
    if isinstance(config.get("agent"), dict):
        return 1
    if isinstance(config.get("agents"), dict):
        return 2
    return 1


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
    if isinstance(value, str) and value in {ANVIL_PLUGIN, "anvil-core"}:
        return True
    if isinstance(value, dict):
        return any(isinstance(value.get(key), str) and value[key] in {ANVIL_PLUGIN, "anvil-core"}
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


def _migrate_mcp(value: Any, source_major: int, target_major: int) -> Any:
    if not isinstance(value, dict) or source_major == target_major:
        return copy.deepcopy(value)
    if source_major == 1 and target_major == 2:
        if "servers" in value:
            return copy.deepcopy(value)
        return {"servers": copy.deepcopy(value)} if value else {"servers": {}}
    if source_major == 2 and target_major == 1:
        servers = value.get("servers")
        if isinstance(servers, dict):
            return _merge_user_mapping({key: item for key, item in value.items() if key != "servers"}, servers)
    return copy.deepcopy(value)


def _migrate_compaction(value: dict[str, Any], source_major: int, target_major: int) -> dict[str, Any]:
    result = copy.deepcopy(value)
    if source_major == target_major:
        return result
    legacy_keys = {"prune", "tail_turns", "preserve_recent_tokens", "reserved"}
    native_keys = {"keep", "buffer"}
    for key in legacy_keys | native_keys:
        if key not in (native_keys if target_major == 1 else legacy_keys):
            continue
        result.pop(key, None)
    return result


def merge_prior_configuration(data: dict[str, Any], prior_config_dir: Path, major: int) -> None:
    """Merge a user's OpenCode configuration into an Anvil-owned profile.

    Generated Anvil fields stay authoritative. Providers, plugins, MCP,
    references, runtime preferences, custom agents and unknown top-level
    configuration are preserved with format-aware handling.
    """
    previous_path = prior_config_dir / "opencode.jsonc"
    try:
        parsed_previous = parse_jsonc(previous_path.read_text(encoding="utf-8"), str(previous_path))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        if previous_path.exists():
            raise ValueError(f"existing OpenCode configuration cannot be safely merged: {exc}") from exc
        parsed_previous = {}
    if not isinstance(parsed_previous, dict):
        raise ValueError("existing OpenCode configuration root is not an object; it was not replaced")
    providers = old_providers(prior_config_dir) if major == 2 else new_providers(prior_config_dir)
    if providers:
        data["providers" if major == 2 else "provider"] = providers

    previous = parsed_previous
    source_major = _config_major(previous)
    custom_agents = _user_agents(prior_config_dir, major)
    agent_key = "agents" if major == 2 else "agent"
    if custom_agents:
        data[agent_key].update(custom_agents)

    plugin_key = "plugins" if major == 2 else "plugin"
    previous_plugins: Any = None
    for key in (("plugins", "plugin") if source_major == 2 else ("plugin", "plugins")):
        value = previous.get(key)
        if value is not None:
            previous_plugins = _merge_plugin_values(previous_plugins, value)
    if previous_plugins is not None:
        data[plugin_key] = _merge_plugin_values(previous_plugins, data.get(plugin_key))

    if "mcp" in previous:
        previous_mcp = _migrate_mcp(previous["mcp"], source_major, major)
        data["mcp"] = _merge_user_mapping(previous_mcp, data.get("mcp", {}))

    if isinstance(previous.get("references"), dict):
        external_references = {key: value for key, value in previous["references"].items()
                               if key != "anvil-knowledge"}
        merged_references = _merge_user_mapping(external_references, data.get("references", {}))
        if merged_references or "references" in data:
            data["references"] = merged_references

    for key in ("compaction", "tool_output"):
        if isinstance(previous.get(key), dict):
            previous_value = (_migrate_compaction(previous[key], source_major, major)
                              if key == "compaction" else previous[key])
            data[key] = _merge_user_mapping(previous_value, data.get(key, {}))

    if isinstance(previous.get("watcher"), dict):
        old_watcher = previous["watcher"]
        target_watcher = data.get("watcher", {})
        merged_watcher = _merge_user_mapping(old_watcher, target_watcher)
        old_ignore = old_watcher.get("ignore", [])
        target_ignore = target_watcher.get("ignore", []) if isinstance(target_watcher, dict) else []
        if isinstance(old_ignore, list) and isinstance(target_ignore, list):
            merged_watcher["ignore"] = list(dict.fromkeys([*old_ignore, *target_ignore]))
        data["watcher"] = merged_watcher

    # Configuration keys outside the Anvil profile are user/machine-owned.
    # Preserve them verbatim unless a structured merge above owns the boundary.
    for key, value in previous.items():
        if key not in data and key not in STRUCTURED_SHARED_KEYS:
            data[key] = copy.deepcopy(value)

    prior_agents_key = "agent" if isinstance(previous.get("agent"), dict) else "agents"
    prior_agents = previous.get(prior_agents_key, {})
    prior_anvil = prior_agents.get("anvil", {}) if isinstance(prior_agents, dict) else {}
    if prior_agents_key == "agent":
        prior_permission = prior_anvil.get("permission", {}) if isinstance(prior_anvil, dict) else {}
        prior_skill_rules = prior_permission.get("skill", {}) if isinstance(prior_permission, dict) else {}
        custom_skills = {name for name, effect in prior_skill_rules.items()
                         if name != "*" and effect == "allow" and name not in SKILLS
                         and (prior_config_dir / "skills" / name / "SKILL.md").is_file()}
    else:
        prior_rules = prior_anvil.get("permissions", []) if isinstance(prior_anvil, dict) else []
        custom_skills = {str(rule.get("resource")) for rule in prior_rules if isinstance(rule, dict)
                         and rule.get("action") == "skill" and rule.get("effect") == "allow"
                         and rule.get("resource") not in {"*", *SKILLS}
                         and (prior_config_dir / "skills" / str(rule.get("resource")) / "SKILL.md").is_file()}
    if custom_skills:
        if major == 1:
            data["agent"]["anvil"]["permission"]["skill"].update({name: "allow" for name in sorted(custom_skills)})
        else:
            permissions = data["agents"]["anvil"]["permissions"]
            insert_at = next((index for index, rule in enumerate(permissions)
                              if isinstance(rule, dict) and rule.get("action") == "subagent"), len(permissions))
            permissions[insert_at:insert_at] = [
                {"action": "skill", "resource": name, "effect": "allow"}
                for name in sorted(custom_skills)
            ]


def extract_user_configuration(prior_config_dir: Path, target_major: int) -> dict[str, Any]:
    """Return user-owned portions of a shared profile for ownership-aware rollback."""
    path = prior_config_dir / "opencode.jsonc"
    if not path.is_file():
        return {}
    try:
        previous = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing OpenCode configuration cannot be safely merged: {exc}") from exc
    if not isinstance(previous, dict):
        raise ValueError("existing OpenCode configuration root is not an object; it was not replaced")

    agents_key = "agent" if isinstance(previous.get("agent"), dict) else "agents"
    agents = previous.get(agents_key, {})
    if not isinstance(agents, dict) or not isinstance(agents.get("anvil"), dict):
        return copy.deepcopy(previous)

    source_major = _config_major(previous)
    result: dict[str, Any] = {}
    providers = old_providers(prior_config_dir) if target_major == 2 else new_providers(prior_config_dir)
    if providers:
        result["providers" if target_major == 2 else "provider"] = providers
    custom_agents = _user_agents(prior_config_dir, target_major)
    if custom_agents:
        result["agents" if target_major == 2 else "agent"] = custom_agents

    plugin_key = "plugins" if target_major == 2 else "plugin"
    plugin_values: Any = None
    for key in (("plugins", "plugin") if source_major == 2 else ("plugin", "plugins")):
        if key in previous:
            plugin_values = _merge_plugin_values(plugin_values, previous[key])
    if isinstance(plugin_values, list):
        plugin_values = [value for value in plugin_values if not _is_anvil_plugin(value)]
    elif isinstance(plugin_values, dict):
        plugin_values = {key: value for key, value in plugin_values.items() if not _is_anvil_plugin(key)}
    if plugin_values:
        result[plugin_key] = plugin_values

    if "mcp" in previous:
        result["mcp"] = _migrate_mcp(previous["mcp"], source_major, target_major)
    if isinstance(previous.get("references"), dict):
        references = {key: value for key, value in previous["references"].items()
                      if key != "anvil-knowledge"}
        if references:
            result["references"] = references
    for key in ("compaction", "tool_output", "watcher"):
        if key in previous:
            value = previous[key]
            if key == "compaction" and isinstance(value, dict):
                value = _migrate_compaction(value, source_major, target_major)
            result[key] = copy.deepcopy(value)

    anvil_owned_root = {
        "$schema", "default_agent", "agent", "agents", "mcp", "plugin", "plugins",
        "provider", "providers", "references", "compaction", "tool_output", "watcher",
    }
    for key, value in previous.items():
        if key not in anvil_owned_root:
            result[key] = copy.deepcopy(value)
    return result


def build(source: Path, destination: Path, prior_config_dir: Path | None, preserve_cli: bool, major: int) -> None:
    if major not in (1, 2):
        raise ValueError("runtime major must be 1 or 2")
    template = source / ("opencode.jsonc" if major == 2 else "runtimes/opencode-v1.jsonc")
    data = parse_jsonc(template.read_text(encoding="utf-8"), str(template))
    if not isinstance(data, dict):
        raise ValueError(f"Anvil OpenCode {major} config must be a JSON object")
    if prior_config_dir is not None:
        merge_prior_configuration(data, prior_config_dir, major)
    if major == 2:
        knowledge = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "anvil" / "knowledge"
        data["references"]["anvil-knowledge"]["path"] = str(knowledge)
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
    if data.get("mcp") is not None and not isinstance(data.get("mcp"), dict):
        errors.append("V1 MCP configuration must be an object")
    if data.get("plugin") is not None and not isinstance(data.get("plugin"), (list, dict)):
        errors.append("V1 plugin configuration has an unsupported shape")
    compact = data.get("compaction", {})
    if not isinstance(compact, dict) or not isinstance(compact.get("auto"), bool):
        errors.append("V1 compaction settings are invalid")
    return errors


def audit(path: Path, *, source_compatible: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        data = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"config is unreadable or invalid JSONC: {exc}"]
    if not isinstance(data, dict):
        return ["config root must be an object"]
    if any(key in data for key in ("agent", "permission", "plugin")):
        errors.append("legacy V1 config keys remain in the native V2 configuration")
    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        errors.append("agents must be an object")
        agents = {}
    if (not ((BUILTINS | {"anvil"}) <= set(agents))
            if not source_compatible else "anvil" not in agents):
        errors.append("agent definitions do not match the native Anvil set")
    if data.get("default_agent") != "anvil":
        errors.append("default_agent is not anvil")
    if source_compatible:
        for name in BUILTINS & set(agents):
            agent = agents[name]
            if not isinstance(agent, dict) or agent.get("disabled") is not True:
                errors.append(f"Anvil-owned built-in agent {name} is not disabled")
    else:
        for name in BUILTINS:
            if not isinstance(agents.get(name), dict) or agents[name].get("disabled") is not True:
                errors.append(f"built-in agent {name} is not disabled")
    anvil = agents.get("anvil", {})
    if not isinstance(anvil, dict) or anvil.get("mode") != "primary":
        errors.append("anvil primary agent is missing")
        anvil = {}
    if any(key in anvil for key in ("model", "system", "prompt", "variant")):
        errors.append("Anvil pins a model or replaces the native system prompt")
    permissions = anvil.get("permissions", [])
    if not isinstance(permissions, list):
        errors.append("Anvil permissions must be an ordered array")
        permissions = []
    rules = {(rule.get("action"), rule.get("resource")): rule.get("effect") for rule in permissions if isinstance(rule, dict)}
    if rules.get(("*", "*")) != "deny" or rules.get(("subagent", "*")) != "deny":
        errors.append("Anvil does not deny arbitrary actions and subagents")
    if rules.get(("read", "*.env")) != "ask" or rules.get(("read", "*.env.*")) != "ask" or rules.get(("read", "*.env.example")) != "allow":
        errors.append("Anvil does not preserve sensitive .env read prompts")
    if rules.get(("shell", "*")) != "allow" or any(rules.get(("shell", pattern)) != "ask" for pattern in PROTECTED_SHELL):
        errors.append("Anvil does not ask before destructive Git shell commands")
    core_actions = ("read", "glob", "grep", "edit", "shell", "webfetch", "websearch", "question", "anvil_memory_search")
    required_actions = ("read", "edit", "shell") if source_compatible else core_actions
    for action in required_actions:
        if rules.get((action, "*")) != "allow":
            errors.append(f"Anvil core action {action} is not allowed")
    allowed_skills = {resource for (action, resource), effect in rules.items() if action == "skill" and resource != "*" and effect == "allow"}
    skill_root = path.parent / "skills"
    custom_skills = allowed_skills - SKILLS
    custom_skills_present = all((skill_root / name / "SKILL.md").is_file() for name in custom_skills)
    skills_valid = (all(isinstance(name, str) and name for name in allowed_skills) and custom_skills_present
                    if source_compatible else SKILLS <= allowed_skills and custom_skills_present)
    if rules.get(("skill", "*")) != "deny" or not skills_valid:
        errors.append("Anvil skill allowlist does not match a supported Anvil profile")
    mcp = data.get("mcp", {})
    if not isinstance(mcp, dict) or ("servers" in mcp and not isinstance(mcp["servers"], dict)):
        errors.append("native V2 MCP configuration has an invalid shape")
    plugins = data.get("plugins", [])
    if not isinstance(plugins, list) or plugins.count(ANVIL_PLUGIN) != 1:
        errors.append("native V2 plugin configuration must retain exactly one Anvil core plugin")
    compaction = data.get("compaction", {})
    if not isinstance(compaction, dict) or not isinstance(compaction.get("auto"), bool):
        errors.append("native V2 compaction settings are invalid")
    output = data.get("tool_output", {})
    if not source_compatible and (not isinstance(output, dict)
            or not isinstance(output.get("max_lines"), int) or output.get("max_lines") < 1
            or not isinstance(output.get("max_bytes"), int) or output.get("max_bytes") < 1):
        errors.append("bounded tool output is not configured")
    if not source_compatible and (not isinstance(data.get("watcher", {}).get("ignore"), list) or not data["watcher"]["ignore"]):
        errors.append("watcher ignore patterns are missing")
    reference = data.get("references", {}).get("anvil-knowledge", {})
    if not source_compatible and (not isinstance(reference, dict) or not reference.get("path") or reference.get("path") == "__ANVIL_KNOWLEDGE_PATH__"):
        errors.append("native anvil-knowledge reference is missing its absolute path")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p_build = sub.add_parser("build")
    p_build.add_argument("--source", type=Path, required=True)
    p_build.add_argument("--destination", type=Path, required=True)
    p_build.add_argument("--prior-config-dir", type=Path)
    p_build.add_argument("--preserve-cli", action="store_true")
    p_build.add_argument("--major", type=int, choices=(1, 2), default=2)
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("config", type=Path)
    p_v1 = sub.add_parser("audit-v1")
    p_v1.add_argument("config", type=Path)
    p_audit_compatible = sub.add_parser("audit-compatible")
    p_audit_compatible.add_argument("config", type=Path)
    p_v1_compatible = sub.add_parser("audit-v1-compatible")
    p_v1_compatible.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "build":
            build(args.source, args.destination, args.prior_config_dir, args.preserve_cli, args.major)
            return 0
        if args.action in {"audit-v1", "audit-v1-compatible"}:
            errors = _audit_v1(args.config, source_compatible=args.action.endswith("-compatible"))
        else:
            errors = audit(args.config, source_compatible=args.action == "audit-compatible")
        for error in errors:
            print(f"ERROR {error}")
        if not errors:
            if args.action == "audit-v1-compatible":
                print("OK config meets a supported OpenCode 1 Anvil profile")
            elif args.action == "audit-compatible":
                print("OK config meets a supported OpenCode 2 Anvil profile")
            elif args.action == "audit-v1":
                print("OK config meets the current OpenCode 1 Anvil baseline")
            else:
                print("OK config meets the native OpenCode 2 Anvil baseline")
        return 1 if errors else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
