from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lifecycle_recovery
import lifecycle_transaction
from analytics.store import migration_rollback_policy


class LifecycleRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Path("/fixture/config")
        self.installation = Path("/fixture/data/installation.json")
        self.journal = {"valid": True, "operation": "anvil-upgrade", "operation_id": "op-123",
                        "phase": "snapshot-verified", "activation_started": False}

    def test_pre_activation_journal_is_abortable_without_snapshot_restore(self) -> None:
        result = lifecycle_recovery.classify(self.journal, self.config, self.installation)
        self.assertEqual(result["state"], "PRE_ACTIVATION_ABANDONED")
        self.assertEqual(result["action"], "ABORT_STAGING")

    def test_activation_and_restore_phases_require_snapshot_recovery(self) -> None:
        for phase in ("activating", "activation-completed", "post-activation-verification"):
            with self.subTest(phase=phase):
                journal = {**self.journal, "phase": phase, "activation_started": True}
                result = lifecycle_recovery.classify(journal, self.config, self.installation)
                self.assertEqual(result["action"], "RESTORE_SNAPSHOT")
        for phase in ("recovery-restoring", "recovery-verified"):
            journal = {**self.journal, "phase": phase, "activation_started": True}
            self.assertEqual(lifecycle_recovery.classify(journal, self.config, self.installation)["action"],
                             "VERIFY_OR_RESTORE")

    def test_committed_target_only_finalizes_when_installed_state_matches(self) -> None:
        journal = {**self.journal, "phase": "committing", "target_version": "2.17.1",
                   "activation_started": True}
        with patch.object(lifecycle_recovery, "_committed_target", return_value=True):
            result = lifecycle_recovery.classify(journal, self.config, self.installation)
            self.assertEqual(result["action"], "FINALIZE_TARGET")
        with patch.object(lifecycle_recovery, "_committed_target", return_value=False):
            result = lifecycle_recovery.classify(journal, self.config, self.installation)
            self.assertEqual(result["action"], "RESTORE_SNAPSHOT")

    def test_unknown_or_unidentified_journal_blocks(self) -> None:
        unknown = {**self.journal, "phase": "future-phase"}
        self.assertEqual(lifecycle_recovery.classify(unknown, self.config, self.installation)["action"], "BLOCK")
        missing_id = {**self.journal, "operation_id": ""}
        self.assertEqual(lifecycle_recovery.classify(missing_id, self.config, self.installation)["action"], "BLOCK")

    def test_schema_migrations_declare_rollback_policy_and_unknown_future_blocks(self) -> None:
        self.assertEqual(migration_rollback_policy(0, 1)["policy"], "BACKWARD_COMPATIBLE")
        self.assertFalse(migration_rollback_policy(0, 1)["restore_required"])
        self.assertEqual(migration_rollback_policy(2, 3)["policy"], "BACKUP_RESTORE_REQUIRED")
        self.assertTrue(migration_rollback_policy(2, 3)["restore_required"])
        self.assertEqual(migration_rollback_policy(3, 4)["policy"], "BACKUP_RESTORE_REQUIRED")
        self.assertTrue(migration_rollback_policy(3, 4)["restore_required"])
        self.assertEqual(migration_rollback_policy(4, 5)["policy"], "BACKUP_RESTORE_REQUIRED")
        self.assertEqual(migration_rollback_policy(5, 6)["status"], "BLOCKED")

    def test_recovery_journal_transitions_are_retryable_and_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            old = {key: os.environ.get(key) for key in ("HOME", "XDG_DATA_HOME")}
            try:
                os.environ["HOME"] = temporary
                os.environ["XDG_DATA_HOME"] = str(Path(temporary) / "data")
                lifecycle_transaction.begin("anvil-upgrade", str(Path(temporary) / "snapshot"),
                                            "2.17.0", "2.17.1", os.getpid())
                for phase in ("staging", "pre-activation-verification", "activating"):
                    lifecycle_transaction.phase(phase)
                lifecycle_transaction.phase("recovery-restoring")
                lifecycle_transaction.phase("recovery-restoring")
                lifecycle_transaction.phase("recovery-verified")
                self.assertEqual(lifecycle_transaction.inspect()["phase"], "recovery-verified")
                self.assertTrue(lifecycle_transaction.inspect()["owner_active"])
                lifecycle_transaction.clear()
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
