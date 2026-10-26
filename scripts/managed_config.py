#!/usr/bin/env python3
"""Inspect, plan, and prepare Anvil-owned configuration transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from configure import BUILTINS, parse_jsonc
from semver import compare, parse as parse_version


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = ".anvil-managed.json"
MANIFEST_REQUIRED_SINCE = (2, 8, 0)


def _load_inventory() -> tuple[dict[str, tuple[int, int, int]], dict[str, tuple[int, int, int]]]:
    path = ROOT / "config" / "managed-inventory.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"managed capability inventory is unavailable: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("managed capability inventory has an unsupported schema")
    result = []
    for category in ("skills", "commands"):
        entries = value.get(category)
        if not isinstance(entries, dict) or any(not isinstance(name, str) or not name for name in entries):
            raise RuntimeError(f"managed capability inventory has an invalid {category} map")
        parsed = {name: parse_version(version) for name, version in entries.items()}
        if any(version is None for version in parsed.values()):
            raise RuntimeError(f"managed capability inventory has an invalid {category} introduction version")
        result.append(parsed)
    return result[0], result[1]


SKILL_INTRODUCED, COMMAND_INTRODUCED = _load_inventory()
COMMUNICATION_VERSION = SKILL_INTRODUCED.get("anvil-communication", (2, 7, 0))
DATABRICKS_PROVIDER_VERSION = (2, 3, 0)
USER_PREFERENCES = {"cli.json", "tui.json", "tui.jsonc"}
BASE_REQUIRED_SCRIPTS = {
    "scripts/memory.py", "scripts/source_registry.py", "scripts/runtime.py", "scripts/runtime_state.py",
}
DATABRICKS_SCRIPTS = {"scripts/databricks.py", "scripts/databricks_finops.py"}


class ManagedConfigError(ValueError):
    pass


def _is_user_preference(relative: str) -> bool:
    return relative in USER_PREFERENCES


def _shipped_package(prefix: str, repository_dir: str) -> set[str]:
    root = ROOT / repository_dir
    return {f"{prefix}/{path.relative_to(root).as_posix()}" for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}


def _shipped_plugin_paths() -> set[str]:
    return _shipped_package("plugins/anvil-core", "config/plugins/anvil-core")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise ManagedConfigError(f"unsafe managed path: {value}")
    return path


def _files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not root.is_dir() or root.is_symlink():
        raise ManagedConfigError("managed config root is missing or is a symbolic link")
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ManagedConfigError(f"symbolic link inside managed config needs manual review: {relative}")
        if path.is_file():
            result[relative] = path
    return result


def _profile_skills(root: Path) -> tuple[int | None, set[str]]:
    path = root / "opencode.jsonc"
    try:
        config = parse_jsonc(path.read_text(encoding="utf-8"), str(path))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ManagedConfigError(f"installed OpenCode profile cannot be read: {exc}") from exc
    if not isinstance(config, dict):
        raise ManagedConfigError("installed OpenCode profile root is not an object")
    v1 = isinstance(config.get("agent"), dict) and "anvil" in config.get("agent", {})
    major = 1 if v1 else 2 if isinstance(config.get("agents"), dict) and "anvil" in config.get("agents", {}) else None
    if major == 1:
        permission = config["agent"]["anvil"].get("permission", {})
        permission = permission if isinstance(permission, dict) else {}
        skills = permission.get("skill", {})
        if not isinstance(skills, dict):
            raise ManagedConfigError("installed OpenCode 1 skill policy is invalid")
        return major, {name for name, effect in skills.items() if name != "*" and effect == "allow"}
    if major == 2:
        permissions = config["agents"]["anvil"].get("permissions", [])
        if not isinstance(permissions, list):
            raise ManagedConfigError("installed OpenCode 2 permission policy is invalid")
        return major, {str(rule.get("resource")) for rule in permissions
                       if isinstance(rule, dict) and rule.get("action") == "skill"
                       and rule.get("effect") == "allow" and rule.get("resource") != "*"}
    raise ManagedConfigError("installed OpenCode config is not a recognized Anvil profile")


def _legacy_owned(root: Path, source_version: str | None, *, allow_missing: bool = False) -> tuple[set[str], list[str]]:
    actual = _files(root)
    version = parse_version(source_version) if source_version else None
    major, skills = _profile_skills(root)
    required = {"AGENTS.md", "opencode.jsonc"}
    if version is None:
        commands = {"remember", "recall", "distill"}
        if "anvil-communication" in skills:
            commands.add("review")
    else:
        commands = {name for name, introduced in COMMAND_INTRODUCED.items() if version >= introduced}
    required.update(f"commands/{name}.md" for name in commands)
    for skill in skills:
        introduced = SKILL_INTRODUCED.get(skill)
        if version is not None and introduced is not None and version < introduced:
            # In an unmanifested old profile this path is user-owned. If the
            # target now ships it, prepare() will report a safe path collision.
            continue
        shipped_skill = ROOT / "config" / "skills" / skill
        if shipped_skill.is_dir():
            # Legacy profiles have no inventory checksum. Require only the
            # stable entrypoint; nested files may have changed across releases.
            required.add(f"skills/{skill}/SKILL.md")
    if version is not None:
        required.update(BASE_REQUIRED_SCRIPTS)
    if version and version >= DATABRICKS_PROVIDER_VERSION:
        required.update(DATABRICKS_SCRIPTS)
    if major == 2:
        required.update(_shipped_plugin_paths())
    if version and version >= COMMUNICATION_VERSION:
        required.update({"scripts/artifacts.py", "skills/anvil-communication/SKILL.md", "commands/review.md"})
    if version is None and "anvil-communication" in skills:
        required.update(path for path in ("scripts/artifacts.py", "skills/anvil-communication/SKILL.md", "commands/review.md")
                        if path in actual)
    missing = sorted(path for path in required if path not in actual)
    if missing and not allow_missing:
        raise ManagedConfigError("source profile is missing files required by its own release: " + ", ".join(missing))
    owned = set(required) & set(actual)
    if version and version >= DATABRICKS_PROVIDER_VERSION:
        owned.update(_shipped_package("scripts/databricks_providers", "scripts/databricks_providers") & actual.keys())
    if version is None:
        known_legacy_scripts = BASE_REQUIRED_SCRIPTS | DATABRICKS_SCRIPTS | {"scripts/artifacts.py"}
        known_legacy_scripts |= _shipped_package("scripts/databricks_providers", "scripts/databricks_providers")
        known_legacy_scripts |= _shipped_package("scripts/communication", "scripts/communication")
        owned.update(known_legacy_scripts & actual.keys())
    if version and version >= COMMUNICATION_VERSION:
        owned.update(_shipped_package("scripts/communication", "scripts/communication") & actual.keys())
    for skill in skills:
        introduced = SKILL_INTRODUCED.get(skill)
        if version is not None and introduced is not None and version < introduced:
            continue
        shipped_skill = ROOT / "config" / "skills" / skill
        if shipped_skill.is_dir():
            owned.update(_shipped_package(f"skills/{skill}", f"config/skills/{skill}") & actual.keys())
    if major == 2:
        owned.update(_shipped_plugin_paths() & actual.keys())
    owned.update(path for path in actual if path in {"AGENTS.md", "opencode.jsonc"}
                 or (path.startswith("commands/") and Path(path).stem in commands))
    return owned, missing


def inspect_source(root: Path, source_version: str | None = None,
                   expected_manifest_sha256: str | None = None, *, recover_managed: bool = False) -> dict[str, Any]:
    actual = _files(root)
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManagedConfigError(f"managed file manifest is unreadable: {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), dict):
            raise ManagedConfigError("managed file manifest has an unsupported shape")
        version = manifest.get("anvil_version")
        if parse_version(version) is None:
            raise ManagedConfigError("managed file manifest has an invalid Anvil version")
        if source_version and parse_version(source_version) and version != source_version:
            raise ManagedConfigError("managed file manifest version does not match installation metadata")
        if expected_manifest_sha256 and digest(manifest_path) != expected_manifest_sha256:
            raise ManagedConfigError("managed file manifest checksum does not match installation metadata")
        config_ownership = manifest.get("config", {})
        if not isinstance(config_ownership, dict):
            raise ManagedConfigError("managed file manifest config ownership is invalid")
        managed_agents = config_ownership.get("managed_agents")
        if (managed_agents is not None
                and (not isinstance(managed_agents, list)
                     or any(not isinstance(name, str) or not name for name in managed_agents)
                     or len(set(managed_agents)) != len(managed_agents))):
            raise ManagedConfigError("managed file manifest agent ownership is invalid")
        owned: set[str] = set()
        owned_digests: dict[str, str | None] = {}
        for relative, expected in manifest["files"].items():
            relative_path = _relative(relative)
            normalized = relative_path.as_posix()
            owned.add(normalized)
            owned_digests[normalized] = expected
            path = root.joinpath(*relative_path.parts)
            if normalized not in actual:
                if recover_managed:
                    continue
                raise ManagedConfigError(f"Anvil-managed file is missing: {normalized}")
            if expected is None and normalized == "opencode.jsonc":
                continue
            if not isinstance(expected, str) or digest(path) != expected:
                if recover_managed:
                    continue
                raise ManagedConfigError(f"Anvil-managed file changed unexpectedly: {normalized}")
    else:
        if expected_manifest_sha256:
            raise ManagedConfigError("Anvil managed file manifest is missing")
        owned, _ = _legacy_owned(root, source_version, allow_missing=recover_managed)
        owned_digests = {path: (None if path == "opencode.jsonc" else digest(root / path))
                         for path in owned}
    owned.update({MANIFEST_NAME} if manifest_path.exists() else set())
    user_files = sorted(path for path in actual if path not in owned and not _is_user_preference(path))
    owned_existing = owned.intersection(actual)
    owned_digests = {path: digest_value for path, digest_value in owned_digests.items() if path in owned_existing}
    return {"owned_files": sorted(owned_existing - {MANIFEST_NAME}), "owned_digests": owned_digests,
            "user_files": user_files,
            "manifest_present": manifest_path.is_file(),
            "manifest_version": (manifest.get("anvil_version") if manifest_path.is_file() else None)}


def _target_manifest(root: Path, target_version: str, *, excluded: set[str] | None = None) -> dict[str, Any]:
    if parse_version(target_version) is None:
        raise ManagedConfigError("target Anvil release is not a numeric semantic version")
    files = _files(root)
    inventory: dict[str, str | None] = {}
    excluded = excluded or set()
    for relative, path in sorted(files.items()):
        if relative == MANIFEST_NAME or relative in excluded or _is_user_preference(relative):
            continue
        inventory[relative] = None if relative == "opencode.jsonc" else digest(path)
    config = parse_jsonc((root / "opencode.jsonc").read_text(encoding="utf-8"), str(root / "opencode.jsonc"))
    if not isinstance(config, dict):
        raise ManagedConfigError("target OpenCode profile root is not an object")
    agents_key = "agent" if isinstance(config.get("agent"), dict) else "agents"
    agents = config.get(agents_key, {})
    if not isinstance(agents, dict):
        raise ManagedConfigError("target OpenCode profile has an invalid agent map")
    managed_agents = sorted((set(agents) & (BUILTINS | {"anvil"})))
    return {"schema_version": 1, "anvil_version": target_version, "files": inventory,
            "config": {"managed_agents": managed_agents}}


def _write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    destination = root / MANIFEST_NAME
    fd, temporary = tempfile.mkstemp(prefix=".anvil-managed.", dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def prepare(source: Path | None, target: Path, source_version: str | None,
            target_version: str, *, recover_managed: bool = False,
            source_manifest_sha256: str | None = None) -> dict[str, Any]:
    target_owned = set(_files(target)) - {MANIFEST_NAME} - {
        path for path in _files(target) if _is_user_preference(path)
    }
    source_state: dict[str, Any] = {"owned_files": [], "user_files": [], "manifest_present": False}
    if source is not None and source.is_dir():
        source_state = inspect_source(source, source_version, source_manifest_sha256,
                                      recover_managed=recover_managed)
        source_owned = set(source_state["owned_files"])
        conflicts = sorted(set(source_state["user_files"]) & target_owned)
        if conflicts:
            raise ManagedConfigError("user-owned files conflict with new Anvil paths; move them before retrying: "
                                     + ", ".join(conflicts))
        for relative in source_state["user_files"]:
            source_path = source / relative
            target_path = target / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                raise ManagedConfigError(f"refusing to overwrite user-owned path: {relative}")
            shutil.copy2(source_path, target_path)
    manifest = _target_manifest(target, target_version, excluded=set(source_state["user_files"]))
    _write_manifest(target, manifest)
    return plan(source_state, manifest, source_version, target_version)


def plan(source_state: dict[str, Any], target_manifest: dict[str, Any],
         source_version: str | None, target_version: str) -> dict[str, Any]:
    source_files = set(source_state.get("owned_files", []))
    target_files = set(target_manifest["files"])
    added = sorted(target_files - source_files)
    removed = sorted(source_files - target_files)
    source_digests = source_state.get("owned_digests", {})
    target_digests = target_manifest["files"]
    updated = sorted(path for path in source_files & target_files
                     if source_digests.get(path) != target_digests.get(path)
                     or (path == "opencode.jsonc" and source_version != target_version))
    unchanged = sorted((source_files & target_files) - set(updated))
    user_files = sorted(source_state.get("user_files", []))
    return {"schema_version": 1, "source_version": source_version or "legacy/unrecorded",
            "target_version": target_version,
            "changes": {"added": added, "updated": updated, "removed": removed,
                        "unchanged": unchanged, "preserved_user_files": user_files},
            "runtime_action": "preserve-compatible-runtime"}


def validate_installed(root: Path, installed_version: str | None, target_version: str,
                       expected_manifest_sha256: str | None = None) -> dict[str, Any]:
    parsed_version = parse_version(installed_version) if installed_version else None
    if parsed_version and parsed_version >= MANIFEST_REQUIRED_SINCE:
        if not (root / MANIFEST_NAME).is_file():
            raise ManagedConfigError("installation release requires a managed file manifest, but it is missing")
    return inspect_source(root, installed_version if parsed_version else None, expected_manifest_sha256)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--source", type=Path)
    p_prepare.add_argument("--target", type=Path, required=True)
    p_prepare.add_argument("--source-version", default="")
    p_prepare.add_argument("--target-version", required=True)
    p_prepare.add_argument("--recover-managed", action="store_true")
    p_prepare.add_argument("--source-manifest-sha256", default="")
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--source", type=Path)
    p_plan.add_argument("--target", type=Path, required=True)
    p_plan.add_argument("--source-version", default="")
    p_plan.add_argument("--target-version", required=True)
    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("--root", type=Path, required=True)
    p_inspect.add_argument("--installed-version", default="")
    p_inspect.add_argument("--target-version", required=True)
    p_inspect.add_argument("--manifest-sha256", default="")
    p_inspect.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.source, args.target, args.source_version or None, args.target_version,
                             recover_managed=args.recover_managed,
                             source_manifest_sha256=args.source_manifest_sha256 or None)
        elif args.action == "plan":
            source_state = inspect_source(args.source, args.source_version or None) if args.source else {
                "owned_files": [], "user_files": []}
            manifest = json.loads((args.target / MANIFEST_NAME).read_text(encoding="utf-8"))
            result = plan(source_state, manifest, args.source_version or None, args.target_version)
        else:
            result = validate_installed(args.root, args.installed_version or None, args.target_version,
                                        args.manifest_sha256 or None)
        if args.action == "prepare":
            return 0
        if args.action == "inspect" and args.format == "text":
            print(f"Managed manifest      {'present' if result['manifest_present'] else 'legacy/unmanifested'}")
            print(f"Anvil-owned files     {len(result['owned_files'])}")
            print(f"User-owned extra files {len(result['user_files'])}")
            for path in result["user_files"]:
                print(f"  preserve             {path}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR MANAGED_CONFIG: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
