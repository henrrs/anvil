#!/usr/bin/env python3
"""Offline install/upgrade/dry-run/rollback contracts for Analytics packaging."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analytics_service import MARKER, sync  # noqa: E402
from managed_config import (MANIFEST_NAME, inspect_source, plan, snapshot,
                            validate_installed, restore_merge)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return ""
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            digest.update(b"L" + path.relative_to(root).as_posix().encode() + os.readlink(path).encode())
        elif path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def build_config(target: Path, home: Path, prior: Path | None = None) -> None:
    env = os.environ.copy()
    env.update({"ANVIL_ROOT": str(ROOT), "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_STATE_HOME": str(home / ".local" / "state"),
                "ANVIL_TEST_MODE": "1"})
    command = (
        'source "$ANVIL_ROOT/scripts/lib/common.sh"; '
        'source "$ANVIL_ROOT/scripts/lib/install.sh"; '
        'anvil_build_config "$1" "$2" yes 1'
    )
    subprocess.run(["bash", "-c", command, "analytics-lifecycle", str(target), str(prior or "")],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="anvil-analytics-lifecycle-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        fresh = root / "fresh-config"
        build_config(fresh, home)
        expected_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        installed = validate_installed(fresh, expected_version, expected_version)
        manifest = json.loads((fresh / MANIFEST_NAME).read_text(encoding="utf-8"))
        check("scripts/analytics/server.py" in manifest["files"],
              "fresh installation did not include the Analytics server in managed packaging")
        check("web/analytics/app.js" in manifest["files"],
              "fresh installation did not include the Analytics frontend")
        check("web/analytics/api.js" in manifest["files"],
              "fresh installation did not include the Analytics HTTP API adapter")
        check(not any(path.startswith("web/analytics/dev/") for path in manifest["files"]),
              "development-only mock files leaked into the production manifest")
        check(not (fresh / "web" / "analytics" / "dev").exists(),
              "development-only mock files were copied into the installed frontend")
        check("plugins/anvil-core-v1.ts" in manifest["files"],
              "OpenCode 1 fresh install did not include its compatible Anvil tools plugin")
        check("anvil_analytics_run_query" in (fresh / "plugins" / "anvil-core-v1.ts").read_text(encoding="utf-8"),
              "OpenCode 1 plugin does not expose Analytics tools")
        check((fresh / "scripts/analytics/server.py").stat().st_mode & 0o777 == 0o600,
              "installed Analytics code is not private")
        check(installed["manifest_present"], "fresh install did not produce an ownership manifest")
        installed_env = os.environ.copy()
        installed_env.update({"HOME": str(home), "ANVIL_HOME": str(home / ".anvil"),
                              "PYTHONPATH": str(fresh)})
        subprocess.run([sys.executable, "-m", "scripts.analytics.server", "--help"],
                       cwd=fresh, env=installed_env, check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)

        # Emulate an existing 2.15 installation that is upgraded by make upgrade.
        legacy = root / "legacy-config"
        shutil.copytree(fresh, legacy)
        shutil.rmtree(legacy / "scripts" / "analytics")
        shutil.rmtree(legacy / "web" / "analytics")
        legacy_manifest_path = legacy / MANIFEST_NAME
        legacy_manifest = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
        legacy_manifest["anvil_version"] = "2.15.0"
        legacy_manifest["files"] = {path: digest for path, digest in legacy_manifest["files"].items()
                                     if not path.startswith(("scripts/analytics/", "web/analytics/"))}
        legacy_manifest_path.write_text(json.dumps(legacy_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (legacy / "company" / "prompts").mkdir(parents=True)
        (legacy / "company" / "prompts" / "team.md").write_text("user-owned prompt\n", encoding="utf-8")
        (legacy / "cli.json").write_text('{"theme":"company"}\n', encoding="utf-8")
        check(validate_installed(legacy, "2.15.0", expected_version)["manifest_present"],
              "legacy managed config could not be inspected")

        # User-global data is created outside both managed config and backup.
        analytics_data = home / ".anvil" / "analytics"
        analytics_data.mkdir(parents=True, mode=0o700)
        private_data = analytics_data / "keep.db"
        private_data.write_bytes(b"user analytics data stays outside lifecycle config")
        private_data.chmod(0o600)
        private_hash = hashlib.sha256(private_data.read_bytes()).hexdigest()

        upgraded = root / "upgraded-config"
        build_config(upgraded, home, legacy)
        result = plan(inspect_source(legacy, "2.15.0"),
                      json.loads((upgraded / MANIFEST_NAME).read_text(encoding="utf-8")),
                      "2.15.0", expected_version)
        validate_installed(upgraded, expected_version, expected_version)
        check("scripts/analytics/server.py" in result["changes"]["added"],
              "upgrade plan did not add the Analytics server")
        check((upgraded / "company" / "prompts" / "team.md").read_text(encoding="utf-8") == "user-owned prompt\n",
              "upgrade did not preserve user-owned files")
        check((upgraded / "cli.json").read_text(encoding="utf-8").find("company") >= 0,
              "upgrade did not preserve user CLI preferences")
        check(hashlib.sha256(private_data.read_bytes()).hexdigest() == private_hash,
              "upgrade changed Analytics user data")

        core_only = root / "core-without-analytics"
        shutil.copytree(upgraded, core_only)
        shutil.rmtree(core_only / "scripts" / "analytics")
        shutil.rmtree(core_only / "web" / "analytics")
        validate_installed(core_only, expected_version, expected_version)

        systemd_dir = root / "systemd" / "user"
        service_state = sync(upgraded, home, systemd_dir, 28765, activate=False)
        check(service_state.startswith("CONFIGURED"), "user service unit was not configured safely")
        unit = systemd_dir / "anvil-analytics.service"
        check(unit.is_file() and MARKER in unit.read_text(encoding="utf-8"),
              "generated systemd unit is missing its Anvil ownership marker")
        check(str(upgraded) in unit.read_text(encoding="utf-8"),
              "systemd unit does not point at the installed managed package")

        # DRY_RUN is represented by the read-only transition planner: no source,
        # user state or service file may change while it produces a plan.
        source_hash = tree_hash(upgraded)
        service_hash = tree_hash(systemd_dir)
        target_plan = json.loads((upgraded / MANIFEST_NAME).read_text(encoding="utf-8"))
        dry_plan = plan(inspect_source(upgraded, expected_version), target_plan,
                        expected_version, expected_version)
        check(not dry_plan["changes"]["added"] and not dry_plan["changes"]["updated"]
              and not dry_plan["changes"]["removed"],
              f"repeated upgrade is not idempotent: {dry_plan['changes']}")
        check(tree_hash(upgraded) == source_hash and tree_hash(systemd_dir) == service_hash
              and hashlib.sha256(private_data.read_bytes()).hexdigest() == private_hash,
              "DRY_RUN changed managed config, service state or user data")

        # Rollback restores the prior Anvil-owned set, merges user files, removes
        # only Anvil's service unit and leaves the global Analytics database alone.
        backup = root / "snapshot"
        snapshot(legacy, backup)
        rollback_stage = root / "rollback-stage"
        shutil.copytree(backup, rollback_stage)
        restore_merge(upgraded, rollback_stage)
        check(not (rollback_stage / "scripts" / "analytics").exists()
              and not (rollback_stage / "web" / "analytics").exists(),
              "rollback retained newly introduced Analytics managed files")
        check((rollback_stage / "company" / "prompts" / "team.md").read_text(encoding="utf-8") == "user-owned prompt\n",
              "rollback did not merge user-owned files")
        removal = sync(rollback_stage, home, systemd_dir, 28765, activate=False)
        check(removal == "REMOVED" and not unit.exists(),
              "rollback did not remove its own service unit")
        check(hashlib.sha256(private_data.read_bytes()).hexdigest() == private_hash,
              "rollback changed Analytics user data")

        # A similarly named service owned by the user is never overwritten.
        systemd_dir.mkdir(parents=True, exist_ok=True)
        user_unit = systemd_dir / "anvil-analytics.service"
        user_unit.write_text("[Unit]\nDescription=User-owned\n", encoding="utf-8")
        try:
            sync(upgraded, home, systemd_dir, 28765, activate=False)
        except ValueError as exc:
            check("user-owned" in str(exc), "service collision failed for an unexpected reason")
        else:
            raise AssertionError("Anvil overwrote a user-owned systemd unit")
        check("User-owned" in user_unit.read_text(encoding="utf-8"),
              "user-owned systemd service content was changed")

    print("PASS Analytics fresh install, upgrade, idempotency, read-only plan, rollback, service ownership and data preservation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
