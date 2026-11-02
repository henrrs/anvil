from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.analytics_service import (MARKER, SERVICE_NAME, _migrate_legacy_listener,
                                       _unit_text, service_state, sync)


class AnalyticsServiceManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home with spaces"
        self.config = self.root / 'config with "quotes"'
        self.systemd = self.root / "systemd" / "user"
        self.home.mkdir()
        (self.config / "scripts" / "analytics").mkdir(parents=True)
        (self.config / "scripts" / "analytics" / "server.py").write_text("# server", encoding="utf-8")
        (self.config / "web" / "analytics").mkdir(parents=True)
        (self.config / "web" / "analytics" / "index.html").write_text("<html>", encoding="utf-8")

    def test_unit_uses_prepared_python_and_quoted_working_directory(self) -> None:
        interpreter = Path("/opt/anvil analytics/bin/python")
        text = _unit_text(self.config, self.home, 8765, interpreter)
        escaped_config = str(self.config).replace(" ", "\\x20").replace(chr(34), "\\x22")
        self.assertIn(f"WorkingDirectory={escaped_config}", text)
        self.assertIn(f'ExecStart="{interpreter}" -m scripts.analytics.server', text)
        self.assertIn('Environment="XDG_DATA_HOME=', text)

    def test_systemd_mainpid_zero_is_not_ready_even_when_health_answers(self) -> None:
        self.systemd.mkdir(parents=True)
        (self.systemd / SERVICE_NAME).write_text(MARKER + "\n[Service]\n", encoding="utf-8")
        with patch("scripts.analytics_service._is_active_user_unit_dir", return_value=True), \
             patch("scripts.analytics_service._systemd_available", return_value=True), \
             patch("scripts.analytics_service._systemctl_value", side_effect=["enabled", "active", "0"]), \
             patch("scripts.analytics_service.health", return_value=True):
            value = service_state(self.config, self.home, self.systemd, 8765)
        self.assertFalse(value["active"])
        self.assertEqual(value["main_pid"], 0)
        self.assertEqual(value["status"], "NOT_READY")

    def test_status_without_systemd_is_read_only(self) -> None:
        root = self.home / ".local" / "share" / "anvil" / "analytics"
        with patch("scripts.analytics_service._systemd_available", return_value=False):
            value = service_state(self.config, self.home, self.systemd, 8765)
        self.assertEqual(value["status"], "NOT_READY")
        self.assertFalse(root.exists())

    def test_activate_fails_if_daemon_reload_fails(self) -> None:
        with patch("scripts.analytics_service._is_active_user_unit_dir", return_value=True), \
             patch("scripts.analytics_service._systemd_available", return_value=True), \
             patch("scripts.analytics_service._run_systemctl", return_value=False):
            with self.assertRaisesRegex(ValueError, "daemon-reload"):
                sync(self.config, self.home, self.systemd, 8765, activate=True)

    def test_sync_reloads_enables_and_starts_before_readiness_gate(self) -> None:
        calls = []
        def run_systemctl(*args):
            calls.append(args)
            return True

        with patch("scripts.analytics_service._is_active_user_unit_dir", return_value=True), \
             patch("scripts.analytics_service._systemd_available", return_value=True), \
             patch("scripts.analytics_service._run_systemctl", side_effect=run_systemctl), \
             patch("scripts.analytics_service._systemctl_value", return_value="inactive"), \
             patch("scripts.analytics_service.service_state", return_value={
                 "installed": True, "enabled": True, "active": True, "main_pid": 123,
                 "healthy": True, "status": "READY"}), \
             patch("scripts.analytics_service._wait_converged", return_value=True):
            result = sync(self.config, self.home, self.systemd, 8765, activate=True)
        self.assertEqual(result, "READY")
        self.assertEqual(calls, [("daemon-reload",), ("enable", "--now", SERVICE_NAME)])

    def test_unknown_port_owner_is_never_signaled(self) -> None:
        with patch("scripts.analytics_service._port_open", return_value=True), \
             patch("scripts.analytics_service._port_owner_pids", return_value=[4321]), \
             patch("scripts.analytics_service._is_legacy_anvil_process", return_value=False), \
             patch("scripts.analytics_service.os.kill") as kill:
            with self.assertRaisesRegex(ValueError, "unknown process"):
                _migrate_legacy_listener(self.config, 8765)
        kill.assert_not_called()

    def test_recognized_legacy_anvil_listener_is_stopped_gracefully(self) -> None:
        with patch("scripts.analytics_service._port_open", side_effect=[True, False, False]), \
             patch("scripts.analytics_service._port_owner_pids", return_value=[4321]), \
             patch("scripts.analytics_service._is_legacy_anvil_process", return_value=True), \
             patch("scripts.analytics_service.os.kill") as kill:
            _migrate_legacy_listener(self.config, 8765)
        kill.assert_called_once()
        self.assertEqual(kill.call_args.args[1], 15)

    def test_sync_repairs_managed_203_exec_unit_before_starting_service(self) -> None:
        self.systemd.mkdir(parents=True)
        unit = self.systemd / SERVICE_NAME
        unit.write_text(MARKER + "\n[Service]\nExecStart=/missing/analytics/python\n", encoding="utf-8")
        interpreter = self.root / "runtime" / "bin" / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        interpreter.chmod(0o700)
        calls = []

        def run_systemctl(*args):
            calls.append(args)
            return True

        with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.root / "config-home")}):
            with patch("scripts.analytics_service._service_runtime", return_value=interpreter), \
                 patch("scripts.analytics_service._verify_unit_payload"), \
                 patch("scripts.analytics_service._is_active_user_unit_dir", return_value=True), \
                 patch("scripts.analytics_service._systemd_available", return_value=True), \
                 patch("scripts.analytics_service._systemctl_value", return_value="inactive"), \
                 patch("scripts.analytics_service._port_open", return_value=False), \
                 patch("scripts.analytics_service._run_systemctl", side_effect=run_systemctl), \
                 patch("scripts.analytics_service.service_state", return_value={
                     "installed": True, "enabled": True, "active": True, "main_pid": 4321,
                     "healthy": True, "status": "READY"}), \
                 patch("scripts.analytics_service._wait_converged", return_value=True):
                self.assertEqual(sync(self.config, self.home, self.systemd, 8765), "READY")
        self.assertIn(str(interpreter), unit.read_text(encoding="utf-8"))
        self.assertNotIn("/missing/analytics/python", unit.read_text(encoding="utf-8"))
        self.assertEqual(calls, [("daemon-reload",), ("enable", "--now", SERVICE_NAME)])

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze is not installed")
    def test_generated_unit_passes_systemd_analyze_verify(self) -> None:
        unit = self._write_verifiable_unit()
        result = subprocess.run([shutil.which("systemd-analyze"), "verify", str(unit)],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def _write_verifiable_unit(self) -> Path:
        unit = self.root / SERVICE_NAME
        unit.write_text(_unit_text(self.config, self.home, 8765, Path(shutil.which("python3"))), encoding="utf-8")
        return unit


if __name__ == "__main__":
    unittest.main()
