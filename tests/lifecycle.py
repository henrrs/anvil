#!/usr/bin/env python3
"""Isolated V1/V2 lifecycle and failure-recovery integration tests."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = pathlib.Path(sys.argv[1]).resolve()
CANDIDATE_V2 = pathlib.Path(sys.argv[2]).resolve()
VERSION_V2 = sys.argv[3]
CANDIDATE_V1 = pathlib.Path(sys.argv[4]).resolve()
VERSION_V1 = sys.argv[5]
TEST_ROOT = pathlib.Path(sys.argv[6]).resolve()
FIXTURES = ROOT / "tests" / "fixtures"
V1_CONFIG = FIXTURES / "v1" / "opencode.jsonc"
V1_MEMORY = FIXTURES / "v1" / "memory" / "company" / "databricks-secret-policy.md"


def check(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def file_hash(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        p.relative_to(path).as_posix(): file_hash(p)
        for p in sorted(path.rglob("*")) if p.is_file() and not p.is_symlink()
    }


def fixture(temp: pathlib.Path) -> dict[str, pathlib.Path]:
    home = temp / "home"
    config_home = temp / "xdg-config"
    data_home = temp / "xdg-data"
    state_home = temp / "xdg-state"
    config = config_home / "opencode"
    install_bin = home / ".opencode" / "bin"
    data_opencode = data_home / "opencode"
    anvil_data = data_home / "anvil"
    state_opencode = state_home / "opencode"
    for path in (config, install_bin, data_opencode, anvil_data / "memory" / "company", state_opencode):
        path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(V1_CONFIG, config / "opencode.jsonc")
    original = json.loads((config / "opencode.jsonc").read_text(encoding="utf-8"))
    original["provider"] = {
        "custom": {
            "name": "Fixture Provider",
            "npm": "@ai-sdk/openai-compatible",
            "api": "https://example.invalid/v1",
            "options": {"headers": {"x-fixture": "safe"}, "temperature": 0.2},
            "models": {
                "fixture-model": {
                    "id": "fixture-model-v2",
                    "options": {"maxTokens": 2048},
                    "variants": {"reasoning": {"reasoningEffort": "high"}},
                }
            },
        }
    }
    write_json(config / "opencode.jsonc", original)
    (config / "AGENTS.md").write_text("V1 global Anvil rules fixture\n", encoding="utf-8")
    (config / "cli.json").write_text('{"theme":"fixture"}\n', encoding="utf-8")
    (config / "tui.json").write_text('{"tabs":{"mode":"off"}}\n', encoding="utf-8")
    (config / "commands").mkdir(exist_ok=True)
    (config / "commands" / "user-command.md").write_text("legacy user command\n", encoding="utf-8")
    (home / ".bashrc").write_text("# fixture shell startup\n", encoding="utf-8")
    (data_opencode / "auth.json").write_text('{"fixture":true}\n', encoding="utf-8")
    (state_opencode / "state.fixture").write_text("opaque OpenCode state fixture\n", encoding="utf-8")
    shutil.copy2(V1_MEMORY, anvil_data / "memory" / "company" / V1_MEMORY.name)
    write_json(anvil_data / "installation.json", {"version": "1.19.0", "fixture": True})
    fake_binary = install_bin / "opencode"
    fake_binary.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == --version ]]; then printf 'opencode v1.19.0\\n'; "
        "elif [[ \"${1:-}\" == debug && \"${2:-}\" == paths ]]; then printf 'config fixture\\ndata fixture\\n'; "
        "elif [[ \"${1:-}\" == stats ]]; then printf 'Fixture native statistics\\n'; "
        "else exit 0; fi\n",
        encoding="utf-8",
    )
    fake_binary.chmod(0o755)
    return {
        "home": home, "config_home": config_home, "data_home": data_home,
        "state_home": state_home, "config": config, "install_bin": install_bin,
        "binary": fake_binary, "data_opencode": data_opencode,
        "anvil_data": anvil_data, "memory": anvil_data / "memory",
        "state_opencode": state_opencode,
    }


def use_v2_profile(paths: dict[str, pathlib.Path], temp: pathlib.Path, wrapper: pathlib.Path) -> None:
    built = temp / "opencode-v2-config"
    run(
        ["bash", "-c", "source \"$ANVIL_ROOT/scripts/lib/common.sh\"; "
         "source \"$ANVIL_ROOT/scripts/lib/install.sh\"; anvil_build_config \"$1\" \"$2\" yes 2",
         "_", str(built), str(paths["config"])],
        env_for(paths, ANVIL_ROOT=str(ROOT)),
    )
    shutil.rmtree(paths["config"])
    shutil.move(str(built), str(paths["config"]))
    (paths["data_home"] / "anvil" / "knowledge").mkdir(parents=True, exist_ok=True)
    paths["binary"].write_text(
        "#!/usr/bin/env bash\n" f"exec {shlex.quote(str(wrapper))} \"$@\"\n",
        encoding="utf-8",
    )
    paths["binary"].chmod(0o755)
    write_json(paths["anvil_data"] / "installation.json", {
        "schema_version": 2,
        "anvil_version": "2.0.0",
        "version": VERSION_V2,
        "runtime_major": 2,
        "profile": "opencode-v2",
        "binary_path": str(paths["binary"]),
        "migration": {"status": "completed"},
    })


def env_for(paths: dict[str, pathlib.Path], **extra: str) -> dict[str, str]:
    result = {
        "PATH": str(paths["install_bin"]) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(paths["home"]),
        "XDG_CONFIG_HOME": str(paths["config_home"]),
        "XDG_DATA_HOME": str(paths["data_home"]),
        "XDG_STATE_HOME": str(paths["state_home"]),
        "SHELL": "/bin/bash",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "ANVIL_DATABRICKS_CLI": "/nonexistent/anvil-test-databricks",
    }
    result.update(extra)
    return result


def run(command: list[str], env: dict[str, str], *, cwd: pathlib.Path = ROOT, expected: int = 0) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=180)
    if proc.returncode != expected:
        raise AssertionError(
            f"command {command!r} returned {proc.returncode}, expected {expected}\n"
            f"stdout:\n{proc.stdout[-5000:]}\nstderr:\n{proc.stderr[-5000:]}"
        )
    return proc


def provider_migration_test(temp: pathlib.Path) -> None:
    paths = fixture(temp)
    proc = run(
        ["bash", "-c", "source \"$ANVIL_ROOT/scripts/lib/common.sh\"; "
         "source \"$ANVIL_ROOT/scripts/lib/install.sh\"; anvil_build_config \"$1\" \"$2\" yes",
         "_", str(temp / "built-config"), str(paths["config"])],
        env_for(paths, ANVIL_ROOT=str(ROOT)),
    )
    config = json.loads((temp / "built-config" / "opencode.jsonc").read_text(encoding="utf-8"))
    provider = config["providers"]["custom"]
    model = provider["models"]["fixture-model"]
    check(provider["package"] == "aisdk:@ai-sdk/openai-compatible", "V1 npm adapter was not migrated")
    check(provider["settings"]["baseURL"] == "https://example.invalid/v1", "V1 provider API was not mapped to baseURL")
    check(provider["headers"] == {"x-fixture": "safe"}, "provider headers were not preserved")
    check(model["modelID"] == "fixture-model-v2", "V1 model id was not migrated")
    check(model["settings"]["maxTokens"] == 2048, "V1 model options were not preserved")
    check(model["variants"] == [{"id": "reasoning", "settings": {"reasoningEffort": "high"}}], "V1 model variants were not migrated")
    check(not ({"provider", "agent", "plugin", "model"} & set(config)), "V1 top-level config keys remain")
    check((temp / "built-config" / "cli.json").read_text(encoding="utf-8").startswith("{\"theme\""), "native CLI config was not preserved")
    check((temp / "built-config" / "tui.json").is_file(), "V1 TUI config needed for native migration was not preserved")
    run(
        ["bash", "-c", "source \"$ANVIL_ROOT/scripts/lib/common.sh\"; "
         "source \"$ANVIL_ROOT/scripts/lib/install.sh\"; anvil_build_config \"$1\" \"$2\" yes 1",
         "_", str(temp / "rebuilt-v1"), str(temp / "built-config")],
        env_for(paths, ANVIL_ROOT=str(ROOT)),
    )
    v1_roundtrip = json.loads((temp / "rebuilt-v1" / "opencode.jsonc").read_text(encoding="utf-8"))
    provider_v1 = v1_roundtrip["provider"]["custom"]
    check(provider_v1["npm"] == "@ai-sdk/openai-compatible" and provider_v1["api"] == "https://example.invalid/v1", "V2-to-V1 runtime adapter lost provider settings")
    check(provider_v1["models"]["fixture-model"]["id"] == "fixture-model-v2", "V2-to-V1 runtime adapter lost model identity")
    print("PASS V1 provider/model settings migrate, and CLI/TUI preferences survive config staging")


def rehearsal_test(temp: pathlib.Path, wrapper: pathlib.Path) -> None:
    paths = fixture(temp)
    before = {
        "config": tree_hash(paths["config"]),
        "data": tree_hash(paths["data_opencode"]),
        "state": tree_hash(paths["state_opencode"]),
        "memory": tree_hash(paths["memory"]),
        "binary": file_hash(paths["binary"]),
    }
    run(["bash", str(ROOT / "scripts" / "rehearse-upgrade.sh"), str(wrapper), VERSION_V2, "1", "2"], env_for(paths))
    after = {
        "config": tree_hash(paths["config"]),
        "data": tree_hash(paths["data_opencode"]),
        "state": tree_hash(paths["state_opencode"]),
        "memory": tree_hash(paths["memory"]),
        "binary": file_hash(paths["binary"]),
    }
    check(before == after, "rehearsal modified the live fixture")
    print("PASS exact OpenCode 2 candidate rehearses V1 config, opaque data/state and V1 Markdown memory without live changes")


def reforge_test(temp: pathlib.Path, wrapper: pathlib.Path) -> None:
    paths = fixture(temp)
    paths["binary"].unlink()
    env = env_for(paths,
        ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), ANVIL_YES="1",
        PATH="/usr/bin:/bin",
    )
    first = run(["/usr/bin/make", "--no-print-directory", "reforge"], env)
    config_tree = tree_hash(paths["config"])
    second = run(["/usr/bin/make", "--no-print-directory", "reforge"], env)
    check(tree_hash(paths["config"]) == config_tree, "repeating reforge changed its managed config")
    startup = (paths["home"] / ".bashrc").read_text(encoding="utf-8")
    check(startup.count("# Anvil: OpenCode install directory") == 1, "repeated reforge duplicated PATH startup entry")
    installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    check(installation["anvil_version"] == (ROOT / "VERSION").read_text().strip() and installation["version"] == VERSION_V1, "reforge did not follow first-install runtime policy")
    check(installation["runtime_major"] == 1, "first-install reforge ignored the approved OpenCode 1 policy")
    check("Status: HEALTHY" in first.stdout and "Status: HEALTHY" in second.stdout, "reforge postflight doctor failed")
    print("PASS first-install reforge follows the OpenCode 1 policy and remains repeatable")


def reforge_preserves_v2_test(temp: pathlib.Path, wrapper: pathlib.Path) -> None:
    paths = fixture(temp)
    use_v2_profile(paths, temp, wrapper)
    env = env_for(paths, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), ANVIL_YES="1")
    proc = run(["/usr/bin/make", "--no-print-directory", "reforge"], env)
    installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    check(installation["runtime_major"] == 2 and installation["version"].startswith("2."), "reforge changed an existing OpenCode 2 runtime")
    check("agents" in config and "agent" not in config, "reforge did not retain the OpenCode 2 config adapter")
    check("Status: HEALTHY" in proc.stdout, "OpenCode 2 reforge postflight doctor failed")
    print("PASS make reforge preserves the selected OpenCode 2 runtime profile")


def upgrade_test(
    temp: pathlib.Path,
    wrapper: pathlib.Path,
    *,
    fail: str | None = None,
    external_binary: bool = False,
) -> None:
    paths = fixture(temp)
    if external_binary:
        external_bin = paths["home"] / ".local" / "bin"
        external_bin.mkdir(parents=True, exist_ok=True)
        external_binary_path = external_bin / "opencode"
        shutil.move(paths["binary"], external_binary_path)
        paths["binary"] = external_binary_path
        shutil.rmtree(paths["home"] / ".opencode")

    def upgrade_env(**extra: str) -> dict[str, str]:
        env = env_for(paths, **extra)
        if external_binary:
            env["PATH"] = str(paths["binary"].parent) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")
        return env

    if external_binary:
        doctor = run(["/usr/bin/make", "--no-print-directory", "doctor"], upgrade_env())
        check("Status: UPGRADE AVAILABLE" in doctor.stdout, "doctor did not recognize an older Anvil install")
        check("make upgrade" in doctor.stderr, "doctor did not explain the Anvil product upgrade path")
        stats = run(["/usr/bin/make", "--no-print-directory", "stats"], upgrade_env())
        check("Fixture native statistics" in stats.stdout, "V1 native text stats were not forwarded")
        check("ERROR" not in stats.stderr, "V1 stats should not report an error")

    original_config = tree_hash(paths["config"])
    original_data = tree_hash(paths["data_opencode"])
    original_state = tree_hash(paths["state_opencode"])
    original_memory = tree_hash(paths["memory"])
    original_binary = file_hash(paths["binary"])
    original_installation = file_hash(paths["anvil_data"] / "installation.json")
    extra = {
        "ANVIL_TEST_MODE": "1",
        "ANVIL_TEST_CANDIDATE_BINARY": str(wrapper),
        "ANVIL_YES": "1",
    }
    if fail:
        extra[fail] = "1"
    if fail in {"ANVIL_TEST_FAIL_CANDIDATE_VALIDATION", "ANVIL_TEST_FAIL_REHEARSAL"}:
        proc = run(["/usr/bin/make", "--no-print-directory", "migrate-runtime", "OPENCODE_MAJOR=2"], upgrade_env(**extra), expected=2)
        expected = "injected candidate runtime validation failure" if fail == "ANVIL_TEST_FAIL_CANDIDATE_VALIDATION" else "Injected rehearsal failure"
        check(expected in proc.stderr, "candidate/rehearsal failure was not reported")
        check(tree_hash(paths["config"]) == original_config, "failed rehearsal changed config")
        check(tree_hash(paths["data_opencode"]) == original_data, "failed rehearsal changed OpenCode data")
        check(tree_hash(paths["state_opencode"]) == original_state, "failed rehearsal changed OpenCode state")
        check(not (paths["anvil_data"] / "backups").exists(), "failed rehearsal created a live backup")
        print(f"PASS {fail} aborts before backup or live mutation")
        return
    if fail == "ANVIL_TEST_FAIL_BACKUP":
        proc = run(["/usr/bin/make", "--no-print-directory", "migrate-runtime", "OPENCODE_MAJOR=2"], upgrade_env(**extra), expected=2)
        check("Injected backup creation failure" in proc.stderr, "backup creation failure was not reported")
        check(tree_hash(paths["config"]) == original_config, "backup failure changed config")
        check(tree_hash(paths["data_opencode"]) == original_data, "backup failure changed OpenCode data")
        check(tree_hash(paths["state_opencode"]) == original_state, "backup failure changed OpenCode state")
        check(file_hash(paths["binary"]) == original_binary, "backup failure changed runtime")
        check(not (paths["anvil_data"] / "backups").exists(), "failed backup left a partial backup directory")
        print("PASS backup creation failure aborts before any live mutation")
        return
    if fail == "ANVIL_TEST_FAIL_AFTER_BACKUP":
        proc = run(["/usr/bin/make", "--no-print-directory", "migrate-runtime", "OPENCODE_MAJOR=2"], upgrade_env(**extra), expected=2)
        check("Injected failure after backup" in proc.stderr, "backup failure was not reported")
        check(tree_hash(paths["config"]) == original_config, "post-backup failure changed config")
        check(file_hash(paths["binary"]) == original_binary, "post-backup failure changed runtime")
        check(tree_hash(paths["data_opencode"]) == original_data, "post-backup failure changed data")
        print("PASS verified backup followed by pre-mutation failure leaves the V1 runtime untouched")
        return

    proc = run(["/usr/bin/make", "--no-print-directory", "migrate-runtime", "OPENCODE_MAJOR=2"], upgrade_env(**extra), expected=2 if fail else 0)
    if fail:
        check("Automatic rollback completed" in proc.stderr, "upgrade failure did not report automatic rollback")
        check(tree_hash(paths["config"]) == original_config, "automatic rollback did not restore V1 config")
        check(file_hash(paths["binary"]) == original_binary, "automatic rollback did not restore V1 executable")
        check(tree_hash(paths["data_opencode"]) == original_data, "automatic rollback did not restore OpenCode data")
        check(tree_hash(paths["state_opencode"]) == original_state, "automatic rollback did not restore OpenCode state")
        check(file_hash(paths["anvil_data"] / "installation.json") == original_installation, "automatic rollback did not restore installation metadata")
        check(tree_hash(paths["memory"]) == original_memory, "automatic rollback changed Anvil memory")
        check(list((paths["anvil_data"] / "memory-backups").glob("memory-before-rollback-*.tar.gz")), "automatic rollback did not archive current memory")
        print(f"PASS injected {fail} automatically restores runtime/config/data/state and preserves Anvil memory")
        return

    installed = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    check(installed["anvil_version"] == (ROOT / "VERSION").read_text().strip() and installed["version"] == VERSION_V2, "installation metadata is not versioned")
    check(installed["runtime_major"] == 2, "explicit migration did not select runtime major 2")
    check(installed["migration"]["status"] == "completed" and installed["migration"]["from_runtime_major"] == 1, "V1 migration provenance is missing")
    check(config["providers"]["custom"]["package"] == "aisdk:@ai-sdk/openai-compatible", "V1 provider configuration was lost")
    check(tree_hash(paths["memory"]) == original_memory, "V1 Markdown memory was rewritten")
    check(tree_hash(paths["data_opencode"]) == original_data, "live OpenCode data changed during upgrade")
    check(tree_hash(paths["state_opencode"]) == original_state, "live OpenCode state changed during upgrade")
    backup = pathlib.Path(installed["migration"]["backup"])
    run([sys.executable, str(ROOT / "scripts" / "state.py"), "verify", str(backup)], env_for(paths))
    check("Status: HEALTHY" in proc.stdout, "post-upgrade doctor did not report healthy")
    if external_binary:
        check(file_hash(paths["binary"]) == original_binary, "upgrade changed the external V1 executable")
        startup = (paths["home"] / ".bashrc").read_text(encoding="utf-8")
        check(startup.count("# Anvil: OpenCode install directory") == 1, "upgrade did not add the managed executable to PATH")
    print("PASS migrate-runtime installs the rehearsed candidate and records a verified V1 rollback snapshot")

    rolled = run(["/usr/bin/make", "--no-print-directory", "rollback"], env_for(paths))
    restored_config = tree_hash(paths["config"])
    check(restored_config == original_config, "manual rollback did not restore all V1 config files")
    check(file_hash(paths["binary"]) == original_binary, "manual rollback did not restore V1 executable")
    check(tree_hash(paths["data_opencode"]) == original_data and tree_hash(paths["state_opencode"]) == original_state, "manual rollback did not restore OpenCode data/state")
    check(tree_hash(paths["memory"]) == original_memory, "manual rollback changed Anvil memory")
    check("Current Anvil memory was archived before rollback" in rolled.stderr, "manual rollback did not archive current memory")
    if external_binary:
        check(file_hash(paths["binary"]) == original_binary, "rollback changed the external V1 executable")
        check(not (paths["home"] / ".opencode").exists(), "rollback left a managed installer that did not exist before upgrade")
        startup = (paths["home"] / ".bashrc").read_text(encoding="utf-8")
        check("# Anvil: OpenCode install directory" not in startup, "rollback left a PATH entry for the removed managed binary")
    print("PASS make rollback restores the complete V1 snapshot and keeps the Markdown memory in place")


def upgrade_preserves_v1_test(temp: pathlib.Path, wrapper: pathlib.Path) -> None:
    paths = fixture(temp)
    before_data = tree_hash(paths["data_opencode"])
    before_state = tree_hash(paths["state_opencode"])
    env = env_for(paths, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), ANVIL_YES="1")
    proc = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    installed = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    check(installed["runtime_major"] == 1 and installed["version"].startswith("1."), "make upgrade changed OpenCode 1 major")
    check(installed["anvil_version"] == (ROOT / "VERSION").read_text().strip(), "make upgrade did not update the Anvil release independently")
    check(config.get("default_agent") == "anvil" and "agent" in config, "Anvil 2.3 V1 runtime config was not installed")
    check(config["provider"]["custom"]["api"] == "https://example.invalid/v1", "same-major Anvil upgrade lost V1 provider config")
    check(tree_hash(paths["data_opencode"]) == before_data and tree_hash(paths["state_opencode"]) == before_state, "make upgrade changed OpenCode data/state")
    check("Target OpenCode major     1 (preserved)" in proc.stdout, "upgrade plan did not state that OpenCode major 1 is preserved")
    check("Status: HEALTHY" in proc.stdout, "OpenCode 1 Anvil 2.3 doctor was not healthy")
    for section in ("Capabilities", "Stats", "Memory", "Knowledge", "Project overrides", "Version documentation"):
        check(section in proc.stdout, f"OpenCode 1 doctor omitted the {section} category")
    check("/distill               YES" in proc.stdout and "file-fallback" in proc.stdout, "OpenCode 1 doctor omitted core command or fallback capability status")
    print("PASS make upgrade advances Anvil on OpenCode 1 without changing the runtime major")


def upgrade_preserves_v2_test(temp: pathlib.Path, wrapper: pathlib.Path) -> None:
    paths = fixture(temp)
    use_v2_profile(paths, temp, wrapper)
    before_data = tree_hash(paths["data_opencode"])
    before_state = tree_hash(paths["state_opencode"])
    env = env_for(paths, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), ANVIL_YES="1")
    proc = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    installed = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    check(installed["runtime_major"] == 2 and installed["version"].startswith("2."), "make upgrade changed OpenCode 2 major")
    check(installed["anvil_version"] == (ROOT / "VERSION").read_text().strip(), "make upgrade did not advance the Anvil release on OpenCode 2")
    check("agents" in config and "agent" not in config and "anvil-core" in str(config.get("plugins")), "OpenCode 2 profile was not retained by same-major upgrade")
    check(tree_hash(paths["data_opencode"]) == before_data and tree_hash(paths["state_opencode"]) == before_state, "OpenCode 2 upgrade changed opaque user data/state")
    check("Target OpenCode major     2 (preserved)" in proc.stdout, "upgrade plan did not state that OpenCode major 2 is preserved")
    check("Status: HEALTHY" in proc.stdout, "OpenCode 2 Anvil 2.3 doctor was not healthy")
    for section in ("Capabilities", "Stats", "Memory", "Knowledge", "Project overrides", "Version documentation"):
        check(section in proc.stdout, f"OpenCode 2 doctor omitted the {section} category")
    check("/distill               YES" in proc.stdout and "native-tool+file-fallback" in proc.stdout, "OpenCode 2 doctor omitted core command or native search capability status")
    print("PASS make upgrade advances Anvil on OpenCode 2 without changing the runtime major")


def dry_run_test(temp: pathlib.Path, wrapper_v1: pathlib.Path, wrapper_v2: pathlib.Path) -> None:
    paths = fixture(temp)
    before = {
        "config": tree_hash(paths["config"]), "data": tree_hash(paths["data_opencode"]),
        "state": tree_hash(paths["state_opencode"]), "binary": file_hash(paths["binary"]),
        "installation": file_hash(paths["anvil_data"] / "installation.json"),
    }
    for command, wrapper in (
        (["upgrade", "DRY_RUN=1"], wrapper_v1),
        (["migrate-runtime", "OPENCODE_MAJOR=2", "DRY_RUN=1"], wrapper_v2),
    ):
        env = env_for(paths, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), DRY_RUN="1")
        proc = run(["/usr/bin/make", "--no-print-directory", *command], env)
        after = {
            "config": tree_hash(paths["config"]), "data": tree_hash(paths["data_opencode"]),
            "state": tree_hash(paths["state_opencode"]), "binary": file_hash(paths["binary"]),
            "installation": file_hash(paths["anvil_data"] / "installation.json"),
        }
        check(after == before, f"dry-run {command[0]} changed live user state")
        check(not (paths["anvil_data"] / "backups").exists(), f"dry-run {command[0]} created a backup")
        check("Dry run complete" in proc.stdout and "Candidate" in proc.stdout, f"dry-run {command[0]} did not report its staged plan")
        check("Policy default major" in proc.stdout and "Current runtime capabilities" in proc.stdout, f"dry-run {command[0]} omitted runtime policy or current capabilities")
        check("Target runtime profile capabilities" in proc.stdout and "search_backend" in proc.stdout, f"dry-run {command[0]} omitted target capability fallbacks")
    print("PASS upgrade and explicit runtime migration dry-runs rehearse without live changes or backups")


def main() -> int:
    wrapper_dir = TEST_ROOT / "candidate-wrapper"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper_v2 = wrapper_dir / "opencode-v2-test"
    wrapper_v2.write_text(
        "#!/usr/bin/env bash\n"
        f"if [[ \"${{1:-}}\" == --version ]]; then printf 'opencode v{VERSION_V2}\\n'; "
        f"else exec {shlex.quote(str(CANDIDATE_V2))} \"$@\"; fi\n",
        encoding="utf-8",
    )
    wrapper_v2.chmod(0o755)
    wrapper_v1 = wrapper_dir / "opencode-v1-test"
    wrapper_v1.write_text(
        "#!/usr/bin/env bash\n"
        f"if [[ \"${{1:-}}\" == --version ]]; then printf 'opencode v{VERSION_V1}\\n'; "
        f"else exec {shlex.quote(str(CANDIDATE_V1))} \"$@\"; fi\n",
        encoding="utf-8",
    )
    wrapper_v1.chmod(0o755)

    with tempfile.TemporaryDirectory(prefix="anvil-provider-migration-", dir=TEST_ROOT) as name:
        provider_migration_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-first-install-stats-", dir=TEST_ROOT) as name:
        temp = pathlib.Path(name)
        home = temp / "home"
        tools = temp / "tools"
        tools.mkdir()
        for command in ("bash", "dirname", "env", "python3"):
            source = shutil.which(command)
            check(source is not None, f"test requires {command}")
            (tools / command).symlink_to(source)
        first_install_env = {
            "PATH": str(tools),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(temp / "xdg-config"),
            "XDG_DATA_HOME": str(temp / "xdg-data"),
            "XDG_STATE_HOME": str(temp / "xdg-state"),
            "SHELL": "/bin/bash",
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
        }
        first_stats = run(["/usr/bin/make", "--no-print-directory", "stats"], first_install_env)
        check("make reforge" in first_stats.stderr, "first-use stats did not direct the user to reforge")
        check("WARN" in first_stats.stderr and "ERROR" not in first_stats.stderr, "first-use stats did not exit with an informational notice")
        first_doctor = run(["/usr/bin/make", "--no-print-directory", "doctor"], first_install_env)
        check("Status: NOT INSTALLED" in first_doctor.stdout and "Approved policy major  1" in first_doctor.stdout, "first-use doctor did not report the approved runtime policy informatively")
        check("Version documentation  valid" in first_doctor.stdout, "first-use doctor omitted release documentation health")
        print("PASS make stats gives first-install guidance when OpenCode is absent")
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-rehearsal-", dir=TEST_ROOT) as name:
        rehearsal_test(pathlib.Path(name), wrapper_v2)
    with tempfile.TemporaryDirectory(prefix="anvil-reforge-idempotent-", dir=TEST_ROOT) as name:
        reforge_test(pathlib.Path(name), wrapper_v1)
    with tempfile.TemporaryDirectory(prefix="anvil-reforge-preserves-v2-", dir=TEST_ROOT) as name:
        reforge_preserves_v2_test(pathlib.Path(name), wrapper_v2)
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-v1-preserves-runtime-", dir=TEST_ROOT) as name:
        upgrade_preserves_v1_test(pathlib.Path(name), wrapper_v1)
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-v2-preserves-runtime-", dir=TEST_ROOT) as name:
        upgrade_preserves_v2_test(pathlib.Path(name), wrapper_v2)
    with tempfile.TemporaryDirectory(prefix="anvil-migration-dry-run-", dir=TEST_ROOT) as name:
        dry_run_test(pathlib.Path(name), wrapper_v1, wrapper_v2)
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-candidate-failure-", dir=TEST_ROOT) as name:
        upgrade_test(pathlib.Path(name), wrapper_v2, fail="ANVIL_TEST_FAIL_CANDIDATE_VALIDATION")
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-early-failure-", dir=TEST_ROOT) as name:
        upgrade_test(pathlib.Path(name), wrapper_v2, fail="ANVIL_TEST_FAIL_REHEARSAL")
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-backup-create-failure-", dir=TEST_ROOT) as name:
        upgrade_test(pathlib.Path(name), wrapper_v2, fail="ANVIL_TEST_FAIL_BACKUP")
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-backup-failure-", dir=TEST_ROOT) as name:
        upgrade_test(pathlib.Path(name), wrapper_v2, fail="ANVIL_TEST_FAIL_AFTER_BACKUP")
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-config-failure-", dir=TEST_ROOT) as name:
        upgrade_test(pathlib.Path(name), wrapper_v2, fail="ANVIL_TEST_FAIL_AFTER_CONFIG")
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-doctor-failure-", dir=TEST_ROOT) as name:
        upgrade_test(pathlib.Path(name), wrapper_v2, fail="ANVIL_TEST_FAIL_DOCTOR")
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-success-", dir=TEST_ROOT) as name:
        upgrade_test(pathlib.Path(name), wrapper_v2)
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-external-v1-binary-", dir=TEST_ROOT) as name:
        upgrade_test(pathlib.Path(name), wrapper_v2, external_binary=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
