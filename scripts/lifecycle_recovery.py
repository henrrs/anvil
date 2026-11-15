#!/usr/bin/env python3
"""Classify interrupted lifecycle journals and verify already-restored baselines."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import lifecycle_state  # noqa: E402
import managed_config  # noqa: E402
import state as backup_state  # noqa: E402

PRE_ACTIVATION = {"snapshot-verified", "staging", "pre-activation-verification",
                  "staging-failed", "pre-activation-failed"}
RESTORE_PHASES = {"restoring-snapshot", "restoring-config", "restoring-metadata",
                  "verifying-restored-state",
                  "recovery-restoring", "recovery-verified"}
KNOWN_PHASES = {phase for phases in __import__("lifecycle_transaction").PHASE_SEQUENCES.values()
                for phase in phases} | PRE_ACTIVATION | RESTORE_PHASES | {
    "activating", "activation-completed", "post-activation-verification", "committing", "completed",
    "applying-config", "config-applied", "before-installation-metadata",
    "pre-activation-failed", "staging-failed", "snapshot-verified",
}


def _committed_target(transaction: dict[str, Any], config: Path, installation: Path) -> bool:
    target = transaction.get("target_version")
    if not isinstance(target, str) or not target:
        return False
    try:
        record = json.loads(installation.read_text(encoding="utf-8"))
        config_version = (config / "VERSION").read_text(encoding="utf-8").strip()
        if not isinstance(record, dict) or record.get("anvil_version") != target or config_version != target:
            return False
        managed_config.validate_installed(
            config, target, target, record.get("managed_config_manifest_sha256"))
        return True
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError):
        return False


def classify(transaction: dict[str, Any], config: Path, installation: Path) -> dict[str, str]:
    operation = transaction.get("operation")
    phase = transaction.get("phase")
    if (transaction.get("valid") is not True or not isinstance(operation, str)
            or not isinstance(transaction.get("operation_id"), str)
            or not transaction.get("operation_id")):
        return {"state": "LEGACY_OR_UNKNOWN", "action": "BLOCK", "reason": "journal is invalid or has no operation"}
    if phase is not None and (not isinstance(phase, str) or phase not in KNOWN_PHASES):
        return {"state": "LEGACY_OR_UNKNOWN", "action": "BLOCK", "reason": "journal phase is not recognized"}
    if phase in RESTORE_PHASES:
        return {"state": "RESTORE_IN_PROGRESS", "action": "VERIFY_OR_RESTORE",
                "reason": "restoration was already in progress"}
    activated = transaction.get("activation_started") is True or phase in {
        "activating", "activation-completed", "post-activation-verification", "committing", "completed",
        "recovery-restoring", "recovery-verified",
    }
    if operation == "anvil-upgrade" and phase in PRE_ACTIVATION and not activated:
        return {"state": "PRE_ACTIVATION_ABANDONED", "action": "ABORT_STAGING",
                "reason": "activation had not started"}
    if operation == "anvil-upgrade" and phase in {"committing", "completed"}:
        if _committed_target(transaction, config, installation):
            return {"state": "COMPLETED_BUT_NOT_FINALIZED", "action": "FINALIZE_TARGET",
                    "reason": "target config and installation record are already committed"}
    if operation in {"upgrade", "reforge", "update-runtime", "rollback"} \
            and phase == "postflight-validated":
        if _committed_target(transaction, config, installation):
            return {"state": "COMPLETED_BUT_NOT_FINALIZED", "action": "FINALIZE_TARGET",
                    "reason": "target config and installation record are already committed"}
    if operation == "anvil-upgrade" and phase in {
        "activating", "activation-completed", "post-activation-verification", "committing", "completed",
        "recovery-restoring", "recovery-verified",
    }:
        return {"state": "POST_ACTIVATION_RECOVERY", "action": "RESTORE_SNAPSHOT",
                "reason": "activation did not reach a verified committed target"}
    if operation in {"upgrade", "reforge", "update-runtime", "rollback"} and phase in KNOWN_PHASES:
        return {"state": "SNAPSHOT_RESTORE_REQUIRED", "action": "RESTORE_SNAPSHOT",
                "reason": "a supported lifecycle operation was interrupted"}
    return {"state": "LEGACY_OR_UNKNOWN", "action": "BLOCK", "reason": "journal operation or phase is not recoverable"}


def verify_baseline(backup: Path) -> dict[str, Any]:
    paths = lifecycle_state.paths()
    manifest = backup_state.verify(backup)
    previous_record = backup / "previous-installation.json"
    if previous_record.is_file():
        expected = previous_record.read_bytes()
        if not paths["record"].is_file() or paths["record"].read_bytes() != expected:
            return {"status": "RESTORATION_FAILED", "reason": "installation record differs from verified snapshot"}
        record = json.loads(expected)
        if not isinstance(record, dict):
            return {"status": "RESTORATION_FAILED", "reason": "snapshot installation record is invalid"}
        if manifest.get("previous", {}).get("config_present"):
            managed_config.validate_installed(
                paths["config"], record.get("anvil_version"), record.get("anvil_version"),
                record.get("managed_config_manifest_sha256"),
            )
    elif manifest.get("previous", {}).get("config_present"):
        return {"status": "RESTORATION_FAILED", "reason": "snapshot has no installation record"}
    elif paths["config"].exists() and any(paths["config"].iterdir()):
        return {"status": "RESTORATION_FAILED", "reason": "Anvil config remains after restoring an absent baseline"}
    return {"status": "RESTORED"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p_classify = sub.add_parser("classify")
    p_classify.add_argument("--journal-json", required=True)
    p_classify.add_argument("--config", type=Path, required=True)
    p_classify.add_argument("--installation", type=Path, required=True)
    p_verify = sub.add_parser("verify-baseline")
    p_verify.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "classify":
            transaction = json.loads(args.journal_json)
            result = classify(transaction, args.config, args.installation)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["action"] != "BLOCK" else 2
        result = verify_baseline(args.backup)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") in {"RESTORED", "RESTORED_DEGRADED_BASELINE"} else 1
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR LIFECYCLE_RECOVERY: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
