from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from scripts import lifecycle_baseline


class LifecycleBaselineTests(unittest.TestCase):
    def test_healthy_analytics_baseline_restores_exact_files_without_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            config = root / "config" / "opencode"
            backup = root / "backup"
            systemd = root / "config" / "systemd" / "user"
            installation = root / "data" / "anvil" / "installation.json"
            runtime_file = home / ".anvil" / "analytics" / "runtime.json"
            unit = systemd / lifecycle_baseline.UNIT_NAME
            for path in (config, systemd, installation.parent, runtime_file.parent, backup):
                path.mkdir(parents=True, exist_ok=True)

            (config / ".anvil-managed.json").write_text('{"schema_version":1}\n', encoding="utf-8")
            installation.write_text('{"schema_version":3,"anvil_version":"2.17.0"}\n', encoding="utf-8")
            runtime_payload = {
                "schema_version": 1, "workspace": str(home / ".anvil/workspaces/analytics"),
                "base_url": "http://127.0.0.1:8765", "executable": "/opt/opencode/bin/opencode",
                "version": "1.19.0", "runtime_generation": 1,
                "canonical_session_id": "anvil-global-analytics",
            }
            runtime_file.write_text(json.dumps(runtime_payload, sort_keys=True) + "\n", encoding="utf-8")
            runtime_file.chmod(0o600)
            unit_payload = lifecycle_baseline.UNIT_MARKER + "\n[Service]\nExecStart=/opt/anvil/python\n"
            unit.write_text(unit_payload, encoding="utf-8")
            unit.chmod(0o640)

            service = {"installed": True, "unit_installed": True, "enabled": True,
                       "active": True, "healthy": True, "status": "READY"}
            runtime = {"runtime": {"usable": True, "supported": True,
                                   "executable": "/opt/opencode/bin/opencode",
                                   "version": "1.19.0", "generation": 1}}
            capture_args = Namespace(
                backup=backup, config_dir=config, home=home, data_root=root / "data",
                installation=installation, analytics_runtime_state=runtime_file,
                systemd_dir=systemd, binary=runtime["runtime"]["executable"],
                python="python3", port=8765,
            )
            with patch.object(lifecycle_baseline.runtime_state, "discover", return_value=runtime), \
                 patch.object(lifecycle_baseline.analytics_service, "service_state", return_value=service), \
                 patch.object(lifecycle_baseline.analytics_service, "_is_active_user_unit_dir", return_value=False), \
                 contextlib.redirect_stdout(io.StringIO()):
                lifecycle_baseline.capture(capture_args)

            original_runtime = runtime_file.read_bytes()
            original_unit = unit.read_bytes()
            runtime_file.write_text('{"canonical_session_id":"changed"}\n', encoding="utf-8")
            unit.write_text(lifecycle_baseline.UNIT_MARKER + "\n[Service]\nExecStart=/tmp/changed\n",
                            encoding="utf-8")

            restore_args = Namespace(
                backup=backup, config_dir=config, home=home, installation=installation,
                analytics_runtime_state=runtime_file, systemd_dir=systemd,
                binary=None, operation_id="", port=8765,
            )
            starts = []

            def start_fallback(*args, **kwargs):
                starts.append((args, kwargs))

            with patch.object(lifecycle_baseline.analytics_service, "service_state", return_value=service), \
                 patch.object(lifecycle_baseline.analytics_service, "_stop_fallback"), \
                 patch.object(lifecycle_baseline.analytics_service, "_service_runtime", return_value=Path("/fake/python")), \
                 patch.object(lifecycle_baseline.analytics_service, "_start_fallback", side_effect=start_fallback), \
                 patch.object(lifecycle_baseline.runtime_state, "discover", return_value=runtime):
                lifecycle_baseline.restore(restore_args)
                result = lifecycle_baseline.verify(restore_args)

            self.assertEqual(result["status"], "RESTORED")
            self.assertEqual(result["errors"], [])
            self.assertEqual(runtime_file.read_bytes(), original_runtime)
            self.assertEqual(unit.read_bytes(), original_unit)
            self.assertEqual(unit.stat().st_mode & 0o777, 0o640)
            self.assertEqual(runtime_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(starts), 1)
            self.assertTrue(starts[0][1]["no_bootstrap"])


if __name__ == "__main__":
    unittest.main()
