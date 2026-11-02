"""Dedicated, recoverable OpenCode process manager for Analytics."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .errors import UnavailableError
from .opencode import OpenCodeRuntimePort, create_adapter
from .paths import AnalyticsPaths
from .sessions import _read_state, _write_state, exclusive_lock

ROOT = Path(__file__).resolve().parents[2]


class AnalyticsRuntimeManager:
    def __init__(self, paths: AnalyticsPaths | None = None, *, runtime: dict[str, Any] | None = None,
                 base_url: str | None = None, adapter: OpenCodeRuntimePort | None = None,
                 process_factory=subprocess.Popen, startup_timeout: float = 45.0) -> None:
        self.paths = paths or AnalyticsPaths.discover(create=True)
        self.runtime_record = runtime
        self.configured_base_url = base_url
        self.adapter = adapter
        self.process_factory = process_factory
        self.startup_timeout = startup_timeout

    def ensure(self, *, lock: bool = True) -> dict[str, Any]:
        if lock:
            with exclusive_lock(self.paths.state / "runtime.lock"):
                return self.ensure(lock=False)
        self.paths.validate(create=True)
        record = self.runtime_record or self._discover_runtime()
        if not record or not record.get("supported", True):
            raise UnavailableError("A supported OpenCode runtime is not installed")
        generation = int(record.get("generation") or record.get("major") or 0)
        base_url = self.configured_base_url
        saved = _read_state(self.paths.runtime)
        if not base_url and saved.get("base_url"):
            if (saved.get("runtime_generation") == generation and
                    saved.get("executable", "") == record.get("executable", "")):
                base_url = saved["base_url"]
                if self.adapter is None or getattr(self.adapter, "base_url", None) != base_url:
                    self.adapter = create_adapter(generation, base_url, self.paths.workspace)
                if self.adapter.health():
                    return {**saved, "generation": generation, "base_url": base_url,
                            "executable": record.get("executable", ""), "version": record.get("version", "")}
                # A persisted URL is only an adoption candidate. Once health
                # fails, discard the adapter as well as the URL so the next
                # branch cannot accidentally re-adopt the dead process.
                base_url = None
                self.adapter = None
            else:
                # The saved process belongs to a different runtime identity.
                # Do not carry a caller-provided handle across that boundary.
                self.adapter = None

        if self.configured_base_url:
            base_url = self.configured_base_url
            if self.adapter is None:
                self.adapter = create_adapter(generation, base_url, self.paths.workspace)
        elif self.adapter is not None:
            base_url = getattr(self.adapter, "base_url", "http://127.0.0.1")
        elif not base_url:
            base_url = self._start_runtime(record)
            if self.adapter is None or getattr(self.adapter, "base_url", None) != base_url:
                self.adapter = create_adapter(generation, base_url, self.paths.workspace)
        if not self.adapter or not self.adapter.health():
            raise UnavailableError("The dedicated OpenCode runtime did not become healthy")

        result = {"schema_version": 1, "workspace": str(self.paths.workspace),
                  "base_url": base_url, "executable": str(record.get("executable", "")),
                  "version": str(record.get("version", "")), "generation": generation,
                  "runtime_generation": generation,
                  "canonical_session_id": saved.get("canonical_session_id", ""),
                  "last_validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _write_state(self.paths.runtime, result, self.paths)
        return result

    @staticmethod
    def _discover_runtime() -> dict[str, Any] | None:
        try:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/runtime_state.py"),
                                     "discover", "--format", "json"],
                                    capture_output=True, text=True, timeout=20, check=True)
            payload = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return None
        runtime = payload.get("runtime")
        return runtime if isinstance(runtime, dict) and runtime.get("supported") else None

    def _start_runtime(self, record: dict[str, Any]) -> str:
        executable = str(record.get("executable") or "")
        if not executable or not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise UnavailableError("The validated OpenCode executable is unavailable")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = os.environ.copy()
        env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
        try:
            process = self.process_factory([executable, "serve", "--hostname", "127.0.0.1",
                                            "--port", str(port)], cwd=self.paths.workspace,
                                           env=env, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True)
        except OSError as exc:
            raise UnavailableError("Could not start the dedicated OpenCode runtime") from exc
        base_url = f"http://127.0.0.1:{port}"
        generation = int(record.get("generation") or 0)
        self.adapter = create_adapter(generation, base_url, self.paths.workspace)
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.adapter.health():
                return base_url
            if process.poll() is not None:
                break
            time.sleep(0.15)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        raise UnavailableError("The dedicated OpenCode runtime failed its local health check")
