from __future__ import annotations

import contextlib
import shutil
import csv
import hashlib
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
import unittest
import venv
from pathlib import Path
from unittest.mock import patch

from scripts.analytics_dependencies import (DependencyError, PackageResolutionPolicy, PackageSource,
                                            _append_log, _redact, activate, abort, finalize, package_resolution_policy,
                                            _failure_reason, _validate, main as dependencies_main,
                                            parse_lock, prepare, restore_operation, runtime_path, stage, staged_interpreter)
from scripts.analytics_service import _unit_text, validate_candidate

ROOT = Path(__file__).resolve().parents[2]


class AnalyticsDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = self.root / "analytics-requirements.lock"
        shutil.copyfile(ROOT / "config/analytics-requirements.lock", self.lock)
        self.data = self.root / "data"

    @staticmethod
    def _wheel(index: Path, name: str, version: str) -> None:
        normalized = name.replace("-", "_")
        filename = f"{normalized}-{version}-py3-none-any.whl"
        package_dir = index / "simple" / name
        package_dir.mkdir(parents=True, exist_ok=True)
        wheel_path = package_dir / filename
        dist_info = f"{normalized}-{version}.dist-info"
        members = {
            f"{normalized}/__init__.py":
                f"__version__ = {version!r}\n".encode(),
            f"{dist_info}/METADATA":
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n".encode(),
            f"{dist_info}/WHEEL":
                b"Wheel-Version: 1.0\nGenerator: Anvil test fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        }
        record = io.StringIO()
        writer = csv.writer(record, lineterminator="\n")
        for member, payload in members.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
            writer.writerow((member, f"sha256={digest}", len(payload)))
        writer.writerow((f"{dist_info}/RECORD", "", ""))
        members[f"{dist_info}/RECORD"] = record.getvalue().encode()
        with zipfile.ZipFile(wheel_path, "w") as archive:
            for member, payload in members.items():
                archive.writestr(member, payload)
        (package_dir / "index.html").write_text(
            f'<a href="{filename}">{filename}</a>\n', encoding="utf-8")

    def test_release_lock_is_exact_and_content_addressed(self) -> None:
        release, packages = parse_lock(self.lock)
        self.assertEqual(release, "2.17.1")
        self.assertEqual(dict(packages), {"duckdb": "1.5.5", "pyarrow": "26.0.0"})
        first = runtime_path(self.lock, self.data)
        changed = self.root / "changed.lock"
        changed.write_text(self.lock.read_text(encoding="utf-8") + "# reviewed change\n", encoding="utf-8")
        self.assertNotEqual(first, runtime_path(changed, self.data))

    def test_venv_python_symlinks_are_validated_by_prefix_and_execution(self) -> None:
        environment = self.root / "venv"
        venv.EnvBuilder(with_pip=False).create(environment)
        interpreter = environment / "bin" / "python"
        self.assertTrue(interpreter.is_file())
        self.assertTrue(os.access(interpreter, os.X_OK))
        self.assertTrue(_validate(interpreter, []), "a standard venv interpreter must pass semantic validation")

        wrong = self.root / "wrong-venv" / "bin" / "python"
        wrong.parent.mkdir(parents=True)
        wrong.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n", encoding="utf-8")
        wrong.chmod(0o700)
        self.assertFalse(_validate(wrong, []), "a launcher outside the expected venv prefix must fail")

        broken = self.root / "broken-venv" / "bin" / "python"
        broken.parent.mkdir(parents=True)
        broken.symlink_to(self.root / "missing-python")
        self.assertFalse(_validate(broken, []), "a broken venv interpreter link must fail")
        self.assertFalse(_validate(self.root / "missing-python", []))

    def test_dependency_action_cli_contracts_are_strict_and_do_not_fall_through(self) -> None:
        actions = ("prepare", "stage", "activate", "abort", "restore", "finalize",
                   "resolve", "status", "plan")
        lifecycle = {"abort", "restore", "finalize"}
        lock_actions = {"prepare", "stage", "activate", "resolve", "status", "plan"}
        operation = "action-contract-fixture"
        output = io.StringIO()
        status_value = {"ready": True, "release": "test", "selected_source": {"label": "local"},
                        "resolution_policy": {"primary": {"label": "local"}}}
        policy = PackageResolutionPolicy(
            PackageSource("file:///tmp/registry", "CORPORATE_REGISTRY", "Configured local package registry"),
            False, None, "corporate-first", "test",
        )
        with patch("scripts.analytics_dependencies.parse_lock", return_value=("test", [("duckdb", "1"), ("pyarrow", "2")])), \
             patch("scripts.analytics_dependencies.runtime_path", return_value=self.data / "runtime"), \
             patch("scripts.analytics_dependencies.python_version", return_value=((3, 11), "3.11")), \
             patch("scripts.analytics_dependencies._validate", return_value=True), \
             patch("scripts.analytics_dependencies.package_resolution_policy", return_value=policy), \
             patch("scripts.analytics_dependencies.resolution_status", return_value=dict(status_value)), \
             patch("scripts.analytics_dependencies.prepare", return_value=self.root / "venv/bin/python"), \
             patch("scripts.analytics_dependencies.stage", return_value=self.root / "stage/bin/python"), \
             patch("scripts.analytics_dependencies.activate", return_value=self.root / "active/bin/python"), \
             patch("scripts.analytics_dependencies.abort") as abort_action, \
             patch("scripts.analytics_dependencies.restore_operation") as restore_action, \
             patch("scripts.analytics_dependencies.finalize") as finalize_action:
            for action in actions:
                argv = [action, "--format", "json", "--data-root", str(self.data)]
                if action in lock_actions:
                    argv += ["--lock", str(self.lock)]
                if action in lifecycle or action == "activate":
                    argv += ["--operation-id", operation]
                output.seek(0)
                output.truncate(0)
                with self.subTest(action=action), contextlib.redirect_stdout(output):
                    self.assertEqual(dependencies_main(argv), 0)
                result = json.loads(output.getvalue())
                self.assertIsInstance(result, dict)
                if action in lifecycle:
                    self.assertEqual(result, {"operation_id": operation, "status": action.upper()})
            abort_action.assert_called_once_with(self.data, operation)
            restore_action.assert_called_once_with(self.data, operation)
            finalize_action.assert_called_once_with(self.data, operation)

        invalid = (
            ["prepare"], ["stage"], ["activate", "--lock", str(self.lock)],
            ["resolve"], ["status"], ["plan"],
            ["abort"], ["restore"], ["finalize"],
            ["abort", "--operation-id", operation, "--lock", str(self.lock)],
            ["restore", "--operation-id", operation, "--python", sys.executable],
            ["plan", "--lock", str(self.lock), "--unexpected"],
        )
        for argv in invalid:
            with self.subTest(invalid_argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    dependencies_main(argv)
                self.assertEqual(raised.exception.code, 2)
        self.assertEqual(_failure_reason("external network disabled by Anvil offline test fixture"),
                         "NETWORK_BLOCKED")
        self.assertEqual(_failure_reason(
            "HTTPSConnectionPool: Max retries exceeded after Failed to establish a new connection; "
            "Could not find a version that satisfies the requirement duckdb==1.5.5"), "REGISTRY_UNAVAILABLE")
        self.assertEqual(_failure_reason("Could not find a version that satisfies duckdb==1.5.5"),
                         "VERSION_NOT_FOUND")

    def test_failed_package_install_preserves_previous_environment(self) -> None:
        destination = runtime_path(self.lock, self.data)
        destination.mkdir(parents=True)
        marker = destination / "previous-install"
        marker.write_text("previous supported environment", encoding="utf-8")
        calls = []

        def run(command, **_kwargs):
            calls.append(command)
            if "-c" in command:
                return subprocess.CompletedProcess(command, 0, stdout="3.14\n", stderr="")
            if command[1:3] == ["-m", "venv"]:
                (Path(command[3]) / "bin").mkdir(parents=True)
                fake_python = Path(command[3]) / "bin" / "python"
                fake_python.write_text("fixture python", encoding="utf-8")
                fake_python.chmod(0o700)
                return subprocess.CompletedProcess(command, 0)
            raise subprocess.CalledProcessError(1, command)

        with patch("scripts.analytics_dependencies._validate", return_value=False), \
             patch("scripts.analytics_dependencies.subprocess.run", side_effect=run):
            with self.assertRaises(DependencyError) as raised:
                prepare(self.lock, self.data)
        self.assertEqual(raised.exception.dependency, "duckdb")
        self.assertEqual(marker.read_text(encoding="utf-8"), "previous supported environment")
        self.assertFalse(any(path.name.startswith(".runtime-") for path in destination.parent.iterdir()))
        self.assertTrue(any("duckdb==1.5.5" in command for command in calls))

    def test_dependency_drift_is_rebuilt_and_imports_revalidated(self) -> None:
        destination = runtime_path(self.lock, self.data)
        destination.mkdir(parents=True)
        (destination / "drift-marker").write_text("missing pyarrow", encoding="utf-8")
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            if "-c" in command:
                return subprocess.CompletedProcess(command, 0, stdout="3.14\n", stderr="")
            if command[1:3] == ["-m", "venv"]:
                (Path(command[3]) / "bin").mkdir(parents=True)
                fake_python = Path(command[3]) / "bin" / "python"
                fake_python.write_text("repaired python", encoding="utf-8")
                fake_python.chmod(0o700)
            return subprocess.CompletedProcess(command, 0)

        with patch("scripts.analytics_dependencies._validate", side_effect=[False, True, True]), \
             patch("scripts.analytics_dependencies.subprocess.run", side_effect=run):
            interpreter = prepare(self.lock, self.data)
        self.assertTrue(interpreter.is_file())
        self.assertFalse((destination / "drift-marker").exists())
        self.assertEqual(sum(command[1:3] == ["-m", "pip"] for command in commands), 2)

    def test_validated_environment_is_published_only_after_all_pins_install(self) -> None:
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            if "-c" in command:
                return subprocess.CompletedProcess(command, 0, stdout="3.14\n", stderr="")
            if command[1:3] == ["-m", "venv"]:
                (Path(command[3]) / "bin").mkdir(parents=True)
                fake_python = Path(command[3]) / "bin" / "python"
                fake_python.write_text("fixture python", encoding="utf-8")
                fake_python.chmod(0o700)
            return subprocess.CompletedProcess(command, 0)

        with patch("scripts.analytics_dependencies._validate", side_effect=[True, True]), \
             patch("scripts.analytics_dependencies.subprocess.run", side_effect=run):
            interpreter = prepare(self.lock, self.data)
        self.assertTrue(interpreter.is_file())
        installs = [command for command in commands if command[1:3] == ["-m", "pip"]]
        self.assertEqual(len(installs), 2)
        self.assertTrue(all("--no-deps" in command and "--only-binary=:all:" in command for command in installs))
        self.assertEqual(interpreter.name, "python")

    def test_stage_is_not_active_until_activation_and_can_be_restored(self) -> None:
        operation = "fixture-stage"
        destination = runtime_path(self.lock, self.data)

        def build(root, operation_id, _source, _packages, _python, _log, _env):
            staged = root / f".runtime-{operation_id}-fixture"
            (staged / "bin").mkdir(parents=True)
            interpreter = staged / "bin" / "python"
            interpreter.write_text("# fixture runtime\\n", encoding="utf-8")
            interpreter.chmod(0o700)
            return staged

        policy = PackageResolutionPolicy(
            PackageSource("https://packages.example.invalid/simple", "CORPORATE_REGISTRY", "Corporate registry"),
            False, None, "corporate-first", "test",
        )
        with patch("scripts.analytics_dependencies.python_version", return_value=((3, 14), "3.14")), \
             patch("scripts.analytics_dependencies._build_staging", side_effect=build), \
             patch("scripts.analytics_dependencies._validate", return_value=True):
            staged = stage(self.lock, self.data, operation_id=operation, policy=policy)
            self.assertFalse(destination.exists(), "stage must leave the active content-addressed runtime untouched")
            self.assertEqual(staged, staged_interpreter(self.lock, self.data, operation))
            active = activate(self.lock, self.data, operation)
            self.assertEqual(active, destination / "bin" / "python")
            self.assertTrue(active.is_file())
            config_home = self.root / "config-home"
            active_lock = config_home / "opencode" / "runtime" / "analytics-requirements.lock"
            active_lock.parent.mkdir(parents=True)
            shutil.copyfile(self.lock, active_lock)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}):
                with self.assertRaises(DependencyError):
                    restore_operation(self.data, operation)
                self.assertTrue(active.is_file(), "rollback deleted a runtime still referenced by active config")
                active_lock.write_text(self.lock.read_text(encoding="utf-8") + "# old pointer\n", encoding="utf-8")
                restore_operation(self.data, operation)
            self.assertFalse(destination.exists(), "rollback must remove a newly activated target runtime")

    def test_service_candidate_uses_final_runtime_path_not_hidden_stage_path(self) -> None:
        config = self.root / "config"
        (config / "runtime").mkdir(parents=True)
        shutil.copyfile(self.lock, config / "runtime" / "analytics-requirements.lock")
        (config / "scripts" / "analytics").mkdir(parents=True)
        (config / "scripts" / "analytics" / "server.py").write_text("# server fixture\n")
        (config / "web" / "analytics").mkdir(parents=True)
        (config / "web" / "analytics" / "index.html").write_text("<html></html>")
        home = self.root / "home"
        systemd = self.root / "config-home" / "systemd" / "user"
        with patch.dict("os.environ", {"XDG_DATA_HOME": str(self.data),
                                       "XDG_CONFIG_HOME": str(self.root / "config-home")}):
            target = runtime_path(config / "runtime" / "analytics-requirements.lock", self.data) / "bin" / "python"
            staged_root = target.parent.parent.parent / ".runtime-operation-fixture"
            venv.EnvBuilder(with_pip=False).create(staged_root)
            staged = staged_root / "bin" / "python"
            with patch("scripts.analytics_service._validate", return_value=True):
                result = validate_candidate(config, home, systemd, 8765, staged)
            self.assertEqual(result["interpreter"], str(staged))
            self.assertEqual(result["service_interpreter"], str(target))
            unit = _unit_text(config, home, 8765, Path(result["service_interpreter"]))
        self.assertIn(f'ExecStart="{target}"', unit)
        self.assertNotIn(str(staged), unit)
        self.assertFalse(systemd.exists(), "candidate verification must not write or install the unit")

    def test_local_corporate_package_index_stages_and_activates_exact_pins(self) -> None:
        index = self.root / "registry"
        self._wheel(index, "duckdb", "1.5.5")
        self._wheel(index, "pyarrow", "26.0.0")
        env = {
            "HOME": str(self.root / "home"),
            "PIP_INDEX_URL": (index / "simple").as_uri(),
            "ANVIL_ALLOW_PUBLIC_PYPI": "false",
            "XDG_STATE_HOME": str(self.root / "state"),
        }
        policy = package_resolution_policy(env=env, home=self.root / "home")
        self.assertEqual(policy.primary.source_type, "CORPORATE_REGISTRY")
        self.assertFalse(policy.public_fallback)
        with patch.dict("os.environ", env, clear=False):
            staged = stage(self.lock, self.data, operation_id="local-registry", policy=policy)
            destination = runtime_path(self.lock, self.data)
            self.assertFalse(destination.exists())
            self.assertTrue(staged.is_file())
            selected = json.loads((staged.parents[1] / "anvil-package-resolution.json").read_text())
            self.assertEqual(selected["selected_source"]["source_type"], "CORPORATE_REGISTRY")
            staged_hash = hashlib.sha256(staged.read_bytes()).hexdigest()
            active = activate(self.lock, self.data, "local-registry")
            self.assertEqual(active, destination / "bin" / "python")
            self.assertTrue(active.is_file())
            self.assertEqual(hashlib.sha256(active.read_bytes()).hexdigest(), staged_hash)
            finalize(self.data, "local-registry")

    def test_corporate_index_is_authoritative_and_public_fallback_is_explicit(self) -> None:
        home = self.root / "home"
        pip_conf = home / ".config" / "pip" / "pip.conf"
        pip_conf.parent.mkdir(parents=True)
        pip_conf.write_text("[global]\nindex-url = https://user:SECRET_REGISTRY_TOKEN_123@packages.example/simple\n"
                            "extra-index-url = https://pypi.org/simple\n", encoding="utf-8")
        original = pip_conf.read_bytes()
        env = {"HOME": str(home), "PIP_INDEX_URL": "https://pypi.org/simple",
               "PIP_EXTRA_INDEX_URL": "https://pypi.org/simple",
               "XDG_CONFIG_HOME": str(home / ".config")}
        policy = package_resolution_policy(env=env, home=home)
        self.assertEqual(policy.primary.source_type, "CORPORATE_REGISTRY")
        self.assertFalse(policy.public_fallback)
        self.assertEqual(len(policy.sources()), 1)
        enabled = package_resolution_policy(
            env={**env, "ANVIL_ALLOW_PUBLIC_PYPI": "true"}, home=home)
        self.assertTrue(enabled.public_fallback)
        self.assertEqual([source.source_type for source in enabled.sources()],
                         ["CORPORATE_REGISTRY", "PUBLIC_PYPI"])
        self.assertEqual(pip_conf.read_bytes(), original, "Anvil must not mutate global pip configuration")
        self.assertNotIn("SECRET_REGISTRY_TOKEN_123", json.dumps(enabled.public()))

    def test_explicit_fallback_uses_public_only_after_primary_package_failure(self) -> None:
        seen = []
        root = self.data / "anvil" / "analytics" / "runtimes"
        policy = PackageResolutionPolicy(
            PackageSource("https://packages.example.invalid/simple", "CORPORATE_REGISTRY", "Corporate registry"),
            True, PackageSource("https://pypi.org/simple", "PUBLIC_PYPI", "Public PyPI"),
            "corporate-first", "test",
        )

        def build(runtime_root, operation, source, _packages, _python, _log, _env):
            seen.append(source.source_type)
            if source.source_type == "CORPORATE_REGISTRY":
                raise DependencyError("duckdb", "pinned package is missing", version="1.5.5",
                                      reason_code="PACKAGE_NOT_FOUND")
            staged = runtime_root / f".runtime-{operation}-public"
            (staged / "bin").mkdir(parents=True)
            interpreter = staged / "bin" / "python"
            interpreter.write_text("fixture", encoding="utf-8")
            interpreter.chmod(0o700)
            return staged

        with patch("scripts.analytics_dependencies.python_version", return_value=((3, 14), "3.14")), \
             patch("scripts.analytics_dependencies._build_staging", side_effect=build), \
             patch("scripts.analytics_dependencies._validate", return_value=True):
            stage(self.lock, self.data, operation_id="fallback", policy=policy)
        self.assertEqual(seen, ["CORPORATE_REGISTRY", "PUBLIC_PYPI"])
        abort(self.data, "fallback")

    def test_disabled_fallback_never_attempts_public_source(self) -> None:
        seen = []
        policy = PackageResolutionPolicy(
            PackageSource("https://packages.example.invalid/simple", "CORPORATE_REGISTRY", "Corporate registry"),
            False, None, "corporate-first", "test",
        )

        def build(_root, _operation, source, _packages, _python, _log, _env):
            seen.append(source.source_type)
            raise DependencyError("duckdb", "pinned package is missing", version="1.5.5",
                                  reason_code="PACKAGE_NOT_FOUND")

        with patch("scripts.analytics_dependencies.python_version", return_value=((3, 14), "3.14")), \
             patch("scripts.analytics_dependencies._build_staging", side_effect=build):
            with self.assertRaises(DependencyError) as raised:
                stage(self.lock, self.data, operation_id="no-fallback", policy=policy)
        self.assertEqual(raised.exception.reason_code, "PACKAGE_NOT_FOUND")
        self.assertEqual(seen, ["CORPORATE_REGISTRY"])
        self.assertFalse(runtime_path(self.lock, self.data).exists())

    def test_registry_credentials_are_redacted_from_logs_and_user_output(self) -> None:
        token = "SECRET_REGISTRY_TOKEN_123"
        env = {"PIP_INDEX_URL": f"https://user:{token}@packages.example/simple?auth={token}"}
        output = f"Retrying https://user:{token}@packages.example/simple?auth={token}"
        redacted = _redact(output, env)
        self.assertNotIn(token, redacted)
        log = self.root / "private" / "dependency-install.log"
        _append_log(log, "package install", output, env)
        self.assertNotIn(token, log.read_text(encoding="utf-8"))
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
