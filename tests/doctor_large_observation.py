#!/usr/bin/env python3
"""Exercise make doctor with a Lifecycle snapshot larger than ARG_MAX."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="anvil-doctor-large-") as directory:
        temp = Path(directory)
        home = temp / "home"
        shim = temp / "bin"
        for path in (home, shim, temp / "config", temp / "data", temp / "cache", temp / "state"):
            path.mkdir(parents=True, exist_ok=True)

        python_shim = shim / "python3"
        python_shim.write_text("""#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == */scripts/lifecycle_resolver.py && "${ANVIL_TEST_LARGE_OBSERVATION:-0}" == 1 ]]; then
  /usr/bin/python3 "$@" | /usr/bin/python3 -c '
import json,os,sys
data=json.load(sys.stdin)
data["test_padding"]="x" * (os.sysconf("SC_ARG_MAX") + 1024 * 1024)
json.dump(data,sys.stdout,separators=(",",":"))
'
else
  exec /usr/bin/python3 "$@"
fi
""", encoding="utf-8")
        python_shim.chmod(0o755)

        env = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(temp / "config"),
            "XDG_DATA_HOME": str(temp / "data"),
            "XDG_CACHE_HOME": str(temp / "cache"),
            "XDG_STATE_HOME": str(temp / "state"),
            "PATH": os.pathsep.join((str(shim), "/usr/bin", "/bin")),
            "ANVIL_DOCTOR_LOCAL": "1",
            "ANVIL_SKIP_RUNTIME_PROBE": "1",
            "PYTHONNOUSERSITE": "1",
        }
        baseline = subprocess.run(
            ["make", "--no-print-directory", "doctor"], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=30, check=False,
        )
        if baseline.returncode != 0:
            raise AssertionError(f"baseline doctor failed ({baseline.returncode}): {baseline.stderr}")

        large = subprocess.run(
            ["make", "--no-print-directory", "doctor"], cwd=ROOT,
            env={**env, "ANVIL_TEST_LARGE_OBSERVATION": "1"},
            capture_output=True, text=True, timeout=30, check=False,
        )
        if large.returncode != baseline.returncode:
            raise AssertionError(f"large-observation doctor exit changed: {large.returncode}: {large.stderr}")
        if large.stdout != baseline.stdout or large.stderr != baseline.stderr:
            raise AssertionError("large-observation doctor output changed from baseline")

    print("PASS make doctor accepts a Lifecycle observation larger than ARG_MAX with unchanged output")


if __name__ == "__main__":
    main()
