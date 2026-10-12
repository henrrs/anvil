#!/usr/bin/env python3
"""Small standard-library config helper for Anvil's OpenCode lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


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

    # Remove commas immediately before a closing bracket, outside strings.
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


def old_provider(config_dir: Path) -> dict[str, Any]:
    provider: dict[str, Any] = {}
    for name in ("config.json", "opencode.json", "opencode.jsonc"):
        path = config_dir / name
        if not path.is_file():
            continue
        try:
            data = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"WARN  Could not read prior provider configuration from {path}: {exc}", file=sys.stderr)
            continue
        if isinstance(data, dict) and isinstance(data.get("provider"), dict):
            provider.update(data["provider"])

    legacy = config_dir / "config"
    if legacy.is_file():
        try:
            data = tomllib.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data.get("provider"), dict):
                provider.update(data["provider"])
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            print(f"WARN  Could not read prior provider configuration from {legacy}: {exc}", file=sys.stderr)
    return provider


def build(source: Path, destination: Path, prior_config_dir: Path | None) -> None:
    data = parse_jsonc(source.read_text(encoding="utf-8"), str(source))
    if not isinstance(data, dict):
        raise ValueError("Anvil OpenCode config must be a JSON object")
    if prior_config_dir is not None:
        provider = old_provider(prior_config_dir)
        if provider:
            data["provider"] = provider
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)


def audit(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"config is unreadable or invalid JSONC: {exc}"]
    if not isinstance(data, dict):
        return ["config root must be an object"]
    if "model" in data or "small_model" in data:
        errors.append("global OpenCode model defaults are pinned")
    agents = data.get("agent", {})
    if not isinstance(agents, dict):
        errors.append("agent must be an object")
        agents = {}
    unexpected_agents = set(agents) - {"build", "plan", "general", "explore", "anvil"}
    if unexpected_agents:
        errors.append(f"unexpected global agent definitions: {', '.join(sorted(unexpected_agents))}")
    if data.get("default_agent") != "anvil":
        errors.append("default_agent is not anvil")
    for name in ("build", "plan", "general", "explore"):
        if not isinstance(agents.get(name), dict) or agents[name].get("disable") is not True:
            errors.append(f"built-in agent {name} is not disabled")
    anvil = agents.get("anvil", {})
    if not isinstance(anvil, dict) or anvil.get("mode") != "primary":
        errors.append("anvil primary agent is missing")
        anvil = {}
    for key in ("model", "variant", "prompt"):
        if key in anvil:
            errors.append(f"anvil unexpectedly pins {key} or replaces the provider prompt")
    permission = anvil.get("permission", {})
    if not isinstance(permission, dict):
        errors.append("anvil permission must be an object")
        permission = {}
    if permission.get("*") != "deny" or permission.get("task") != "deny":
        errors.append("anvil does not default-deny tools and subagents")
    expected_permission_keys = {
        "*", "read", "glob", "grep", "list", "edit", "bash", "webfetch", "websearch",
        "lsp", "todowrite", "question", "doom_loop", "task", "skill",
    }
    unexpected_permission_keys = set(permission) - expected_permission_keys
    if unexpected_permission_keys:
        errors.append(f"unexpected Anvil tool permissions: {', '.join(sorted(unexpected_permission_keys))}")
    read_rules = permission.get("read", {})
    if not isinstance(read_rules, dict) or read_rules.get("*") != "allow" or read_rules.get("*.env") != "ask" or read_rules.get("*.env.*") != "ask" or read_rules.get("*.env.example") != "allow":
        errors.append("Anvil does not preserve OpenCode's sensitive .env read prompts")
    bash_rules = permission.get("bash", {})
    protected_commands = (
        "git reset --hard*", "git clean -f*", "git checkout -- *", "git restore --worktree*",
        "git push --force*", "git push -f*", "git branch -D*", "git stash drop*", "git stash clear*",
    )
    if not isinstance(bash_rules, dict) or bash_rules.get("*") != "allow" or any(bash_rules.get(pattern) != "ask" for pattern in protected_commands):
        errors.append("Anvil does not ask before destructive Git commands")
    for tool in ("glob", "grep", "list", "edit", "webfetch", "websearch", "lsp", "todowrite", "question"):
        if permission.get(tool) != "allow":
            errors.append(f"Anvil core tool {tool} is not allowed")
    if permission.get("doom_loop") != "ask":
        errors.append("Anvil does not ask before continuing a detected tool loop")
    skill_rules = permission.get("skill", {})
    if not isinstance(skill_rules, dict) or skill_rules.get("*") != "deny":
        errors.append("anvil does not deny arbitrary skills")
    allowed_skills = {
        key for key, value in skill_rules.items() if key != "*" and value == "allow"
    } if isinstance(skill_rules, dict) else set()
    expected = {
        "anvil-memory", "anvil-spark-performance", "anvil-delta-lake",
        "anvil-databricks", "anvil-data-ingestion",
    }
    if allowed_skills != expected:
        errors.append("Anvil skill allowlist does not match the five shipped skills")
    mcp = data.get("mcp", {})
    if not isinstance(mcp, dict) or mcp:
        errors.append("managed global MCP config is not empty")
    plugins = data.get("plugin", [])
    if not isinstance(plugins, list) or plugins:
        errors.append("managed global plugins are configured")
    compact = data.get("compaction", {})
    if not isinstance(compact, dict) or compact.get("auto") is not True:
        errors.append("native automatic compaction is not enabled")
    output = data.get("tool_output", {})
    if not isinstance(output, dict) or not output.get("max_lines") or not output.get("max_bytes"):
        errors.append("bounded tool output is not configured")
    watcher = data.get("watcher", {})
    if not isinstance(watcher, dict) or not watcher.get("ignore"):
        errors.append("watcher ignore patterns are missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p_build = sub.add_parser("build")
    p_build.add_argument("--source", type=Path, required=True)
    p_build.add_argument("--destination", type=Path, required=True)
    p_build.add_argument("--prior-config-dir", type=Path)
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "build":
            build(args.source, args.destination, args.prior_config_dir)
            return 0
        errors = audit(args.config)
        for error in errors:
            print(f"ERROR {error}")
        if not errors:
            print("OK config meets the Anvil baseline")
        return 1 if errors else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
