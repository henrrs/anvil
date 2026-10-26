#!/usr/bin/env python3
"""Isolated V1/V2 lifecycle and failure-recovery integration tests."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import time
import tempfile
from typing import Any
from unittest import mock


ROOT = pathlib.Path(sys.argv[1]).resolve()
ANVIL_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
sys.path.insert(0, str(ROOT / "scripts"))
import lifecycle_state  # noqa: E402
from semver import compare as compare_versions, parse as parse_version, supported_migration  # noqa: E402
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


def filesystem_snapshot(root: pathlib.Path) -> dict[str, tuple[Any, ...]]:
    """Capture file contents, permissions, directories, and symlink targets."""
    result: dict[str, tuple[Any, ...]] = {}

    def visit(path: pathlib.Path, relative: str) -> None:
        info = path.lstat()
        mode = info.st_mode
        if path.is_symlink():
            result[relative] = ("symlink", mode & 0o777, os.readlink(path))
        elif path.is_dir():
            result[relative] = ("directory", mode & 0o777)
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                child_relative = child.name if relative == "." else f"{relative}/{child.name}"
                visit(child, child_relative)
        elif path.is_file():
            result[relative] = ("file", mode & 0o777, info.st_size, file_hash(path))
        else:
            result[relative] = ("other", mode & 0o777)

    if root.exists() or root.is_symlink():
        visit(root, ".")
    return result


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
    paths = {
        "home": home, "config_home": config_home, "data_home": data_home,
        "state_home": state_home, "config": config, "install_bin": install_bin,
        "data_opencode": data_opencode, "anvil_data": anvil_data,
        "memory": anvil_data / "memory", "state_opencode": state_opencode,
    }
    generated = temp / "generated-v1-config"
    run(["bash", "-c", "source \"$ANVIL_ROOT/scripts/lib/common.sh\"; "
         "source \"$ANVIL_ROOT/scripts/lib/install.sh\"; anvil_build_config \"$1\" '' no 1",
         "_", str(generated)], env_for(paths, ANVIL_ROOT=str(ROOT)))
    shutil.rmtree(config)
    shutil.copytree(generated, config)
    shutil.rmtree(generated)
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
    (config / "cli.json").write_text('{"theme":"fixture"}\n', encoding="utf-8")
    (config / "tui.json").write_text('{"tabs":{"mode":"off"}}\n', encoding="utf-8")
    (config / "commands" / "user-command.md").write_text("legacy user command\n", encoding="utf-8")
    (config / "scripts" / "user-helper.py").write_text("# user-owned helper\n", encoding="utf-8")
    downgrade_to_legacy_profile(paths, "2.6.1")
    (home / ".bashrc").write_text("# fixture shell startup\n", encoding="utf-8")
    (data_opencode / "auth.json").write_text('{"fixture":true}\n', encoding="utf-8")
    (state_opencode / "state.fixture").write_text("opaque OpenCode state fixture\n", encoding="utf-8")
    shutil.copy2(V1_MEMORY, anvil_data / "memory" / "company" / V1_MEMORY.name)
    write_json(anvil_data / "installation.json", {
        "schema_version": 2, "anvil_version": "2.6.1", "version": "1.19.0",
        "runtime_major": 1, "binary": str(install_bin / "opencode"), "fixture": True,
    })
    fake_binary = install_bin / "opencode"
    fake_binary.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == --version ]]; then printf 'opencode v1.19.0\\n'; "
        "elif [[ \"${1:-}\" == --hold ]]; then "
        "if [[ \"${ANVIL_TEST_IGNORE_TERM:-0}\" == 1 ]]; then trap '' TERM; "
        "else trap '[[ -n \"${ANVIL_TEST_TERM_MARKER:-}\" ]] && : > \"$ANVIL_TEST_TERM_MARKER\"; exit 0' TERM; fi; "
        "[[ -n \"${ANVIL_TEST_READY:-}\" ]] && : > \"$ANVIL_TEST_READY\"; "
        "while :; do read -t 0.1 _ || true; done; "
        "elif [[ \"${1:-}\" == --run-upgrade-child ]]; then /usr/bin/make --no-print-directory -C \"${ANVIL_TEST_REPO}\" upgrade; exit $?; "
        f"else exec {shlex.quote(str(FIXTURES / 'bin' / 'opencode-v1'))} \"$@\"; fi\n",
        encoding="utf-8",
    )
    fake_binary.chmod(0o755)
    paths["binary"] = fake_binary
    return paths


def downgrade_to_legacy_profile(paths: dict[str, pathlib.Path], version: str) -> None:
    config_dir = paths["config"]
    config_path = config_dir / "opencode.jsonc"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if isinstance(config.get("agent"), dict):
        config["agent"]["anvil"]["permission"]["skill"].pop("anvil-communication", None)
    elif isinstance(config.get("agents"), dict):
        config["agents"]["anvil"]["permissions"] = [
            rule for rule in config["agents"]["anvil"]["permissions"]
            if not (rule.get("action") == "skill" and rule.get("resource") == "anvil-communication")
        ]
    write_json(config_path, config)
    for path in (config_dir / "skills" / "anvil-communication", config_dir / "scripts" / "communication"):
        shutil.rmtree(path, ignore_errors=True)
    for path in (config_dir / "commands" / "review.md", config_dir / "scripts" / "artifacts.py",
                 config_dir / ".anvil-managed.json"):
        path.unlink(missing_ok=True)
    installation_path = paths["anvil_data"] / "installation.json"
    try:
        installation = json.loads(installation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        installation = {}
    installation["anvil_version"] = version
    installation.pop("managed_config_manifest_sha256", None)
    write_json(installation_path, installation)


def promote_fixture_to_current_anvil(paths: dict[str, pathlib.Path], temp: pathlib.Path) -> None:
    """Prepare a current managed Anvil fixture for runtime-major migration tests."""
    generated = temp / "current-anvil-config"
    run(
        ["bash", "-c", "source \"$ANVIL_ROOT/scripts/lib/common.sh\"; "
         "source \"$ANVIL_ROOT/scripts/lib/install.sh\"; anvil_build_config \"$1\" \"$2\" yes 1",
         "_", str(generated), str(paths["config"])],
        env_for(paths, ANVIL_ROOT=str(ROOT)),
    )
    shutil.rmtree(paths["config"])
    shutil.copytree(generated, paths["config"])
    shutil.rmtree(generated)
    installation_path = paths["anvil_data"] / "installation.json"
    installation = json.loads(installation_path.read_text(encoding="utf-8"))
    installation["schema_version"] = 3
    installation["anvil_version"] = ANVIL_VERSION
    installation["managed_config_manifest_sha256"] = file_hash(paths["config"] / ".anvil-managed.json")
    write_json(installation_path, installation)


def fresh_environment(temp: pathlib.Path) -> dict[str, str]:
    home = temp / "home"
    config_home = temp / "xdg-config"
    data_home = temp / "xdg-data"
    state_home = temp / "xdg-state"
    cache_home = temp / "xdg-cache"
    for path in (home, config_home, data_home, state_home, cache_home):
        path.mkdir(parents=True, exist_ok=True)
    python_dir = str(pathlib.Path(sys.executable).parent)
    return {
        "PATH": python_dir + os.pathsep + "/usr/bin:/bin",
        "HOME": str(home), "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(data_home), "XDG_STATE_HOME": str(state_home),
        "XDG_CACHE_HOME": str(cache_home), "PYTHONNOUSERSITE": "1",
        "SHELL": "/bin/bash", "TMPDIR": "/tmp", "LANG": "C.UTF-8",
        "ANVIL_DATABRICKS_CLI": str(FIXTURES / "bin" / "databricks"),
        "ANVIL_DATABRICKS_SCENARIO": "valid", "ANVIL_DOCTOR_LOCAL": "1",
    }


def assert_human_public_result(proc: subprocess.CompletedProcess[str], command: str) -> str:
    output = proc.stdout + proc.stderr
    check("Traceback" not in output and "FileNotFoundError" not in output
          and "json.decoder" not in output,
          f"{command} exposed an internal exception or traceback: {output[-2000:]}")
    check(not any(line.lstrip().startswith(("{", "[")) for line in output.splitlines()),
          f"{command} emitted raw JSON in its normal human output")
    return output


def fresh_machine_command_contract_test(temp: pathlib.Path, wrapper_v1: pathlib.Path) -> None:
    env = fresh_environment(temp)
    offline = offline_env({
        "home": pathlib.Path(env["HOME"]),
        "config_home": pathlib.Path(env["XDG_CONFIG_HOME"]),
        "data_home": pathlib.Path(env["XDG_DATA_HOME"]),
        "state_home": pathlib.Path(env["XDG_STATE_HOME"]),
        "install_bin": pathlib.Path(env["HOME"]) / ".opencode" / "bin",
    }, temp, **{key: value for key, value in env.items()
                if key not in {"PATH", "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "SHELL", "TMPDIR", "LANG"}})
    offline.update(env)
    offline["PYTHONPATH"] = str(ROOT / "tests" / "fixtures" / "network-denied")
    preinstall = [
        (("help",), 0), (("inspect",), 0), (("doctor",), 0),
        (("capabilities",), 0), (("stats",), 0),
        (("upgrade", "DRY_RUN=1"), 2), (("upgrade",), 2), (("rollback",), 2),
        (("update-runtime",), 2), (("migrate-runtime", "OPENCODE_MAJOR=2"), 2),
        (("databricks-setup", "DRY_RUN=1"), 0), (("databricks-setup",), 2),
    ]
    outputs: dict[str, str] = {}
    for args, expected in preinstall:
        proc = run(["/usr/bin/make", "--no-print-directory", *args], offline, expected=expected)
        outputs[" ".join(args)] = assert_human_public_result(proc, "make " + " ".join(args))
    check("Status                NOT_INSTALLED" in outputs["inspect"],
          "fresh repository inspect did not report NOT_INSTALLED")
    check("make reforge" in outputs["upgrade"],
          "pre-install Anvil upgrade did not explain the reforge prerequisite")
    check("No Anvil rollback snapshot" in outputs["rollback"],
          "fresh rollback did not explain the missing snapshot and next action")
    check("workspace URL" in outputs["databricks-setup"].casefold()
          or "interactive terminal" in outputs["databricks-setup"],
          "first-use Databricks setup did not explain its workspace prerequisite")
    paths = {
        "home": pathlib.Path(offline["HOME"]),
        "config": pathlib.Path(offline["XDG_CONFIG_HOME"]) / "opencode",
        "record": pathlib.Path(offline["XDG_DATA_HOME"]) / "anvil" / "installation.json",
        "binary": pathlib.Path(offline["HOME"]) / ".opencode" / "bin" / "opencode",
    }
    check(not paths["config"].exists() and not paths["record"].exists() and not paths["binary"].exists(),
          "pre-install inventory or blocked commands changed managed Anvil state")

    managed_path = str(pathlib.Path(offline["HOME"]) / ".opencode" / "bin")
    bootstrap_env = dict(offline, PATH=managed_path + os.pathsep + offline["PATH"],
                         ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper_v1),
                         ANVIL_YES="1", ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    bootstrapped = run(["/usr/bin/make", "--no-print-directory", "reforge"], bootstrap_env)
    assert_human_public_result(bootstrapped, "make reforge")
    check("Status: HEALTHY" in bootstrapped.stdout,
          "fresh-machine make reforge did not pass its postflight doctor")
    check(lifecycle_state_for_env(bootstrap_env) == "READY",
          "first-use reforge did not produce READY lifecycle state")

    postinstall = [
        (("inspect",), 0), (("doctor",), 2), (("capabilities",), 0),
        (("stats",), 0), (("upgrade", "DRY_RUN=1"), 0),
        (("update-runtime",), 2), (("migrate-runtime", "OPENCODE_MAJOR=2"), 2),
        (("databricks-setup", "DRY_RUN=1"), 0), (("databricks-setup",), 2),
    ]
    after_failures = tree_hash(pathlib.Path(bootstrap_env["XDG_DATA_HOME"]) / "anvil")
    for args, expected in postinstall:
        proc = run(["/usr/bin/make", "--no-print-directory", *args], offline, expected=expected)
        output = assert_human_public_result(proc, "make " + " ".join(args))
        if args[0] == "doctor":
            check("not in this session's PATH" in output and "Status: WARNING" in output,
                  "doctor did not report a usable runtime missing from this shell's PATH: "
                  f"exit={proc.returncode}, output={output[-2500:]}")
        if args[0] == "update-runtime" or args[0] == "migrate-runtime":
            check("release" in output.casefold() or "network" in output.casefold()
                  or "could not" in output.casefold(),
                  f"offline runtime operation lacked a useful blocker: {output[-1000:]}")
    check(tree_hash(pathlib.Path(bootstrap_env["XDG_DATA_HOME"]) / "anvil") == after_failures,
          "blocked offline runtime operations changed Anvil state")

    memory = pathlib.Path(bootstrap_env["XDG_DATA_HOME"]) / "anvil" / "memory"
    shutil.rmtree(memory)
    degraded = run(["/usr/bin/make", "--no-print-directory", "inspect"], offline)
    check("Status                DEGRADED" in degraded.stdout,
          "missing memory directory was not classified as DEGRADED")
    memory.mkdir(parents=True)
    successful_upgrade = run(["/usr/bin/make", "--no-print-directory", "upgrade"],
                             dict(bootstrap_env, ANVIL_DOCTOR_LOCAL="1"))
    assert_human_public_result(successful_upgrade, "make upgrade")
    rollback = run(["/usr/bin/make", "--no-print-directory", "rollback"], offline)
    assert_human_public_result(rollback, "make rollback")
    check("Rollback completed" in rollback.stderr,
          "post-install rollback did not restore a verified snapshot")
    check(lifecycle_state_for_env(offline) == "READY",
          "rollback did not leave the prior Anvil installation ready")
    print("PASS fresh HOME/XDG public command matrices, reforge journey, offline blockers, and post-install rollback")


def lifecycle_state_for_env(env: dict[str, str]) -> str:
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "lifecycle_state.py"), "inspect", "--format", "json"],
                          cwd=ROOT, env=env, text=True, capture_output=True, timeout=20, check=False)
    check(proc.returncode == 0, f"lifecycle state inspection failed: {proc.stderr}")
    return json.loads(proc.stdout)["lifecycle"]


def partial_lifecycle_matrix_test(temp: pathlib.Path, wrapper_v1: pathlib.Path) -> None:
    config_only = fresh_environment(temp / "config-only")
    config_path = pathlib.Path(config_only["XDG_CONFIG_HOME"]) / "opencode"
    config_path.mkdir(parents=True)
    shutil.copy2(V1_CONFIG, config_path / "opencode.jsonc")
    inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], config_only)
    check("PARTIALLY_INSTALLED" in inspect.stdout, "config-only environment was not classified as partial")

    runtime_only = fresh_environment(temp / "runtime-only")
    binary = pathlib.Path(runtime_only["HOME"]) / ".opencode" / "bin" / "opencode"
    binary.parent.mkdir(parents=True)
    binary.symlink_to(wrapper_v1)
    inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], runtime_only)
    check("PARTIALLY_INSTALLED" in inspect.stdout, "runtime-only environment was not classified as partial")
    doctor = run(["/usr/bin/make", "--no-print-directory", "doctor"], runtime_only, expected=2)
    check("managed Anvil config is missing" in doctor.stderr,
          "runtime-only doctor did not explain the missing Anvil config")

    corrupt = fresh_environment(temp / "corrupt-config")
    corrupt_config = pathlib.Path(corrupt["XDG_CONFIG_HOME"]) / "opencode"
    corrupt_config.mkdir(parents=True)
    (corrupt_config / "opencode.jsonc").write_text("{ invalid", encoding="utf-8")
    doctor = run(["/usr/bin/make", "--no-print-directory", "doctor"], corrupt, expected=2)
    check("CORRUPTED" in doctor.stdout and "BROKEN" in doctor.stdout,
          "corrupted generated config was not classified by doctor")

    non_executable = fresh_environment(temp / "non-executable-runtime")
    binary = pathlib.Path(non_executable["HOME"]) / ".opencode" / "bin" / "opencode"
    binary.parent.mkdir(parents=True)
    shutil.copy2(wrapper_v1, binary)
    binary.chmod(0o644)
    inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], non_executable)
    check("CORRUPTED" in inspect.stdout, "non-executable managed runtime was not classified as corrupted")

    invalid_repo = temp / "invalid-repository"
    invalid_repo.mkdir()
    (invalid_repo / "VERSION").write_text("invalid\n", encoding="utf-8")
    invalid_env = fresh_environment(temp / "invalid-version")
    with mock.patch.object(lifecycle_state, "ROOT", invalid_repo), \
            mock.patch.object(lifecycle_state.runtime_state, "discover", return_value={"runtime": None}), \
            mock.patch.dict(os.environ, invalid_env, clear=True):
        check(lifecycle_state.evaluate()["lifecycle"] == "CORRUPTED",
              "invalid repository VERSION was not classified as corrupted")
    print("PASS config-only, runtime-only, corrupted config, non-executable runtime, and invalid VERSION states")


def lifecycle_version_order_test() -> None:
    check(parse_version("2.10.0") == (2, 10, 0), "semantic version parser did not retain numeric minor ordering")
    check(compare_versions("2.10.0", "2.9.9") == 1, "semantic version ordering compared minor releases lexically")
    check(compare_versions("2.08.0", "2.8.0") is None, "semantic version parser accepted a non-canonical leading zero")
    check(supported_migration("2.6.1", "2.8.0"), "two-minor source window was rejected")
    check(not supported_migration("2.5.9", "2.8.0"), "source outside the two-minor window was accepted")
    check(not supported_migration("2.9.0", "2.8.0"), "a newer installed release was treated as migratable")
    print("PASS semantic release ordering, supported source window, and downgrade rejection")


def config_ownership_transition_test(temp: pathlib.Path) -> None:
    paths = fixture(temp / "preserve")
    source_config_path = paths["config"] / "opencode.jsonc"
    source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
    source_config["agent"]["retired-source-agent"] = {"disable": True}
    source_config["agent"]["anvil"]["permission"]["skill"]["company-private"] = "allow"
    write_json(source_config_path, source_config)
    custom_skill = paths["config"] / "skills/company-private/SKILL.md"
    custom_skill.parent.mkdir(parents=True)
    custom_skill.write_text("---\nname: company-private\ndescription: Company skill fixture\n---\n# Company private skill\n",
                            encoding="utf-8")
    changed_nested = paths["config"] / "skills/anvil-databricks/references/authentication.md"
    check(changed_nested.is_file(), "legacy fixture lacks the nested skill file evolution regression target")
    changed_nested.unlink()
    env = offline_env(paths, temp / "preserve", ANVIL_YES="1", ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    source_inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], env)
    check("Status                MIGRATION_REQUIRED" in source_inspect.stdout,
          "a valid source profile with changed nested skill files and an older agent inventory was called corrupted")
    before_dry = tree_hash(paths["config"])
    dry = run(["/usr/bin/make", "--no-print-directory", "upgrade", "DRY_RUN=1"], env)
    check(tree_hash(paths["config"]) == before_dry, "upgrade dry run modified the live configuration")
    check("preserved user" in dry.stdout and "scripts/user-helper.py" in dry.stdout,
          "dry-run migration plan omitted preserved user-owned files")
    run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    manifest = json.loads((paths["config"] / ".anvil-managed.json").read_text(encoding="utf-8"))
    check(set(manifest.get("config", {}).get("managed_agents", [])) ==
          {"build", "plan", "general", "explore", "anvil"},
          "managed config manifest did not record ownership of the shipped inline agent set")
    installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    check((paths["config"] / "commands/user-command.md").read_text(encoding="utf-8") == "legacy user command\n",
          "Anvil upgrade overwrote or lost a user-owned command")
    check((paths["config"] / "scripts/user-helper.py").read_text(encoding="utf-8") == "# user-owned helper\n",
          "Anvil upgrade overwrote or lost a user-owned helper script")
    check(custom_skill.read_text(encoding="utf-8").endswith("# Company private skill\n"),
          "Anvil upgrade overwrote or lost a user-owned custom skill")
    upgraded_config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    check(upgraded_config["agent"]["anvil"]["permission"]["skill"].get("company-private") == "allow",
          "Anvil upgrade did not preserve the user's custom skill permission")
    check(upgraded_config["agent"].get("retired-source-agent", {}).get("disable") is True,
          "Anvil upgrade dropped a user-owned disabled inline agent")
    check(changed_nested.is_file(), "Anvil upgrade did not add the target version's updated nested skill file")
    check("commands/user-command.md" not in manifest["files"] and "scripts/user-helper.py" not in manifest["files"],
          "Anvil incorrectly claimed ownership of preserved user files")
    check("skills/company-private/SKILL.md" not in manifest["files"],
          "Anvil incorrectly claimed ownership of the preserved custom skill")
    check(installation["managed_config_manifest_sha256"] == file_hash(paths["config"] / ".anvil-managed.json"),
          "installation metadata did not bind the managed-file manifest checksum")
    (paths["config"] / "scripts/user-helper.py").write_text("# user changed this after installation\n", encoding="utf-8")
    after_edit = tree_hash(paths["config"])
    second_dry = run(["/usr/bin/make", "--no-print-directory", "upgrade", "DRY_RUN=1"], env)
    check(tree_hash(paths["config"]) == after_edit, "dry run changed a modified user-owned extra")
    check("scripts/user-helper.py" in second_dry.stdout,
          "later migration stopped preserving a modified user-owned extra")

    collision = fixture(temp / "collision")
    collision_config_path = collision["config"] / "opencode.jsonc"
    collision_config = json.loads(collision_config_path.read_text(encoding="utf-8"))
    collision_config["agent"]["anvil"]["permission"]["skill"]["anvil-communication"] = "allow"
    write_json(collision_config_path, collision_config)
    collision_path = collision["config"] / "skills/anvil-communication/SKILL.md"
    collision_path.parent.mkdir(parents=True)
    collision_path.write_text("user-owned skill collision\n", encoding="utf-8")
    collision_before = tree_hash(collision["config"])
    collision_env = offline_env(collision, temp / "collision")
    blocked = run(["/usr/bin/make", "--no-print-directory", "upgrade", "DRY_RUN=1"],
                  collision_env, expected=2)
    check("user-owned files conflict" in blocked.stderr,
          "migration did not stop on a user-owned path that collides with a target Anvil skill")
    check(tree_hash(collision["config"]) == collision_before and not (collision["anvil_data"] / "backups").exists(),
          "path collision changed live state or created a snapshot")
    print("PASS upgrade preserves user-owned extras, binds the manifest, and blocks target-path collisions")


def custom_agent_transition_test(temp: pathlib.Path) -> None:
    env_home = temp / "home with spaces"
    env_data = temp / "data ü"
    env = {"HOME": str(env_home), "XDG_CONFIG_HOME": str(temp / "config home"),
           "XDG_DATA_HOME": str(env_data), "XDG_STATE_HOME": str(temp / "state home"),
           "PATH": os.defpath, "PYTHONUTF8": "1"}
    env_home.mkdir(parents=True)
    env_data.mkdir(parents=True)
    for source_major in (1, 2):
        for target_major in (1, 2):
            case = temp / f"v{source_major}-to-v{target_major} with spaces"
            prior = case / "prior"
            target = case / "target"
            prior.mkdir(parents=True)
            template = ROOT / ("config/runtimes/opencode-v1.jsonc" if source_major == 1
                               else "config/opencode.jsonc")
            config = json.loads(template.read_text(encoding="utf-8"))
            agents_key = "agent" if source_major == 1 else "agents"
            disabled_key = "disable" if source_major == 1 else "disabled"
            config[agents_key]["company-audit-agent"] = {
                disabled_key: True, "description": "Company-owned disabled agent",
                "prompt": "Keep this user configuration during Anvil rebuilds.",
            }
            retired_name = "retired-anvil-agent"
            config[agents_key][retired_name] = {
                disabled_key: True, "description": "Managed by the source Anvil release",
            }
            (prior / "opencode.jsonc").write_text(json.dumps(config), encoding="utf-8")
            (prior / ".anvil-managed.json").write_text(json.dumps({
                "schema_version": 1, "anvil_version": ANVIL_VERSION,
                "files": {"opencode.jsonc": None},
                "config": {"managed_agents": sorted(set(config[agents_key]) - {"company-audit-agent"})},
            }), encoding="utf-8")
            source_audit = "audit-v1-compatible" if source_major == 1 else "audit-compatible"
            target_audit = "audit-v1" if target_major == 1 else "audit"
            run([sys.executable, str(ROOT / "scripts/configure.py"), source_audit,
                 str(prior / "opencode.jsonc")], env)
            run([sys.executable, str(ROOT / "scripts/configure.py"), "build", "--source", str(ROOT / "config"),
                 "--destination", str(target), "--prior-config-dir", str(prior), "--major", str(target_major)], env)
            target_config_path = target / "opencode.jsonc"
            run([sys.executable, str(ROOT / "scripts/configure.py"), target_audit,
                 str(target_config_path)], env)
            result = json.loads(target_config_path.read_text(encoding="utf-8"))
            agents = result["agent" if target_major == 1 else "agents"]
            custom = agents.get("company-audit-agent", {})
            check(custom.get("disable" if target_major == 1 else "disabled") is True,
                  f"disabled custom agent was lost converting OpenCode {source_major} to {target_major}")
            check(retired_name not in agents,
                  "a source-manifest-owned agent removed by the target release was retained as user-owned")
            check("disable" not in custom or target_major == 1,
                  "OpenCode V2 output retained the legacy disable property")
            check("disabled" not in custom or target_major == 2,
                  "OpenCode V1 output retained the native disabled property")
            if target_major == 2:
                expected_knowledge = str(env_data / "anvil" / "knowledge")
                check(result.get("references", {}).get("anvil-knowledge", {}).get("path") == expected_knowledge,
                      "config generation did not honor the isolated Unicode XDG data path")
    print("PASS disabled user agents survive config rebuilds and V1/V2 adapter transitions")


def filesystem_and_working_directory_test(temp: pathlib.Path) -> None:
    machine_root = temp / "machine with spaces ü"
    paths = fixture(machine_root)
    env = offline_env(paths, temp, ANVIL_YES="1", ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    external_cwd = temp / "external working directory"
    external_cwd.mkdir()
    observed_roots = [paths["home"], paths["config_home"], paths["data_home"], paths["state_home"]]
    before_inspect = {str(root): filesystem_snapshot(root) for root in observed_roots}
    runtime_before = file_hash(paths["binary"])

    inspect = run(["/usr/bin/make", "--no-print-directory", "-C", str(ROOT), "inspect"],
                  env, cwd=external_cwd)
    check("MIGRATION_REQUIRED" in inspect.stdout,
          "make -C from an external cwd did not inspect the Anvil state under spaced/Unicode XDG paths")
    check(before_inspect == {str(root): filesystem_snapshot(root) for root in observed_roots},
          "read-only make inspect changed isolated HOME or XDG state")
    before = {
        "home": filesystem_snapshot(paths["home"]),
        "config": filesystem_snapshot(paths["config_home"]),
        "data": filesystem_snapshot(paths["data_home"]),
        "state": filesystem_snapshot(paths["state_home"]),
    }
    dry = run(["/usr/bin/make", "--no-print-directory", "-C", str(ROOT), "upgrade", "DRY_RUN=1"],
              env, cwd=external_cwd)
    check("No changes performed" in dry.stdout,
          "external-cwd dry run did not report its no-mutation result")
    check(before == {
        "home": filesystem_snapshot(paths["home"]),
        "config": filesystem_snapshot(paths["config_home"]),
        "data": filesystem_snapshot(paths["data_home"]),
        "state": filesystem_snapshot(paths["state_home"]),
    }, "dry run changed managed state with spaced/Unicode HOME/XDG paths")

    run(["/usr/bin/make", "--no-print-directory", "-C", str(ROOT), "upgrade"], env, cwd=external_cwd)
    check(lifecycle_state_for_env(env) == "READY",
          "upgrade from an external cwd did not complete with spaced/Unicode HOME/XDG paths")
    check(file_hash(paths["binary"]) == runtime_before,
          "Anvil upgrade changed the runtime when HOME/XDG paths contained spaces and Unicode")
    reforge = run(["/usr/bin/make", "--no-print-directory", "-C", str(ROOT), "reforge"],
                  dict(env, ANVIL_YES="1"), cwd=external_cwd)
    check("Status: HEALTHY" in reforge.stdout,
          "make -C reforge did not reuse the runtime under a spaced/Unicode HOME path")
    check(lifecycle_state_for_env(env) == "READY" and file_hash(paths["binary"]) == runtime_before,
          "reforge from an external cwd did not preserve the runtime and produce READY state")

    updated_candidate = temp / "OpenCode update candidate ü"
    updated_candidate.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == --version ]]; then printf 'opencode v1.20.0\\n'; "
        f"else exec {shlex.quote(str(FIXTURES / 'bin' / 'opencode-v1'))} \"$@\"; fi\n",
        encoding="utf-8",
    )
    updated_candidate.chmod(0o755)
    config_before_runtime_update = tree_hash(paths["config"])
    runtime_update_env = dict(env, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(updated_candidate),
                             ANVIL_YES="1")
    run(["/usr/bin/make", "--no-print-directory", "-C", str(ROOT), "update-runtime"],
        runtime_update_env, cwd=external_cwd)
    updated_installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    check(updated_installation["version"] == "1.20.0" and updated_installation["binary"] == str(paths["binary"]),
          "runtime update did not rediscover and install through the spaced managed executable path")
    check(updated_installation["anvil_version"] == ANVIL_VERSION and tree_hash(paths["config"]) == config_before_runtime_update,
          "runtime update changed the Anvil release/config while exercising spaced paths")
    check(lifecycle_state_for_env(runtime_update_env) == "READY",
          "runtime update from an external cwd with spaced paths did not finish READY")
    assert_no_external_network(temp)
    print("PASS make -C lifecycle dry-run, upgrade, reforge and runtime update work with spaced Unicode HOME/XDG paths")


def readonly_config_parent_preflight_test(temp: pathlib.Path) -> None:
    paths = fixture(temp / "machine")
    env = offline_env(paths, temp, ANVIL_YES="1", ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    before_config = tree_hash(paths["config"])
    before_data = tree_hash(paths["anvil_data"])
    runtime = start_runtime(paths, marker=temp / "runtime-ready")
    paths["config_home"].chmod(0o555)
    try:
        dry = run(["/usr/bin/make", "--no-print-directory", "upgrade", "DRY_RUN=1"], env, expected=2)
        check("configuration parent is not writable" in dry.stdout.casefold(),
              "read-only config parent was not reported as an upgrade preflight blocker")
        check(tree_hash(paths["config"]) == before_config and tree_hash(paths["anvil_data"]) == before_data,
              "blocked dry-run changed Anvil configuration or lifecycle state")
        check(runtime.poll() is None, "read-only config preflight stopped the active OpenCode runtime")

        blocked = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env, expected=2)
        check("configuration parent is not writable" in blocked.stdout.casefold(),
              "real upgrade did not stop at the read-only config preflight")
        check(tree_hash(paths["config"]) == before_config and tree_hash(paths["anvil_data"]) == before_data,
              "read-only config preflight created a backup/journal or changed managed state")
        check(runtime.poll() is None, "blocked real upgrade stopped OpenCode before the writable-path check")
    finally:
        paths["config_home"].chmod(0o700)
        runtime.terminate()
        runtime.wait(timeout=3)
    print("PASS read-only config parent blocks before backup, transaction, or runtime shutdown")


def concurrent_lifecycle_test(temp: pathlib.Path) -> None:
    paths = fixture(temp / "machine")
    env = offline_env(paths, temp, ANVIL_YES="1", ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    runtime_before = file_hash(paths["binary"])
    command = ["/usr/bin/make", "--no-print-directory", "-C", str(ROOT), "upgrade"]
    processes = [subprocess.Popen(command, cwd=temp, env=env, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(2)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=180)
        check(process.returncode in {0, 2},
              f"concurrent lifecycle command returned an unexpected exit code: {process.returncode}\n{stderr[-2000:]}")
        if process.returncode != 0:
            check("another lifecycle transaction" in stderr.casefold(),
                  "concurrent lifecycle loser did not report the active transaction blocker")
    check(lifecycle_state_for_env(env) == "READY",
          "overlapping Anvil upgrades left a non-ready installation")
    check(not (paths["anvil_data"] / "lifecycle-transaction.json").exists(),
          "overlapping Anvil upgrades left an orphaned transaction journal")
    check(file_hash(paths["binary"]) == runtime_before,
          "Anvil upgrade changed the OpenCode runtime during a concurrent invocation")
    backup_root = paths["anvil_data"] / "backups"
    backups = sorted(item for item in backup_root.iterdir() if item.is_dir())
    check(bool(backups), "concurrent upgrade did not produce a rollback snapshot")
    for backup in backups:
        verify = subprocess.run([sys.executable, str(ROOT / "scripts" / "state.py"), "verify", str(backup)],
                                text=True, capture_output=True, timeout=20)
        check(verify.returncode == 0, f"concurrent lifecycle left an invalid snapshot: {backup.name}")
    print("PASS overlapping lifecycle invocations leave coherent state and verified snapshots")


def interrupted_transaction_recovery_test(temp: pathlib.Path) -> None:
    paths = fixture(temp)
    env = offline_env(paths, temp, ANVIL_YES="1", ANVIL_UPGRADE_COUNTDOWN_SECONDS="0",
                      ANVIL_TEST_KILL_AFTER_CONFIG_RENAME="1")
    crashed = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env, expected=2)
    check("Killed" in crashed.stderr or "137" in crashed.stderr,
          "failure injection did not terminate the upgrade process at the config rename boundary")
    inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], env)
    check("Status                RECOVERY_REQUIRED" in inspect.stdout,
          "interrupted config activation was not classified as RECOVERY_REQUIRED")
    before_dry = tree_hash(paths["config_home"])
    dry = run(["/usr/bin/make", "--no-print-directory", "upgrade", "DRY_RUN=1"], env, expected=2)
    check("DRY_RUN is read-only" in dry.stderr, "dry run attempted recovery instead of remaining read-only")
    check(tree_hash(paths["config_home"]) == before_dry,
          "dry-run operation modified an interrupted configuration state")
    retry_env = dict(env)
    retry_env.pop("ANVIL_TEST_KILL_AFTER_CONFIG_RENAME", None)
    recovered = run(["/usr/bin/make", "--no-print-directory", "upgrade"], retry_env)
    check("Interrupted operation recovered" in recovered.stderr,
          "retry did not restore the verified snapshot before continuing")
    check(not (paths["anvil_data"] / "lifecycle-transaction.json").exists(),
          "successful retry left a pending lifecycle journal")
    check(not list(paths["config_home"].glob(".anvil-config-stage.*"))
          and not list(paths["config_home"].glob(".anvil-config-previous-*")),
          "recovery left an orphaned config staging directory")
    check(lifecycle_state_for_env(retry_env) == "READY",
          "recovered retry did not finish in READY state")
    print("PASS interrupted config activation is journaled, dry run stays read-only, and retry recovers idempotently")


def managed_file_repair_test(temp: pathlib.Path) -> None:
    paths = fixture(temp)
    env = offline_env(paths, temp, ANVIL_YES="1", ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    managed_script = paths["config"] / "scripts/memory.py"
    managed_script.write_text("# injected managed-file modification\n", encoding="utf-8")
    inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], env)
    check("Status                CORRUPTED" in inspect.stdout,
          "modified manifest-owned script was not diagnosed as corruption")
    reforge = run(["/usr/bin/make", "--no-print-directory", "reforge"],
                  dict(env, ANVIL_YES="1"))
    check("Status: HEALTHY" in reforge.stdout, "reforge could not rebuild a modified manifest-owned file")
    check(managed_script.read_bytes() == (ROOT / "scripts/memory.py").read_bytes(),
          "reforge did not restore the shipped Anvil-owned helper")
    check(lifecycle_state_for_env(env) == "READY", "manifest repair did not restore READY lifecycle state")
    print("PASS reforge repairs a modified managed file while retaining trusted ownership metadata")


def future_install_downgrade_test(temp: pathlib.Path) -> None:
    paths = fixture(temp / "future")
    promote_fixture_to_current_anvil(paths, temp / "future")
    runtime_before = file_hash(paths["binary"])
    installation_path = paths["anvil_data"] / "installation.json"
    installation = json.loads(installation_path.read_text(encoding="utf-8"))
    manifest_path = paths["config"] / ".anvil-managed.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["anvil_version"] = "2.9.0"
    write_json(manifest_path, manifest)
    installation["anvil_version"] = "2.9.0"
    installation["managed_config_manifest_sha256"] = file_hash(manifest_path)
    write_json(installation_path, installation)
    config_before = tree_hash(paths["config"])
    installation_before = file_hash(installation_path)
    env = offline_env(paths, temp / "future")

    inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], env)
    check("Status                UNSUPPORTED" in inspect.stdout,
          "a valid future Anvil install was not classified as an unsupported downgrade")
    upgrade = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env, expected=2)
    check("refusing a downgrade" in upgrade.stderr,
          "Anvil upgrade did not explicitly refuse a future installed version")
    reforge = run(["/usr/bin/make", "--no-print-directory", "reforge"], env, expected=2)
    check("reforge refuses to downgrade" in reforge.stderr,
          "reforge did not explicitly refuse to downgrade a future installed version")
    check(tree_hash(paths["config"]) == config_before and file_hash(paths["binary"]) == runtime_before
          and file_hash(installation_path) == installation_before
          and not (paths["anvil_data"] / "backups").exists(),
          "future-version downgrade attempts changed configuration/runtime or created a snapshot")
    print("PASS a future managed Anvil installation blocks upgrade and reforge downgrades without mutation")


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
        "anvil_version": "2.6.1",
        "version": VERSION_V2,
        "runtime_major": 2,
        "profile": "opencode-v2",
        "binary_path": str(paths["binary"]),
        "migration": {"status": "completed"},
    })
    downgrade_to_legacy_profile(paths, "2.6.1")


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
        "ANVIL_VSCODE_CLI": "/nonexistent/anvil-test-code",
        "ANVIL_TEST_REPO": str(ROOT),
    }
    result.update(extra)
    return result


def offline_env(paths: dict[str, pathlib.Path], temp: pathlib.Path, **extra: str) -> dict[str, str]:
    log = temp / "network-attempts.log"
    log.unlink(missing_ok=True)
    prior_pythonpath = os.environ.get("PYTHONPATH", "")
    guard = str(ROOT / "tests" / "fixtures" / "network-denied")
    env = env_for(paths, PYTHONPATH=os.pathsep.join(part for part in (guard, prior_pythonpath) if part),
                  ANVIL_NETWORK_GUARD_LOG=str(log), **extra)
    return env


def assert_no_external_network(temp: pathlib.Path) -> None:
    log = temp / "network-attempts.log"
    check(not log.exists() or not log.read_text(encoding="utf-8").strip(),
          f"offline lifecycle attempted external network access: {log.read_text(encoding='utf-8') if log.exists() else ''}")


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
         "source \"$ANVIL_ROOT/scripts/lib/install.sh\"; anvil_build_config \"$1\" \"$2\" yes 1 \"$(cat \"$ANVIL_ROOT/VERSION\")\"",
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
    env = offline_env(paths, temp,
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
    assert_no_external_network(temp)
    print("PASS first-install reforge follows the OpenCode 1 policy and remains repeatable")


def reforge_preserves_v2_test(temp: pathlib.Path, wrapper: pathlib.Path) -> None:
    paths = fixture(temp)
    use_v2_profile(paths, temp, wrapper)
    original_binary = file_hash(paths["binary"])
    env = offline_env(paths, temp, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), ANVIL_YES="1")
    proc = run(["/usr/bin/make", "--no-print-directory", "reforge"], env)
    installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    check(installation["runtime_major"] == 2 and installation["version"].startswith("2."), "reforge changed an existing OpenCode 2 runtime")
    check(file_hash(paths["binary"]) == original_binary, "reforge changed the exact existing OpenCode 2 executable")
    check("agents" in config and "agent" not in config, "reforge did not retain the OpenCode 2 config adapter")
    check("Status: HEALTHY" in proc.stdout, "OpenCode 2 reforge postflight doctor failed")
    assert_no_external_network(temp)
    print("PASS make reforge preserves the selected OpenCode 2 runtime profile")


def local_inventory_and_external_runtime_test(temp: pathlib.Path) -> None:
    paths = fixture(temp)
    external_dir = paths["home"] / ".local" / "bin"
    external_dir.mkdir(parents=True)
    external_binary = external_dir / "opencode"
    shutil.move(paths["binary"], external_binary)
    paths["binary"] = external_binary
    shutil.rmtree(paths["home"] / ".opencode")
    run([sys.executable, str(ROOT / "scripts" / "runtime_state.py"), "record", "--binary", str(external_binary)],
        env_for(paths))
    env = offline_env(paths, temp, PATH="/usr/bin:/bin")

    inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], env)
    check("OpenCode installed     True" in inspect.stdout and "OpenCode usable        True" in inspect.stdout,
          "inspect confused an absolute executable outside PATH with an absent runtime")
    check("PATH integration      NOT READY" in inspect.stdout, "inspect did not report PATH readiness separately")
    for target in ("doctor", "capabilities", "stats"):
        run(["/usr/bin/make", "--no-print-directory", target], env)
    run(["/usr/bin/make", "--no-print-directory", "databricks-setup", "DRY_RUN=1"], env)
    dry = run(["/usr/bin/make", "--no-print-directory", "upgrade", "DRY_RUN=1"], env)
    check(str(external_binary) in dry.stdout and "Network required      NO" in dry.stdout,
          "offline Anvil upgrade did not select the validated absolute runtime")
    assert_no_external_network(temp)
    print("PASS inspect, doctor, capabilities, stats, and Anvil dry-run are local; absolute runtime discovery survives PATH loss")


def upgrade_external_runtime_is_offline_test(temp: pathlib.Path) -> None:
    paths = fixture(temp)
    external_dir = paths["home"] / ".local" / "bin"
    external_dir.mkdir(parents=True)
    external_binary = external_dir / "opencode"
    shutil.move(paths["binary"], external_binary)
    paths["binary"] = external_binary
    shutil.rmtree(paths["home"] / ".opencode")
    run([sys.executable, str(ROOT / "scripts" / "runtime_state.py"), "record", "--binary", str(external_binary)],
        env_for(paths))
    before_hash = file_hash(external_binary)
    before_startup = (paths["home"] / ".bashrc").read_text(encoding="utf-8")
    env = offline_env(paths, temp, PATH="/usr/bin:/bin", ANVIL_YES="1")
    proc = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    backup = pathlib.Path(installation["migration"]["backup"])
    check(file_hash(external_binary) == before_hash, "Anvil upgrade changed an external OpenCode executable")
    check(not (paths["home"] / ".opencode").exists(), "Anvil upgrade created a managed OpenCode runtime tree")
    check((paths["home"] / ".bashrc").read_text(encoding="utf-8") == before_startup,
          "Anvil upgrade edited shell startup PATH")
    check(installation["binary"] == str(external_binary), "Anvil metadata did not retain the selected absolute executable")
    runtime_state = json.loads((paths["anvil_data"] / "runtime.json").read_text(encoding="utf-8"))["runtime"]
    check(runtime_state["executable"] == str(external_binary) and runtime_state["version"] == "1.19.0",
          "validated runtime state did not record the selected absolute executable/version")
    check(runtime_state["identity"]["sha256"] == hashlib.sha256(external_binary.read_bytes()).hexdigest(),
          "runtime state did not retain a current executable identity hash")
    check((paths["anvil_data"] / "runtime.json").stat().st_mode & 0o777 == 0o600,
          "runtime state file is not private")
    check(json.loads((backup / "manifest.json").read_text(encoding="utf-8"))["scope"] == "anvil",
          "Anvil upgrade used a runtime-scoped backup")
    check("OpenCode 1.19.0 was preserved exactly" in proc.stderr,
          "Anvil upgrade did not report preservation of the exact runtime")
    assert_no_external_network(temp)
    print("PASS Anvil upgrade with an external PATH-hidden runtime is offline and changes no OpenCode or PATH files")


def anvil_upgrade_rollback_test(temp: pathlib.Path) -> None:
    paths = fixture(temp)
    before = {
        "config": tree_hash(paths["config"]), "binary": file_hash(paths["binary"]),
        "data": tree_hash(paths["data_opencode"]), "state": tree_hash(paths["state_opencode"]),
        "installation": file_hash(paths["anvil_data"] / "installation.json"),
        "memory": tree_hash(paths["memory"]),
    }
    env = offline_env(paths, temp, ANVIL_YES="1", ANVIL_TEST_FAIL_AFTER_CONFIG="1")
    proc = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env, expected=2)
    after = {
        "config": tree_hash(paths["config"]), "binary": file_hash(paths["binary"]),
        "data": tree_hash(paths["data_opencode"]), "state": tree_hash(paths["state_opencode"]),
        "installation": file_hash(paths["anvil_data"] / "installation.json"),
        "memory": tree_hash(paths["memory"]),
    }
    check(after == before, "Anvil-only rollback did not restore metadata/config while preserving runtime and user state")
    check("Automatic Anvil rollback completed" in proc.stderr, "Anvil-only failure did not report successful scoped rollback")
    backups = list((paths["anvil_data"] / "backups").iterdir())
    check(len(backups) == 1 and json.loads((backups[0] / "manifest.json").read_text(encoding="utf-8"))["scope"] == "anvil",
          "failed Anvil upgrade did not retain its verified Anvil-only recovery snapshot")
    assert_no_external_network(temp)
    print("PASS Anvil-only post-mutation failure restores Anvil files without changing OpenCode runtime/data/state")

    before_metadata_paths = fixture(temp / "before-metadata")
    before_metadata = {
        "config": tree_hash(before_metadata_paths["config"]),
        "installation": file_hash(before_metadata_paths["anvil_data"] / "installation.json"),
        "runtime": file_hash(before_metadata_paths["binary"]),
        "data": tree_hash(before_metadata_paths["data_opencode"]),
        "state": tree_hash(before_metadata_paths["state_opencode"]),
    }
    before_metadata_env = offline_env(
        before_metadata_paths, temp / "before-metadata", ANVIL_YES="1",
        ANVIL_TEST_FAIL_BEFORE_METADATA="1",
    )
    before_metadata_failure = run(
        ["/usr/bin/make", "--no-print-directory", "upgrade"], before_metadata_env, expected=2,
    )
    after_metadata_failure = {
        "config": tree_hash(before_metadata_paths["config"]),
        "installation": file_hash(before_metadata_paths["anvil_data"] / "installation.json"),
        "runtime": file_hash(before_metadata_paths["binary"]),
        "data": tree_hash(before_metadata_paths["data_opencode"]),
        "state": tree_hash(before_metadata_paths["state_opencode"]),
    }
    check(after_metadata_failure == before_metadata,
          "failure immediately before metadata commit left source config or runtime state changed")
    check("Automatic Anvil rollback completed" in before_metadata_failure.stderr,
          "pre-metadata failure did not report successful source-state restoration")
    check(not (before_metadata_paths["anvil_data"] / "lifecycle-transaction.json").exists(),
          "pre-metadata rollback left a pending transaction journal")
    print("PASS failure before metadata commit restores the source release coherently")


def update_runtime_test(temp: pathlib.Path, wrapper_v1: pathlib.Path) -> None:
    paths = fixture(temp)
    installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    installation.update({"anvil_version": "2.6.1", "version": "1.19.0", "runtime_major": 1,
                         "binary": str(paths["binary"])})
    write_json(paths["anvil_data"] / "installation.json", installation)
    updated_candidate = temp / "opencode-v1-update-candidate"
    updated_candidate.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == --version ]]; then printf 'opencode v1.20.0\\n'; "
        f"else exec {shlex.quote(str(FIXTURES / 'bin' / 'opencode-v1'))} \"$@\"; fi\n",
        encoding="utf-8",
    )
    updated_candidate.chmod(0o755)
    before_config = tree_hash(paths["config"])
    before_data = tree_hash(paths["data_opencode"])
    before_state = tree_hash(paths["state_opencode"])
    env = offline_env(paths, temp, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(updated_candidate), ANVIL_YES="1")
    proc = run(["/usr/bin/make", "--no-print-directory", "update-runtime"], env)
    updated = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    check(updated["version"] == "1.20.0" and updated["runtime_major"] == 1,
          "same-major runtime update did not install the validated candidate")
    check(updated["anvil_version"] == "2.6.1", "runtime-only update advanced the installed Anvil release")
    check(tree_hash(paths["config"]) == before_config, "same-major runtime update changed Anvil config")
    check(tree_hash(paths["data_opencode"]) == before_data and tree_hash(paths["state_opencode"]) == before_state,
          "same-major runtime update rewrote OpenCode data/state")
    backup = pathlib.Path(updated["migration"]["backup"])
    check(json.loads((backup / "manifest.json").read_text(encoding="utf-8"))["scope"] == "runtime",
          "runtime update did not create a runtime-scoped snapshot")
    check("Anvil 2.6.1 was preserved" in proc.stderr, "runtime update did not report Anvil release preservation")
    assert_no_external_network(temp)
    print("PASS make update-runtime changes OpenCode within the same major while preserving Anvil release/config")


def release_403_boundary_test(temp: pathlib.Path) -> None:
    paths = fixture(temp)
    before_binary = file_hash(paths["binary"])
    before_config = tree_hash(paths["config"])
    before_data = tree_hash(paths["data_opencode"])
    before_state = tree_hash(paths["state_opencode"])
    before_installation = file_hash(paths["anvil_data"] / "installation.json")
    before_anvil_data = tree_hash(paths["anvil_data"])
    before_shell_startup = file_hash(paths["home"] / ".bashrc")

    env = offline_env(paths, temp, ANVIL_YES="1", ANVIL_NETWORK_GUARD_HTTP_403="1")
    upgrade = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    assert_no_external_network(temp)
    check(file_hash(paths["binary"]) == before_binary,
          "make upgrade changed the exact runtime while a mocked release service returned HTTP 403")
    check(tree_hash(paths["config"]) != before_config,
          "make upgrade did not install Anvil changes while the mocked release service was unavailable")
    check(tree_hash(paths["data_opencode"]) == before_data and tree_hash(paths["state_opencode"]) == before_state,
          "make upgrade changed OpenCode user data/state during the HTTP 403 regression")
    check("PRESERVE EXACT VERSION" in upgrade.stdout,
          "Anvil upgrade plan omitted exact runtime preservation during the HTTP 403 regression")
    check(file_hash(paths["anvil_data"] / "installation.json") != before_installation,
          "HTTP 403 fixture did not exercise an Anvil upgrade independently first")

    updated_anvil_binary = file_hash(paths["binary"])
    updated_anvil_config = tree_hash(paths["config"])
    updated_data = tree_hash(paths["data_opencode"])
    updated_state = tree_hash(paths["state_opencode"])
    updated_installation = file_hash(paths["anvil_data"] / "installation.json")
    backups_before_runtime = sorted(path.name for path in (paths["anvil_data"] / "backups").glob("*"))
    runtime_update = run(["/usr/bin/make", "--no-print-directory", "update-runtime"], env, expected=2)
    check("HTTP 403" in runtime_update.stderr and "api.github.com" in runtime_update.stderr,
          "explicit runtime update did not report the mocked GitHub HTTP 403 clearly")
    check("remain unchanged" in runtime_update.stderr,
          "explicit runtime update did not guarantee Anvil/runtime remain unchanged on lookup failure")
    check(file_hash(paths["binary"]) == updated_anvil_binary and tree_hash(paths["config"]) == updated_anvil_config,
          "failed runtime update changed the OpenCode executable or Anvil config")
    check(tree_hash(paths["data_opencode"]) == updated_data and tree_hash(paths["state_opencode"]) == updated_state,
          "failed runtime update changed OpenCode user data/state")
    check(file_hash(paths["anvil_data"] / "installation.json") == updated_installation,
          "failed runtime update changed Anvil installation metadata")
    backups_after_runtime = sorted(path.name for path in (paths["anvil_data"] / "backups").glob("*"))
    check(backups_after_runtime == backups_before_runtime,
          "release lookup failure created an additional lifecycle backup despite no live mutation")
    log = temp / "network-attempts.log"
    attempts = log.read_text(encoding="utf-8").splitlines()
    check(attempts == ["HTTP_403 https://api.github.com/repos/anomalyco/opencode/releases?per_page=100"],
          f"HTTP 403 fixture did not isolate the expected runtime release request: {attempts!r}")
    print("PASS mocked GitHub HTTP 403 cannot block make upgrade; update-runtime fails before mutation")


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
        doctor_env = offline_env(paths, temp)
        doctor_env["PATH"] = str(paths["binary"].parent) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")
        doctor = run(["/usr/bin/make", "--no-print-directory", "doctor"], doctor_env)
        check("Status: UPGRADE AVAILABLE" in doctor.stdout, "doctor did not recognize an older Anvil install")
        check("make upgrade" in doctor.stderr, "doctor did not explain the Anvil product upgrade path")
        stats = run(["/usr/bin/make", "--no-print-directory", "stats"], doctor_env)
        check("Sessions" in stats.stdout and "Input" in stats.stdout, "V1 native text stats were not forwarded")
        check("ERROR" not in stats.stderr, "V1 stats should not report an error")

    promote_fixture_to_current_anvil(paths, temp)

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
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    config["agent"]["anvil"]["permission"]["skill"].pop("anvil-communication", None)
    write_json(paths["config"] / "opencode.jsonc", config)
    installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    installation["anvil_version"] = "2.6.1"
    write_json(paths["anvil_data"] / "installation.json", installation)
    env = offline_env(paths, temp, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), ANVIL_YES="1")
    before_inspect = run(["/usr/bin/make", "--no-print-directory", "inspect"], env)
    check("Status                MIGRATION_REQUIRED" in before_inspect.stdout,
          "a valid Anvil 2.6.1 OpenCode 1 profile was treated as corrupted by the 2.7 repository")
    before_doctor = run(["/usr/bin/make", "--no-print-directory", "doctor"], env)
    check("Status: UPGRADE AVAILABLE" in before_doctor.stdout,
          "doctor did not recognize an older Anvil profile with a newly added skill missing")
    before_data = tree_hash(paths["data_opencode"])
    before_state = tree_hash(paths["state_opencode"])
    original_binary = file_hash(paths["binary"])
    proc = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    installed = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    check(installed["runtime_major"] == 1 and installed["version"] == "1.19.0", "make upgrade changed the exact OpenCode 1 runtime version")
    check(installed["anvil_version"] == (ROOT / "VERSION").read_text().strip(), "make upgrade did not update the Anvil release independently")
    check(config.get("default_agent") == "anvil" and "agent" in config, "Anvil 2.3 V1 runtime config was not installed")
    check(config["provider"]["custom"]["api"] == "https://example.invalid/v1", "same-major Anvil upgrade lost V1 provider config")
    check(tree_hash(paths["data_opencode"]) == before_data and tree_hash(paths["state_opencode"]) == before_state, "make upgrade changed OpenCode data/state")
    check("Network required      NO" in proc.stdout and "PRESERVE EXACT VERSION" in proc.stdout, "upgrade plan did not state the offline exact-runtime invariant")
    check(file_hash(paths["binary"]) == original_binary, "Anvil-only upgrade changed the OpenCode executable bytes")
    backup = pathlib.Path(installed["migration"]["backup"])
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    check(manifest["scope"] == "anvil", "normal Anvil upgrade did not create an Anvil-scoped backup")
    check("Status: HEALTHY" in proc.stdout, "OpenCode 1 Anvil 2.3 doctor was not healthy")
    for section in ("Capabilities", "Stats", "Memory", "Knowledge", "Project overrides", "Version documentation"):
        check(section in proc.stdout, f"OpenCode 1 doctor omitted the {section} category")
    check("/distill               YES" in proc.stdout and "file-fallback" in proc.stdout, "OpenCode 1 doctor omitted core command or fallback capability status")
    assert_no_external_network(temp)
    print("PASS make upgrade advances Anvil on OpenCode 1 without changing the runtime major")


def upgrade_preserves_v2_test(temp: pathlib.Path, wrapper: pathlib.Path) -> None:
    paths = fixture(temp)
    use_v2_profile(paths, temp, wrapper)
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    config["agents"]["anvil"]["permissions"] = [
        rule for rule in config["agents"]["anvil"]["permissions"]
        if not (rule.get("action") == "skill" and rule.get("resource") == "anvil-communication")
    ]
    write_json(paths["config"] / "opencode.jsonc", config)
    installation = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    installation["anvil_version"] = "2.6.1"
    write_json(paths["anvil_data"] / "installation.json", installation)
    before_data = tree_hash(paths["data_opencode"])
    before_state = tree_hash(paths["state_opencode"])
    original_binary = file_hash(paths["binary"])
    env = offline_env(paths, temp, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), ANVIL_YES="1")
    proc = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    installed = json.loads((paths["anvil_data"] / "installation.json").read_text(encoding="utf-8"))
    config = json.loads((paths["config"] / "opencode.jsonc").read_text(encoding="utf-8"))
    check(installed["runtime_major"] == 2 and installed["version"].startswith("2."), "make upgrade changed OpenCode 2 major")
    check(installed["anvil_version"] == (ROOT / "VERSION").read_text().strip(), "make upgrade did not advance the Anvil release on OpenCode 2")
    check("agents" in config and "agent" not in config and "anvil-core" in str(config.get("plugins")), "OpenCode 2 profile was not retained by same-major upgrade")
    check(tree_hash(paths["data_opencode"]) == before_data and tree_hash(paths["state_opencode"]) == before_state, "OpenCode 2 upgrade changed opaque user data/state")
    check("Network required      NO" in proc.stdout and "PRESERVE EXACT VERSION" in proc.stdout, "upgrade plan did not state the offline exact-runtime invariant")
    check(file_hash(paths["binary"]) == original_binary, "Anvil-only upgrade changed the OpenCode 2 executable bytes")
    check("Status: HEALTHY" in proc.stdout, "OpenCode 2 Anvil 2.3 doctor was not healthy")
    for section in ("Capabilities", "Stats", "Memory", "Knowledge", "Project overrides", "Version documentation"):
        check(section in proc.stdout, f"OpenCode 2 doctor omitted the {section} category")
    check("/distill               YES" in proc.stdout and "native-tool+file-fallback" in proc.stdout, "OpenCode 2 doctor omitted core command or native search capability status")
    assert_no_external_network(temp)
    print("PASS make upgrade advances Anvil on OpenCode 2 without changing the runtime major")


def dry_run_test(temp: pathlib.Path, wrapper_v1: pathlib.Path, wrapper_v2: pathlib.Path) -> None:
    paths = fixture(temp)
    promote_fixture_to_current_anvil(paths, temp)
    before = {
        "config": tree_hash(paths["config"]), "data": tree_hash(paths["data_opencode"]),
        "state": tree_hash(paths["state_opencode"]), "binary": file_hash(paths["binary"]),
        "installation": file_hash(paths["anvil_data"] / "installation.json"),
    }
    for command, wrapper in (
        (["upgrade", "DRY_RUN=1"], wrapper_v1),
        (["migrate-runtime", "OPENCODE_MAJOR=2", "DRY_RUN=1"], wrapper_v2),
    ):
        env = offline_env(paths, temp, ANVIL_TEST_MODE="1", ANVIL_TEST_CANDIDATE_BINARY=str(wrapper), DRY_RUN="1")
        proc = run(["/usr/bin/make", "--no-print-directory", *command], env)
        after = {
            "config": tree_hash(paths["config"]), "data": tree_hash(paths["data_opencode"]),
            "state": tree_hash(paths["state_opencode"]), "binary": file_hash(paths["binary"]),
            "installation": file_hash(paths["anvil_data"] / "installation.json"),
        }
        check(after == before, f"dry-run {command[0]} changed live user state")
        check(not (paths["anvil_data"] / "backups").exists(), f"dry-run {command[0]} created a backup")
        if command[0] == "upgrade":
            check("No changes performed" in proc.stdout and "Network required      NO" in proc.stdout and "PRESERVE EXACT VERSION" in proc.stdout,
                  "Anvil dry-run omitted local exact-runtime plan")
        else:
            check("Dry run complete" in proc.stdout and "Candidate" in proc.stdout, f"dry-run {command[0]} did not report its staged plan")
            check("Policy default major" in proc.stdout and "Current runtime capabilities" in proc.stdout, f"dry-run {command[0]} omitted runtime policy or current capabilities")
            check("Target runtime profile capabilities" in proc.stdout and "search_backend" in proc.stdout, f"dry-run {command[0]} omitted target capability fallbacks")
        assert_no_external_network(temp)
    print("PASS Anvil upgrade dry-run is offline; explicit runtime migration dry-run preserves live state")


def wait_for_file(path: pathlib.Path, process: subprocess.Popen[str], timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.025)
    check(path.exists(), f"runtime fixture did not reach its ready marker; exit={process.poll()}")


def start_runtime(paths: dict[str, pathlib.Path], *, marker: pathlib.Path, **extra: str) -> subprocess.Popen[str]:
    env = env_for(paths, ANVIL_TEST_READY=str(marker), **extra)
    process = subprocess.Popen([str(paths["binary"]), "--hold"], env=env, text=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for_file(marker, process)
    return process


def runtime_quiesce_test(temp: pathlib.Path) -> None:
    paths = fixture(temp)
    env = offline_env(paths, temp, ANVIL_TEST_MODE="1", ANVIL_YES="1",
                      ANVIL_UPGRADE_COUNTDOWN_SECONDS="0", ANVIL_OPEN_CODE_GRACE_SECONDS="0.25")
    before_config = tree_hash(paths["config"])
    before_data = tree_hash(paths["data_opencode"])
    before_state = tree_hash(paths["state_opencode"])
    before_installation = file_hash(paths["anvil_data"] / "installation.json")
    before_anvil_data = tree_hash(paths["anvil_data"])
    before_shell_startup = file_hash(paths["home"] / ".bashrc")
    marker = temp / "runtime-ready"
    term_marker = temp / "runtime-term"
    runtime = start_runtime(paths, marker=marker, ANVIL_TEST_TERM_MARKER=str(term_marker))
    dry = run(["/usr/bin/make", "--no-print-directory", "upgrade", "DRY_RUN=1"], env)
    check("active processes    1 running" in dry.stdout, "upgrade dry-run did not report the running OpenCode process")
    check("No processes stopped" in dry.stdout and "No files changed" in dry.stdout, "dry-run did not state its non-mutating behavior")
    check(runtime.poll() is None and not term_marker.exists(), "dry-run signaled or stopped OpenCode")
    check(not (paths["anvil_data"] / "backups").exists(), "dry-run created a backup with OpenCode running")
    check(tree_hash(paths["config"]) == before_config and tree_hash(paths["data_opencode"]) == before_data
          and tree_hash(paths["state_opencode"]) == before_state
          and file_hash(paths["anvil_data"] / "installation.json") == before_installation
          and tree_hash(paths["anvil_data"]) == before_anvil_data
          and file_hash(paths["home"] / ".bashrc") == before_shell_startup,
          "dry-run changed Anvil/OpenCode state")
    runtime.terminate()
    runtime.wait(timeout=3)
    print("PASS upgrade dry-run observes an active OpenCode process without signaling or writing state")

    marker.unlink(missing_ok=True)
    term_marker.unlink(missing_ok=True)
    runtime = start_runtime(paths, marker=marker, ANVIL_TEST_TERM_MARKER=str(term_marker))
    graceful = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    check(runtime.poll() is not None, "real upgrade did not gracefully stop OpenCode")
    check(term_marker.exists(), "real upgrade did not send SIGTERM before backup")
    check("SIGKILL as a fallback" not in graceful.stdout, "graceful runtime shutdown unexpectedly used SIGKILL")
    check("Start it normally when ready" in graceful.stderr, "upgrade omitted the normal runtime restart guidance")
    check((paths["anvil_data"] / "backups").is_dir(), "backup was not created after graceful shutdown")
    print("PASS upgrade sends SIGTERM, verifies shutdown, then creates its backup")

    paths = fixture(temp / "forced")
    env = offline_env(paths, temp / "forced", ANVIL_TEST_MODE="1", ANVIL_YES="1",
                      ANVIL_UPGRADE_COUNTDOWN_SECONDS="0", ANVIL_OPEN_CODE_GRACE_SECONDS="0.15")
    marker = temp / "forced-ready"
    runtime = start_runtime(paths, marker=marker, ANVIL_TEST_IGNORE_TERM="1")
    forced = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    check(runtime.poll() is not None, "SIGKILL fallback did not stop the unresponsive runtime")
    check("using SIGKILL as a fallback" in forced.stdout, "unresponsive OpenCode did not report its SIGKILL fallback")
    check((paths["anvil_data"] / "backups").is_dir(), "forced shutdown did not verify quiescence before backup")
    print("PASS upgrade uses SIGKILL only after the bounded graceful timeout")

    paths = fixture(temp / "unrelated")
    env = offline_env(paths, temp / "unrelated", ANVIL_TEST_MODE="1", ANVIL_YES="1",
                      ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    other_home = temp / "other-home"
    other_env = env_for(paths, HOME=str(other_home), XDG_CONFIG_HOME=str(other_home / ".config"),
                        XDG_DATA_HOME=str(other_home / ".local/share"), XDG_STATE_HOME=str(other_home / ".local/state"),
                        ANVIL_TEST_READY=str(temp / "other-ready"))
    unrelated = subprocess.Popen([str(paths["binary"]), "--hold"], env=other_env, text=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for_file(temp / "other-ready", unrelated)
    ignored = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env)
    check("active processes    0 running" in ignored.stdout, "unrelated same-executable process was treated as this Anvil runtime")
    check(unrelated.poll() is None, "upgrade stopped an OpenCode process using different XDG data paths")
    unrelated.terminate()
    unrelated.wait(timeout=3)
    print("PASS upgrade leaves a same-executable process using unrelated XDG paths untouched")

    paths = fixture(temp / "preflight")
    env = offline_env(paths, temp / "preflight", ANVIL_TEST_MODE="1", ANVIL_YES="1",
                      ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    bad_backup = paths["anvil_data"] / "backups"
    bad_backup.symlink_to(temp, target_is_directory=True)
    runtime = start_runtime(paths, marker=temp / "preflight-ready")
    failed = run(["/usr/bin/make", "--no-print-directory", "upgrade"], env, expected=2)
    check(runtime.poll() is None, "preflight failure stopped OpenCode")
    check("preflight failed" in failed.stderr.casefold(), "preflight failure was not described")
    check(not (paths["anvil_data"] / "installation.json").is_symlink(), "preflight touched installation state")
    runtime.terminate()
    runtime.wait(timeout=3)
    print("PASS backup preflight failure leaves OpenCode running and live state untouched")

    paths = fixture(temp / "ancestor")
    env = offline_env(paths, temp / "ancestor", ANVIL_TEST_MODE="1", ANVIL_YES="1",
                      ANVIL_UPGRADE_COUNTDOWN_SECONDS="0")
    child = subprocess.run([str(paths["binary"]), "--run-upgrade-child"], env=env, text=True,
                           capture_output=True, timeout=30, check=False)
    check(child.returncode != 0, "upgrade from inside OpenCode unexpectedly succeeded")
    check("inside OpenCode" in child.stderr, "self-ancestor upgrade did not explain the safe recovery action")
    check(not (paths["anvil_data"] / "backups").exists(), "self-ancestor upgrade created a backup")
    print("PASS upgrade aborts before signaling an OpenCode ancestor process")

    paths = fixture(temp / "cancel")
    env = offline_env(paths, temp / "cancel", ANVIL_TEST_MODE="1", ANVIL_YES="1",
                      ANVIL_UPGRADE_COUNTDOWN_SECONDS="5", ANVIL_OPEN_CODE_GRACE_SECONDS="0.2")
    runtime = start_runtime(paths, marker=temp / "cancel-ready")
    process = subprocess.Popen(["/usr/bin/make", "--no-print-directory", "upgrade"], env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.monotonic() + 15
    output = ""
    while time.monotonic() < deadline and "Stopping in 5" not in output and process.poll() is None:
        time.sleep(0.025)
        if process.stdout:
            import select
            if select.select([process.stdout], [], [], 0)[0]:
                output += process.stdout.readline()
    check("Stopping in 5" in output, "upgrade did not expose a cancellable countdown")
    os.killpg(process.pid, signal.SIGINT)
    remaining_out, remaining_err = process.communicate(timeout=5)
    check(process.returncode != 0, "Ctrl+C during countdown did not cancel upgrade")
    check(runtime.poll() is None, "countdown cancellation stopped OpenCode")
    check(not (paths["anvil_data"] / "backups").exists(), "countdown cancellation created a backup")
    check("UPGRADE_CANCELLED" in (output + remaining_out + remaining_err), "countdown cancellation was not classified")
    runtime.terminate()
    runtime.wait(timeout=3)
    print("PASS user cancellation during countdown leaves OpenCode and Anvil state untouched")


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

    with tempfile.TemporaryDirectory(prefix="anvil-public-commands-", dir=TEST_ROOT) as name:
        fresh_machine_command_contract_test(pathlib.Path(name), wrapper_v1)
    with tempfile.TemporaryDirectory(prefix="anvil-partial-lifecycle-", dir=TEST_ROOT) as name:
        partial_lifecycle_matrix_test(pathlib.Path(name), wrapper_v1)
    lifecycle_version_order_test()
    with tempfile.TemporaryDirectory(prefix="anvil-config-ownership-", dir=TEST_ROOT) as name:
        config_ownership_transition_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-custom-agent-transition-", dir=TEST_ROOT) as name:
        custom_agent_transition_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-filesystem-paths-", dir=TEST_ROOT) as name:
        filesystem_and_working_directory_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-readonly-config-parent-", dir=TEST_ROOT) as name:
        readonly_config_parent_preflight_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-concurrent-lifecycle-", dir=TEST_ROOT) as name:
        concurrent_lifecycle_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-interrupted-transaction-", dir=TEST_ROOT) as name:
        interrupted_transaction_recovery_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-managed-file-repair-", dir=TEST_ROOT) as name:
        managed_file_repair_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-future-version-downgrade-", dir=TEST_ROOT) as name:
        future_install_downgrade_test(pathlib.Path(name))

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
    with tempfile.TemporaryDirectory(prefix="anvil-runtime-quiesce-", dir=TEST_ROOT) as name:
        runtime_quiesce_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-reforge-idempotent-", dir=TEST_ROOT) as name:
        reforge_test(pathlib.Path(name), wrapper_v1)
    with tempfile.TemporaryDirectory(prefix="anvil-reforge-preserves-v2-", dir=TEST_ROOT) as name:
        reforge_preserves_v2_test(pathlib.Path(name), wrapper_v2)
    with tempfile.TemporaryDirectory(prefix="anvil-local-inventory-", dir=TEST_ROOT) as name:
        local_inventory_and_external_runtime_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-external-runtime-", dir=TEST_ROOT) as name:
        upgrade_external_runtime_is_offline_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-upgrade-rollback-scope-", dir=TEST_ROOT) as name:
        anvil_upgrade_rollback_test(pathlib.Path(name))
    with tempfile.TemporaryDirectory(prefix="anvil-runtime-update-", dir=TEST_ROOT) as name:
        update_runtime_test(pathlib.Path(name), wrapper_v1)
    with tempfile.TemporaryDirectory(prefix="anvil-runtime-http-403-", dir=TEST_ROOT) as name:
        release_403_boundary_test(pathlib.Path(name))
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
