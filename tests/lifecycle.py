#!/usr/bin/env python3
"""Isolated OpenCode 1 lifecycle integration checks."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(sys.argv[1]).resolve()
CANDIDATE = Path(sys.argv[2]).resolve()
VERSION = sys.argv[3].removeprefix("opencode ").removeprefix("v")
TEST_ROOT = Path(sys.argv[4]).resolve()
FIXTURE_BIN = ROOT / "tests/fixtures/bin"
ANVIL_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def check(value: Any, reason: str) -> None:
    if not value:
        raise AssertionError(reason)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {item.relative_to(root).as_posix(): digest(item)
            for item in sorted(root.rglob("*")) if item.is_file() and not item.is_symlink()}


def run(command: list[str], env: dict[str, str], *, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True,
                            timeout=180, check=False)
    if result.returncode != expected:
        raise AssertionError(f"{command!r} returned {result.returncode}, expected {expected}\n"
                             f"stdout:\n{result.stdout[-3500:]}\nstderr:\n{result.stderr[-3500:]}")
    return result


def environment(root: Path, *, candidate: Path | None = None, **extra: str) -> dict[str, str]:
    home, config_home, data_home, state_home = (
        root / "home", root / "xdg-config", root / "xdg-data", root / "xdg-state")
    env = {
        "PATH": str(home / ".opencode/bin") + os.pathsep + "/usr/bin:/bin",
        "HOME": str(home), "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(data_home), "XDG_STATE_HOME": str(state_home),
        "SHELL": "/bin/bash", "TMPDIR": str(TEST_ROOT), "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1", "PYTHONPATH": str(ROOT / "tests/fixtures/network-denied"),
        "ANVIL_NETWORK_GUARD_LOG": str(root / "network-attempts.log"),
        "ANVIL_DATABRICKS_CLI": "/nonexistent/anvil-test-databricks",
        "ANVIL_DATABRICKS_SCENARIO": "valid", "ANVIL_TEST_REPO": str(ROOT),
        "ANVIL_TEST_MODE": "1", "ANVIL_DOCTOR_LOCAL": "1", "ANVIL_YES": "1",
    }
    if candidate:
        env["ANVIL_TEST_CANDIDATE_BINARY"] = str(candidate)
    env.update(extra)
    return env


def create_fixture(root: Path) -> dict[str, Path]:
    home, config_home, data_home, state_home = (
        root / "home", root / "xdg-config", root / "xdg-data", root / "xdg-state")
    config, install_bin = config_home / "opencode", home / ".opencode/bin"
    data_opencode, anvil_data = data_home / "opencode", data_home / "anvil"
    state_opencode = state_home / "opencode"
    for path in (config, install_bin, data_opencode, anvil_data / "memory/company", state_opencode):
        path.mkdir(parents=True, exist_ok=True)

    paths = {"home": home, "config_home": config_home, "data_home": data_home,
             "state_home": state_home, "config": config, "install_bin": install_bin,
             "data_opencode": data_opencode, "anvil_data": anvil_data,
             "memory": anvil_data / "memory", "state_opencode": state_opencode}
    generated = root / "generated-config"
    env = environment(root)
    run(["bash", "-c", 'source "$ANVIL_ROOT/scripts/lib/common.sh"; '
         'source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" ""',
         "_", str(generated)], {**env, "ANVIL_ROOT": str(ROOT)})
    shutil.copytree(generated, config, dirs_exist_ok=True)
    shutil.rmtree(generated)

    profile_path = config / "opencode.jsonc"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["provider"] = {"custom": {"name": "Fixture Provider",
                                      "npm": "@ai-sdk/openai-compatible",
                                      "api": "https://example.invalid/v1",
                                      "options": {"headers": {"x-fixture": "opaque"}}}}
    profile["plugin"].append("@company/opencode-audit")
    profile["mcp"] = {"internal-catalog": {"type": "local", "command": "company-catalog"}}
    profile["theme"] = "company-dark"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    (config / "cli.json").write_text('{"theme":"fixture"}\n', encoding="utf-8")
    for relative, content in (
        ("commands/user-command.md", "User command fixture\n"),
        ("agents/custom.md", "User agent fixture\n"),
        ("scripts/user-helper.py", "# user-owned helper\n"),
        ("plugins/company-plugin.ts", "// user plugin fixture\n"),
        ("skills/company/SKILL.md", "---\nname: company\ndescription: Company fixture skill\n---\n\n# Company skill fixture\n"),
    ):
        path = config / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    binary = install_bin / "opencode"
    binary.write_text("#!/usr/bin/env bash\nexec " + shlex.quote(str(CANDIDATE)) + ' "$@"\n',
                      encoding="utf-8")
    binary.chmod(0o755)
    (data_opencode / "auth.json").write_text('{"opaque":"fixture-auth"}\n', encoding="utf-8")
    (state_opencode / "session.fixture").write_text("opaque session state\n", encoding="utf-8")
    (anvil_data / "memory/company/notes.md").write_text(
        "---\nid: 'fixture-memory'\ntype: 'fact'\nscope: 'company'\ntags:\n  - 'fixture'\n"
        "source:\n  type: 'user-explicit'\n  note: 'Lifecycle preservation fixture'\n"
        "confidence: 'confirmed'\ncreated: 2026-01-12\nupdated: 2026-01-12\n---\n\n"
        "Persisted local memory fixture.\n", encoding="utf-8")
    manifest = config / ".anvil-managed.json"
    (anvil_data / "installation.json").write_text(json.dumps({
        "schema_version": 3, "anvil_version": ANVIL_VERSION, "runtime_major": 1,
        "runtime_profile": "opencode-v1", "version": VERSION, "binary": str(binary),
        "managed_config_manifest_sha256": digest(manifest),
        "migration": {"status": "installed"},
    }, indent=2) + "\n", encoding="utf-8")
    (home / ".bashrc").write_text("# user shell config\n", encoding="utf-8")
    run([sys.executable, str(ROOT / "scripts/runtime_state.py"), "record"],
        environment(root))
    return paths


def assert_network_clean(root: Path) -> None:
    log = root / "network-attempts.log"
    check(not log.exists() or not log.read_text(encoding="utf-8").strip(),
          "offline lifecycle attempted external network access")


def read_only_and_upgrade_test(root: Path) -> None:
    paths = create_fixture(root)
    env = environment(root)
    before = {name: tree(paths[name]) for name in
              ("config", "data_opencode", "state_opencode", "memory")}
    for command in (["inspect"], ["doctor"], ["capabilities", "FORMAT=json"]):
        run(["/usr/bin/make", "--no-print-directory", *command], env)
    after = {name: tree(paths[name]) for name in before}
    check(before == after, "read-only lifecycle commands changed installed files")

    run(["/usr/bin/make", "--no-print-directory", "upgrade", "DRY_RUN=1"], env)
    check(before == {name: tree(paths[name]) for name in before},
          "Anvil upgrade dry run changed config, credentials, runtime data or memory")
    check(not (paths["anvil_data"] / "backups").exists(), "dry run created a backup")

    initial_binary = digest(paths["install_bin"] / "opencode")
    preserved = {
        "config": {relative: digest(paths["config"] / relative) for relative in (
            "cli.json", "commands/user-command.md", "agents/custom.md",
            "scripts/user-helper.py", "plugins/company-plugin.ts", "skills/company/SKILL.md")},
        "auth": digest(paths["data_opencode"] / "auth.json"),
        "session": digest(paths["state_opencode"] / "session.fixture"),
        "memory": digest(paths["memory"] / "company/notes.md"),
    }
    run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    profile = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    installed = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    check(profile["provider"]["custom"]["options"]["headers"]["x-fixture"] == "opaque",
          "upgrade changed user provider configuration")
    check(profile["plugin"][-1] == "@company/opencode-audit" and profile["mcp"]["internal-catalog"]["command"] == "company-catalog",
          "upgrade changed user plugins or MCP settings")
    check(profile["theme"] == "company-dark", "upgrade changed a shared user preference")
    for relative, expected in preserved["config"].items():
        check(digest(paths["config"] / relative) == expected, f"upgrade changed user-owned config file {relative}")
    check(digest(paths["data_opencode"] / "auth.json") == preserved["auth"],
          "upgrade changed opaque OpenCode authentication")
    check(digest(paths["state_opencode"] / "session.fixture") == preserved["session"],
          "upgrade changed opaque OpenCode session state")
    check(digest(paths["memory"] / "company/notes.md") == preserved["memory"],
          "upgrade changed persisted user memory")
    check(digest(paths["install_bin"] / "opencode") == initial_binary,
          "Anvil upgrade replaced the OpenCode executable")
    check(installed["anvil_version"] == ANVIL_VERSION and installed["runtime_major"] == 1,
          "upgrade did not record the current Anvil release on OpenCode 1")
    backup = Path(installed["migration"]["backup"])
    run([sys.executable, str(ROOT / "scripts/state.py"), "verify", str(backup)], env)
    assert_network_clean(root)
    print("PASS inspect/doctor/capabilities are read-only; Anvil upgrade preserves OpenCode 1, credentials, state, memory and user config")


def rollback_on_failure_test(root: Path) -> None:
    paths = create_fixture(root)
    managed = paths["config"] / "scripts/memory.py"
    managed.write_text("# recoverable local managed drift\n", encoding="utf-8")
    before = {name: tree(paths[name]) for name in ("config", "data_opencode", "state_opencode", "memory")}
    binary_before = digest(paths["install_bin"] / "opencode")
    env = environment(root, ANVIL_TEST_FAIL_AFTER_CONFIG="1")
    result = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env, expected=2)
    check("Automatic Anvil rollback completed" in result.stderr,
          "upgrade failure after replacement did not report snapshot rollback")
    check(before == {name: tree(paths[name]) for name in before},
          "automatic rollback did not restore the exact pre-upgrade config, data, state and memory")
    check(digest(paths["install_bin"] / "opencode") == binary_before,
          "automatic rollback changed the OpenCode executable")
    check(json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))["anvil_version"] == ANVIL_VERSION,
          "automatic rollback changed installation metadata")
    assert_network_clean(root)
    print("PASS post-replacement failure restores managed drift and preserves runtime/user state")


def reforge_first_install_test(root: Path) -> None:
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / ".bashrc").write_text("# user shell config\n", encoding="utf-8")
    env = environment(root, candidate=CANDIDATE, ANVIL_YES="1", PATH="/usr/bin:/bin")
    run(["/usr/bin/make", "--no-print-directory", "reforge"], env)
    paths = {"config": root / "xdg-config/opencode",
             "binary": root / "home/.opencode/bin/opencode",
             "record": root / "xdg-data/anvil/installation.json"}
    check((paths["config"] / "opencode.jsonc").is_file(), "first reforge did not create the V1 config")
    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    check(record["runtime_major"] == 1 and record["version"] == VERSION,
          "first reforge did not install the selected OpenCode 1 candidate")
    first_config = tree(paths["config"])
    run(["/usr/bin/make", "--no-print-directory", "reforge"], env)
    check(tree(paths["config"]) == first_config, "repeating reforge changed the managed config")
    shell = (root / "home/.bashrc").read_text(encoding="utf-8")
    check(shell.count("# Anvil: OpenCode install directory") == 1,
          "repeated reforge duplicated the PATH entry")
    assert_network_clean(root)
    print("PASS isolated first-install reforge is repeatable and keeps one PATH entry")


def main() -> None:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anvil-lifecycle-readonly-", dir=TEST_ROOT) as name:
        read_only_and_upgrade_test(Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-lifecycle-rollback-", dir=TEST_ROOT) as name:
        rollback_on_failure_test(Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-lifecycle-first-install-", dir=TEST_ROOT) as name:
        reforge_first_install_test(Path(name))


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
