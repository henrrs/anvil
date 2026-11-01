from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.analytics_dependencies import DependencyError, parse_lock, prepare, runtime_path

ROOT = Path(__file__).resolve().parents[2]


class AnalyticsDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = self.root / "analytics-requirements.lock"
        shutil.copyfile(ROOT / "config/analytics-requirements.lock", self.lock)
        self.data = self.root / "data"

    def test_release_lock_is_exact_and_content_addressed(self) -> None:
        release, packages = parse_lock(self.lock)
        self.assertEqual(release, "2.17.0")
        self.assertEqual(dict(packages), {"duckdb": "1.5.5", "pyarrow": "26.0.0"})
        first = runtime_path(self.lock, self.data)
        changed = self.root / "changed.lock"
        changed.write_text(self.lock.read_text(encoding="utf-8") + "# reviewed change\n", encoding="utf-8")
        self.assertNotEqual(first, runtime_path(changed, self.data))

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
                (Path(command[3]) / "bin" / "python").write_text("fixture python", encoding="utf-8")
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
                (Path(command[3]) / "bin" / "python").write_text("repaired python", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with patch("scripts.analytics_dependencies._validate", side_effect=[False, False, True, True]), \
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
                (Path(command[3]) / "bin" / "python").write_text("fixture python", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with patch("scripts.analytics_dependencies._validate", side_effect=[True, True]), \
             patch("scripts.analytics_dependencies.subprocess.run", side_effect=run):
            interpreter = prepare(self.lock, self.data)
        self.assertTrue(interpreter.is_file())
        installs = [command for command in commands if command[1:3] == ["-m", "pip"]]
        self.assertEqual(len(installs), 2)
        self.assertTrue(all("--no-deps" in command and "--only-binary=:all:" in command for command in installs))
        self.assertEqual(interpreter.name, "python")


if __name__ == "__main__":
    unittest.main()
