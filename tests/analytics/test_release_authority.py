from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from scripts.managed_config import release_checkout_changes


class ReleaseAuthorityTests(unittest.TestCase):
    def test_release_artifacts_and_lifecycle_controls_block_dirty_upgrade_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, content in {
                "VERSION": "9.1.0\n",
                "config/runtime-policy.json": '{"schema_version":1}\n',
                "scripts/analytics/runtime.py": "runtime = 'release'\n",
                "scripts/anvil_upgrade.sh": "upgrade = 'release'\n",
                "scripts/analytics_service.py": "service = 'release'\n",
                "README.md": "docs\n",
            }.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            inventory = {
                "schema_version": 1,
                "managed_artifacts": {"release": "9.1.0", "files": {
                    "VERSION": "0" * 64,
                    "config/runtime-policy.json": "1" * 64,
                    "scripts/analytics/runtime.py": "2" * 64,
                    "opencode.jsonc": None,
                }},
            }
            (root / "config" / "managed-inventory.json").write_text(
                json.dumps(inventory) + "\n", encoding="utf-8")
            git_env = {"GIT_AUTHOR_NAME": "Anvil test", "GIT_AUTHOR_EMAIL": "anvil-test@example.invalid",
                       "GIT_COMMITTER_NAME": "Anvil test", "GIT_COMMITTER_EMAIL": "anvil-test@example.invalid"}
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "--quiet", "-m", "fixture"],
                           check=True, env={**os.environ, **git_env})

            controls = {"scripts/anvil_upgrade.sh", "scripts/analytics_service.py"}
            self.assertEqual(release_checkout_changes(root, test_mode=False, control_files=controls), [])
            (root / "scripts/analytics/runtime.py").write_text("runtime = 'uncommitted'\n", encoding="utf-8")
            self.assertEqual(release_checkout_changes(root, test_mode=False, control_files=controls),
                             ["scripts/analytics/runtime.py"])
            self.assertEqual(release_checkout_changes(root, test_mode=True), [])
            (root / "scripts/analytics/runtime.py").write_text("runtime = 'release'\n", encoding="utf-8")
            (root / "scripts/anvil_upgrade.sh").write_text("upgrade = 'uncommitted'\n", encoding="utf-8")
            self.assertEqual(release_checkout_changes(root, test_mode=False, control_files=controls),
                             ["scripts/anvil_upgrade.sh"])
            (root / "scripts/anvil_upgrade.sh").write_text("upgrade = 'release'\n", encoding="utf-8")
            (root / "README.md").write_text("documentation update\n", encoding="utf-8")
            self.assertEqual(release_checkout_changes(root, test_mode=False, control_files=controls), [])
            controlled = root / "scripts/anvil_upgrade.sh"
            controlled.unlink()
            controlled.symlink_to(root / "scripts/analytics_service.py")
            self.assertEqual(release_checkout_changes(root, test_mode=False, control_files=controls),
                             ["scripts/anvil_upgrade.sh"])


if __name__ == "__main__":
    unittest.main()
