from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.analytics_service import MARKER, SERVICE_NAME, _unit_text, service_state, sync


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
