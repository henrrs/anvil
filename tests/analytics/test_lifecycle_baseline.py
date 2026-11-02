from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from scripts import lifecycle_baseline


class LifecycleBaselineTests(unittest.TestCase):
    def test_recovery_verification_detects_missing_legacy_profile_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            config = root / "config" / "opencode"
            backup = root / "backup"
            systemd = root / "config" / "systemd" / "user"
            installation = root / "data" / "anvil" / "installation.json"
            runtime_file = home / ".anvil" / "analytics" / "runtime.json"
            for path in (config, systemd, installation.parent, runtime_file.parent, backup):
                path.mkdir(parents=True, exist_ok=True)
            (config / "opencode.jsonc").write_text('{"agent":{}}\n', encoding="utf-8")
            installation.write_text('{"schema_version":3,"anvil_version":"2.17.0"}\n', encoding="utf-8")
            service = {"installed": False, "unit_installed": False, "enabled": False,
                       "active": False, "healthy": False, "status": "NOT_READY"}
            capture_args = Namespace(
                backup=backup, config_dir=config, home=home, data_root=root / "data",
                installation=installation, analytics_runtime_state=runtime_file,
                systemd_dir=systemd, binary=None, python="python3", port=8765,
            )
            with patch.object(lifecycle_baseline.runtime_state, "discover", return_value={"runtime": None}), \
                 patch.object(lifecycle_baseline.analytics_service, "service_state", return_value=service), \
                 patch.object(lifecycle_baseline.analytics_service, "_is_active_user_unit_dir", return_value=False), \
                 contextlib.redirect_stdout(io.StringIO()):
                lifecycle_baseline.capture(capture_args)

            self.assertIsNone(json.loads((backup / "lifecycle-baseline" / "pre-operation-state.json").read_text())
                              ["managed_manifest_sha256"])
            profile = config / "opencode.jsonc"
            original_profile = profile.read_bytes()
            profile.write_text('{"agent":{"changed":true}}\n', encoding="utf-8")
            verify_args = Namespace(
                backup=backup, config_dir=config, home=home, installation=installation,
                analytics_runtime_state=runtime_file, systemd_dir=systemd,
                binary=None, operation_id="", port=8765,
            )
            with patch.object(lifecycle_baseline.runtime_state, "discover", return_value={"runtime": None}), \
                 patch.object(lifecycle_baseline.analytics_service, "service_state", return_value=service):
                interrupted = lifecycle_baseline.verify(verify_args, strict_configuration=True)
            self.assertIn("OpenCode configuration profile differs from the captured baseline", interrupted["errors"])

            profile.write_bytes(original_profile)
            for path in config.iterdir():
                path.unlink()
            config.rmdir()
            with patch.object(lifecycle_baseline.runtime_state, "discover", return_value={"runtime": None}), \
                 patch.object(lifecycle_baseline.analytics_service, "service_state", return_value=service):
                result = lifecycle_baseline.verify(verify_args)

            self.assertEqual(result["status"], "RESTORATION_FAILED")
            self.assertIn("configuration directory presence differs from the captured baseline", result["errors"])

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
            with sqlite3.connect(runtime_file.parent / "context.db") as connection:
                connection.execute("CREATE TABLE created_during_failed_migration(value TEXT)")

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

            self.assertEqual(result["status"], "RESTORED", result["errors"])
            self.assertEqual(result["errors"], [])
            self.assertEqual(runtime_file.read_bytes(), original_runtime)
            self.assertEqual(unit.read_bytes(), original_unit)
            self.assertFalse((runtime_file.parent / "context.db").exists(),
                             "rollback must remove a control database created after an absent baseline")
            self.assertEqual(unit.stat().st_mode & 0o777, 0o640)
            self.assertEqual(runtime_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(starts), 1)
            self.assertTrue(starts[0][1]["no_bootstrap"])

    def test_schema_migration_snapshot_restores_sqlite_baseline_before_service_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            config = root / "config" / "opencode"
            backup = root / "backup"
            systemd = root / "config" / "systemd" / "user"
            installation = root / "data" / "anvil" / "installation.json"
            runtime_file = home / ".anvil" / "analytics" / "runtime.json"
            database = runtime_file.parent / "context.db"
            for path in (config, systemd, installation.parent, runtime_file.parent, backup):
                path.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                connection.executemany("INSERT INTO schema_migrations VALUES(?, 'baseline')", [(1,), (2,)])
                connection.execute("CREATE TABLE control_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("INSERT INTO control_state VALUES('key', 'before')")

            installation.write_text('{"schema_version":3,"anvil_version":"2.17.0"}\n', encoding="utf-8")
            service = {"installed": False, "unit_installed": False, "enabled": False,
                       "active": False, "healthy": False, "status": "NOT_READY"}
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

            baseline_path = backup / "lifecycle-baseline" / "pre-operation-state.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            db_baseline = baseline["analytics"]["context_database"]
            self.assertEqual(db_baseline["schema_version"], 2)
            self.assertEqual(db_baseline["target_schema_version"], lifecycle_baseline.analytics_schema.SCHEMA_VERSION)
            self.assertEqual(db_baseline["rollback_policy"], "BACKUP_RESTORE_REQUIRED")
            snapshot = backup / "lifecycle-baseline" / "context.db"
            self.assertTrue(snapshot.is_file())
            lifecycle_baseline.analytics_schema.verify_snapshot(db_baseline, snapshot)

            with sqlite3.connect(database) as connection:
                connection.execute("ALTER TABLE control_state ADD COLUMN migrated TEXT DEFAULT 'yes'")
                connection.execute("INSERT INTO schema_migrations VALUES(3, 'target')")
                connection.execute("UPDATE control_state SET value='after'")

            restore_args = Namespace(
                backup=backup, config_dir=config, home=home, installation=installation,
                analytics_runtime_state=runtime_file, systemd_dir=systemd,
                binary=None, operation_id="", port=8765,
            )
            with patch.object(lifecycle_baseline.analytics_service, "_stop_fallback"), \
                 patch.object(lifecycle_baseline.analytics_service, "_service_runtime", return_value=Path("/fake/python")), \
                 patch.object(lifecycle_baseline.analytics_service, "_start_fallback"), \
                 patch.object(lifecycle_baseline.runtime_state, "discover", return_value=runtime):
                lifecycle_baseline.restore(restore_args)
                result = lifecycle_baseline.verify(restore_args)

            self.assertEqual(result["status"], "RESTORED_DEGRADED_BASELINE", result["errors"])
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT value FROM control_state WHERE key='key'").fetchone()[0], "before")
                self.assertEqual(connection.execute("PRAGMA quick_check(1)").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
