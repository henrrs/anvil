#!/usr/bin/env python3
"""Central OpenCode runtime policy and Anvil capability adapter."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "runtime-policy.json"
FEATURES = {
    1: {
        "native_plugins": True,
        "anvil_core_plugin": False,
        "native_references": False,
        "native_memory_search": False,
        "native_stats": True,
        "structured_stats": False,
        "ordered_permissions": False,
        "native_subagent_policy": True,
        "native_tool_output_limits": False,
        "native_compaction_configuration": True,
    },
    2: {
        "native_plugins": True,
        "anvil_core_plugin": True,
        "native_references": True,
        "native_memory_search": True,
        "native_stats": True,
        "structured_stats": True,
        "ordered_permissions": True,
        "native_subagent_policy": True,
        "native_tool_output_limits": True,
        "native_compaction_configuration": True,
    },
}


def policy() -> dict[str, Any]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("runtime policy must be a schema_version 1 JSON object")
    opencode = value.get("opencode")
    if not isinstance(opencode, dict):
        raise ValueError("runtime policy is missing opencode settings")
    supported = opencode.get("supported_majors")
    default = opencode.get("default_major")
    if not isinstance(supported, list) or not supported or any(item not in FEATURES for item in supported):
        raise ValueError("runtime policy supported_majors must be a non-empty list containing supported adapters")
    if default not in supported:
        raise ValueError("runtime policy default_major must be supported")
    for major in supported:
        minimum = opencode.get("minimum_versions", {}).get(str(major), "")
        if not parse_version(minimum) or parse_version(minimum)[0] != major:
            raise ValueError(f"runtime policy has an invalid minimum version for OpenCode {major}")
    return value


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?!\d)", value.strip())
    return tuple(map(int, match.groups())) if match else None


def inspect_binary(binary: str | None = None) -> tuple[str | None, str | None, int | None]:
    if binary:
        selected = binary
    else:
        try:
            from runtime_state import discover
            result = discover()
            runtime = result.get("runtime") or {}
            selected = runtime.get("executable")
        except (ImportError, OSError, ValueError, KeyError):
            selected = shutil.which("opencode")
    if not selected:
        return None, None, None
    try:
        environment = os.environ.copy()
        environment["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
        result = subprocess.run([selected, "--version"], capture_output=True, text=True,
                                timeout=10, check=True, env=environment)
    except (OSError, subprocess.SubprocessError):
        return selected, None, None
    output = (result.stdout or result.stderr).strip().splitlines()
    text = output[0] if output else ""
    parsed = parse_version(text)
    normalized = ".".join(map(str, parsed)) if parsed else None
    return selected, normalized, parsed[0] if parsed else None


def capabilities(binary: str | None = None, requested_major: int | None = None) -> dict[str, Any]:
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    configured = policy()["opencode"]
    path, version, detected = inspect_binary(binary)
    major = requested_major if requested_major is not None else detected
    installed = bool(path and version and detected is not None)
    supported = configured["supported_majors"]
    supported_runtime = major in supported if major is not None else None
    profile = f"opencode-v{major}" if major in FEATURES else "unavailable"
    feature_map = FEATURES.get(major, {})
    unavailable = "unavailable" if major is None else False
    return {
        "schema_version": 1,
        "anvil_version": release,
        "runtime": {
            "binary": path,
            "version": version,
            "major": major,
            "detected_major": detected,
            "installed": installed,
            "profile": profile,
            "policy_profile": f"opencode-v{configured['default_major']}",
            "supported": supported_runtime,
            "minimum_version": configured["minimum_versions"].get(str(major)) if major is not None else None,
        },
        "policy": {
            "supported_majors": supported,
            "default_major": configured["default_major"],
            "allow_automatic_major_upgrade": configured["allow_automatic_major_upgrade"],
        },
        "core": {
            "anvil_agent": major in FEATURES if major is not None else unavailable,
            "slash_commands_installed": installed,
            "model_agnostic": True,
            "remember": True,
            "recall": True,
            "distill": True,
        },
        "memory": {
            "file_memory": True,
            "markdown": True,
            "provenance": True,
            "reconciliation": True,
            "multilingual_aliases": True,
            "source_registry": True,
            "stale_source_detection": True,
            "native_search_tool": feature_map.get("native_memory_search", unavailable),
            "search_backend": "native-tool+file-fallback" if feature_map.get("native_memory_search") else "file-fallback",
        },
        "knowledge": {
            "native_references": feature_map.get("native_references", unavailable),
            "reference_fallback": "direct-file-paths",
        },
        "runtime_features": feature_map,
        "stats": {
            "native_stats": feature_map.get("native_stats", unavailable),
            "structured_native_stats": feature_map.get("structured_stats", unavailable),
            "fallback": "native-text" if feature_map.get("native_stats") and not feature_map.get("structured_stats") else "unavailable-on-current-runtime",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p_caps = sub.add_parser("capabilities")
    p_caps.add_argument("--binary")
    p_caps.add_argument("--major", type=int)
    p_caps.add_argument("--format", choices=("json", "text"), default="json")
    sub.add_parser("policy")
    args = parser.parse_args()
    try:
        if args.action == "policy":
            print(json.dumps(policy(), indent=2))
            return 0
        result = capabilities(args.binary, args.major)
        if args.format == "json":
            print(json.dumps(result, indent=2))
            return 0
        runtime = result["runtime"]
        caps = result["core"]
        memory = result["memory"]
        knowledge = result["knowledge"]
        runtime_major = runtime["major"]
        print("Anvil Capabilities")
        print("────────────────────────────────")
        print(f"Anvil version           {result['anvil_version']}")
        target_profile = not runtime["installed"] and runtime_major is not None
        if runtime["installed"]:
            print(f"OpenCode                {runtime['version']}")
        elif target_profile:
            print(f"OpenCode                {runtime_major}.x target profile (not installed)")
        else:
            print("OpenCode                not installed")
        print(f"Runtime profile         {runtime['profile']}")
        integration = "YES" if runtime["installed"] else ("available after install" if target_profile else "NO (run make reforge)")
        print(f"Command integration     {integration}")
        if not runtime["installed"] and not target_profile:
            print(f"Policy profile          {runtime['policy_profile']} (used for first install)")
            print("Feature flags below describe what this Anvil release provides after reforge; runtime-native features are unknown until OpenCode is installed.")
        print(f"Runtime supported       {'YES' if runtime['supported'] else ('UNKNOWN' if runtime_major is None else 'NO')}")
        print(f"Policy default major    {result['policy']['default_major']}")
        print(f"Supported majors        {', '.join(map(str, result['policy']['supported_majors']))}")
        print("Core")
        for key in ("anvil_agent", "model_agnostic", "remember", "recall", "distill"):
            print(f"  {key:24} {display(caps[key])}")
        print("Memory")
        for key in ("file_memory", "provenance", "reconciliation", "multilingual_aliases", "source_registry", "stale_source_detection", "native_search_tool"):
            print(f"  {key:24} {display(memory[key])}")
        print(f"  {'search_backend':24} {memory['search_backend']}")
        print("Knowledge")
        for key, value in knowledge.items():
            print(f"  {key:24} {display(value)}")
        print("Stats")
        print(f"  {'native stats':24} {display(result['stats']['native_stats'])}")
        print(f"  {'structured stats':24} {display(result['stats']['structured_native_stats'])}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


def display(value: Any) -> str:
    if value is True:
        return "YES"
    if value is False:
        return "NO"
    if value == "unavailable":
        return "UNKNOWN"
    if value == "direct-file-paths":
        return "active"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
