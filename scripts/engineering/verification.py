"""Explicit, bounded command checks; never execute work during resume."""

from __future__ import annotations

import hashlib
import os
import selectors
import signal
import subprocess
import time
from pathlib import Path


def run(argv: list[str], root: Path, timeout: int) -> dict:
    started = time.monotonic()
    digest = hashlib.sha256()
    size = 0
    reason = None
    try:
        process = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    except OSError:
        return {"result": "FAIL", "returncode": None, "reason": "CHECK_EXECUTABLE_UNAVAILABLE", "elapsed_ms": 0}
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            if time.monotonic() - started > timeout:
                reason = "CHECK_TIMEOUT"
                break
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    break
                digest.update(chunk)
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    reason = "CHECK_OUTPUT_LIMIT"
                    break
            if reason:
                break
        # A process may close its output while continuing to run.
        if not reason:
            try:
                process.wait(timeout=max(0.1, timeout - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                reason = "CHECK_TIMEOUT"
    finally:
        selector.close()
        if process.poll() is None or reason:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            if reason:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        process.stdout.close()
    return {"result": "PASS" if not reason and process.returncode == 0 else "FAIL",
            "returncode": process.returncode, "reason": reason,
            "output_sha256": digest.hexdigest(), "output_bytes": size,
            "elapsed_ms": round((time.monotonic() - started) * 1000)}
