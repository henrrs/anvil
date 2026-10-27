#!/usr/bin/env python3
"""Inspect, plan, and prepare Anvil-owned configuration transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
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
ENGINEERING_VERSION = SKILL_INTRODUCED.get("anvil-engineering", (2, 9, 0))
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


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise ManagedConfigError(f"unsafe managed path: {value}")
    return path


def _scan(root: Path) -> tuple[dict[str, Path], set[str], set[str]]:
    """Inventory leaf nodes without following symlinks anywhere below root."""
    result: dict[str, Path] = {}
    if not root.is_dir() or root.is_symlink():
        raise ManagedConfigError("managed config root is missing or is a symbolic link")
    symlinks: set[str] = set()
    other: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scanner:
                entries = list(scanner)
        except OSError as exc:
            raise ManagedConfigError(f"managed config directory cannot be inspected: {directory}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                if entry.is_symlink():
                    symlinks.add(relative)
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    result[relative] = path
                else:
                    other.add(relative)
            except OSError as exc:
                raise ManagedConfigError(f"managed config entry cannot be inspected: {relative}") from exc
    return result, symlinks, other


def _symlink_ancestor(relative: str, symlinks: set[str]) -> str | None:
    parts = PurePosixPath(relative).parts
    for end in range(1, len(parts) + 1):
        candidate = PurePosixPath(*parts[:end]).as_posix()
        if candidate in symlinks:
            return candidate
    return None


def _check_managed_path(relative: str, symlinks: set[str], *, recover_managed: bool = False) -> str | None:
    link = _symlink_ancestor(relative, symlinks)
    if link is None:
        return None
    if not recover_managed:
        raise ManagedConfigError(f"Anvil-managed path is a symbolic link: {relative} (via {link})")
    return link


def _open_regular(root: Path, relative: str) -> int:
    """Open a root-relative regular file without following any symlink component."""
    parts = _relative(relative).parts
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(root, directory_flags)
    try:
        for component in parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        descriptor = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ManagedConfigError(f"managed path is not a regular file: {relative}")
        return descriptor
    finally:
        os.close(directory_fd)


def _read_regular(root: Path, relative: str) -> bytes:
    with os.fdopen(_open_regular(root, relative), "rb") as stream:
        return stream.read()


def _digest_regular(root: Path, relative: str) -> str:
    result = hashlib.sha256()
    with os.fdopen(_open_regular(root, relative), "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _profile_skills(root: Path) -> tuple[int | None, set[str]]:
    path = "opencode.jsonc"
    try:
        config = parse_jsonc(_read_regular(root, path).decode("utf-8"), str(root / path))
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
    actual, symlinks, other = _scan(root)
    profile_link = _check_managed_path("opencode.jsonc", symlinks, recover_managed=allow_missing)
    if profile_link:
        raise ManagedConfigError("the installed Anvil profile is a symbolic link and cannot be used as a migration source")
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
    if version and version >= ENGINEERING_VERSION:
        required.update({"scripts/engineering.py", "scripts/public_errors.py"})
    if version is None and "anvil-communication" in skills:
        required.update(path for path in ("scripts/artifacts.py", "skills/anvil-communication/SKILL.md", "commands/review.md")
                        if path in actual or path in symlinks or path in other)
    missing = sorted(path for path in required if path not in actual
                     and _symlink_ancestor(path, symlinks) is None and path not in other)
    if missing and not allow_missing:
        raise ManagedConfigError("source profile is missing files required by its own release: " + ", ".join(missing))
    owned = set(required)
    if version and version >= DATABRICKS_PROVIDER_VERSION:
        owned.update(_shipped_package("scripts/databricks_providers", "scripts/databricks_providers"))
    if version is None:
        known_legacy_scripts = BASE_REQUIRED_SCRIPTS | DATABRICKS_SCRIPTS | {"scripts/artifacts.py"}
        known_legacy_scripts |= _shipped_package("scripts/databricks_providers", "scripts/databricks_providers")
        known_legacy_scripts |= _shipped_package("scripts/communication", "scripts/communication")
        owned.update(known_legacy_scripts)
    if version and version >= COMMUNICATION_VERSION:
        owned.update(_shipped_package("scripts/communication", "scripts/communication"))
    if version and version >= ENGINEERING_VERSION:
        owned.update({"scripts/engineering.py", "scripts/public_errors.py"})
        owned.update(_shipped_package("scripts/engineering", "scripts/engineering"))
    for skill in skills:
        introduced = SKILL_INTRODUCED.get(skill)
        if version is not None and introduced is not None and version < introduced:
            continue
        shipped_skill = ROOT / "config" / "skills" / skill
        if shipped_skill.is_dir():
            owned.update(_shipped_package(f"skills/{skill}", f"config/skills/{skill}"))
    if major == 2:
        owned.update(_shipped_plugin_paths())
    owned.update(path for path in actual if path in {"AGENTS.md", "opencode.jsonc"}
                 or (path.startswith("commands/") and Path(path).stem in commands))
    owned.update(path for path in symlinks | other
                 if path in {"AGENTS.md", "opencode.jsonc"}
                 or (path.startswith("commands/") and Path(path).stem in commands))
    managed_links: set[str] = set()
    for relative in sorted(owned):
        link = _check_managed_path(relative, symlinks, recover_managed=allow_missing)
        if link:
            managed_links.add(link)
        if relative in other and not allow_missing:
            raise ManagedConfigError(f"Anvil-managed path is not a regular file: {relative}")
    owned.update(managed_links)
    owned.intersection_update(set(actual) | symlinks | other)
    return owned, missing


def inspect_source(root: Path, source_version: str | None = None,
                   expected_manifest_sha256: str | None = None, *, recover_managed: bool = False) -> dict[str, Any]:
    actual, symlinks, other = _scan(root)
    if MANIFEST_NAME in symlinks or MANIFEST_NAME in other:
        raise ManagedConfigError("Anvil managed file manifest is not a regular file")
    manifest_present = MANIFEST_NAME in actual
    if manifest_present:
        try:
            manifest = json.loads(_read_regular(root, MANIFEST_NAME).decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManagedConfigError(f"managed file manifest is unreadable: {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), dict):
            raise ManagedConfigError("managed file manifest has an unsupported shape")
        version = manifest.get("anvil_version")
        if parse_version(version) is None:
            raise ManagedConfigError("managed file manifest has an invalid Anvil version")
        if source_version and parse_version(source_version) and version != source_version:
            raise ManagedConfigError("managed file manifest version does not match installation metadata")
        if expected_manifest_sha256 and _digest_regular(root, MANIFEST_NAME) != expected_manifest_sha256:
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
        managed_links: set[str] = set()
        for relative, expected in manifest["files"].items():
            relative_path = _relative(relative)
            normalized = relative_path.as_posix()
            if normalized in owned:
                raise ManagedConfigError(f"managed file manifest contains duplicate normalized path: {normalized}")
            owned.add(normalized)
            owned_digests[normalized] = expected
            managed_link = _check_managed_path(normalized, symlinks, recover_managed=recover_managed)
            if managed_link:
                managed_links.add(managed_link)
                continue
            if normalized in other:
                if recover_managed:
                    continue
                raise ManagedConfigError(f"Anvil-managed path is not a regular file: {normalized}")
            if normalized not in actual:
                if recover_managed:
                    continue
                raise ManagedConfigError(f"Anvil-managed file is missing: {normalized}")
            if expected is None and normalized == "opencode.jsonc":
                continue
            if not isinstance(expected, str) or _digest_regular(root, normalized) != expected:
                if recover_managed:
                    continue
                raise ManagedConfigError(f"Anvil-managed file changed unexpectedly: {normalized}")
        owned.update(managed_links)
    else:
        if expected_manifest_sha256:
            raise ManagedConfigError("Anvil managed file manifest is missing")
        owned, _ = _legacy_owned(root, source_version, allow_missing=recover_managed)
        owned_digests = {path: (None if path == "opencode.jsonc" else _digest_regular(root, path))
                         for path in owned if path in actual}
    owned.update({MANIFEST_NAME} if manifest_present else set())
    nodes = set(actual) | symlinks | other
    user_files = sorted(path for path in nodes if path not in owned and not _is_user_preference(path))
    owned_existing = owned.intersection(actual)
    owned_digests = {path: digest_value for path, digest_value in owned_digests.items() if path in owned_existing}
    return {"owned_files": sorted(owned_existing - {MANIFEST_NAME}), "owned_digests": owned_digests,
            "user_files": user_files,
            "external_symlinks": sorted(symlinks - owned),
            "manifest_present": manifest_present,
            "manifest_version": (manifest.get("anvil_version") if manifest_present else None)}


def _target_manifest(root: Path, target_version: str, *, excluded: set[str] | None = None) -> dict[str, Any]:
    if parse_version(target_version) is None:
        raise ManagedConfigError("target Anvil release is not a numeric semantic version")
    files, symlinks, other = _scan(root)
    excluded = excluded or set()
    for relative in sorted(symlinks):
        if relative not in excluded:
            raise ManagedConfigError(f"target Anvil config contains an unclassified symbolic link: {relative}")
    for relative in sorted(other):
        if relative not in excluded:
            raise ManagedConfigError(f"target Anvil config contains an unclassified filesystem node: {relative}")
    _check_managed_path("opencode.jsonc", symlinks)
    inventory: dict[str, str | None] = {}
    for relative in sorted(files):
        if relative == MANIFEST_NAME or relative in excluded or _is_user_preference(relative):
            continue
        inventory[relative] = None if relative == "opencode.jsonc" else _digest_regular(root, relative)
    config = parse_jsonc(_read_regular(root, "opencode.jsonc").decode("utf-8"), str(root / "opencode.jsonc"))
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
    target_files, target_symlinks, target_other = _scan(target)
    target_nodes = set(target_files) | target_symlinks | target_other
    target_owned = target_nodes - {MANIFEST_NAME} - {path for path in target_nodes if _is_user_preference(path)}
    source_state: dict[str, Any] = {"owned_files": [], "user_files": [], "manifest_present": False}
    if source is not None and source.is_dir():
        source_state = inspect_source(source, source_version, source_manifest_sha256,
                                      recover_managed=recover_managed)
        target_prefixes: set[str] = set()
        for target_path in target_owned:
            parts = PurePosixPath(target_path).parts
            target_prefixes.update(PurePosixPath(*parts[:end]).as_posix() for end in range(1, len(parts)))
        conflicts = []
        for source_path in source_state["user_files"]:
            parts = PurePosixPath(source_path).parts
            source_parents = {PurePosixPath(*parts[:end]).as_posix() for end in range(1, len(parts))}
            if source_path in target_owned or source_path in target_prefixes or source_parents & target_owned:
                conflicts.append(source_path)
        conflicts.sort()
        if conflicts:
            raise ManagedConfigError("user-owned files conflict with new Anvil paths; move them before retrying: "
                                     + ", ".join(conflicts))
        for relative in source_state["user_files"]:
            source_path = source / relative
            target_path = target / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(target_path):
                raise ManagedConfigError(f"refusing to overwrite user-owned path: {relative}")
            if source_path.is_symlink():
                os.symlink(os.readlink(source_path), target_path)
            elif source_path.is_file():
                descriptor = _open_regular(source, relative)
                metadata = os.fstat(descriptor)
                with os.fdopen(descriptor, "rb") as source_stream, target_path.open("xb") as target_stream:
                    shutil.copyfileobj(source_stream, target_stream)
                target_path.chmod(stat.S_IMODE(metadata.st_mode))
                os.utime(target_path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns), follow_symlinks=False)
            else:
                raise ManagedConfigError(f"cannot safely preserve external filesystem node: {relative}")
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
