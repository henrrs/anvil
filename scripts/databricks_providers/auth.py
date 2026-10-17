"""Bounded executors for official Databricks and Azure CLI authentication."""

from __future__ import annotations

import json
import os
import select
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import owned_config, process, timeouts


def azure_cli_status(timeout: float = 5) -> tuple[bool, bool]:
    executable = shutil.which("az")
    if not executable:
        return False, False
    try:
        result = process.run([executable, "account", "show", "--only-show-errors", "--output", "json"],
                             timeout=timeout, env=owned_config.azure_login_environment())
        value = json.loads(result.stdout) if result.returncode == 0 else None
        return True, isinstance(value, dict) and bool(value.get("id"))
    except (OSError, subprocess.SubprocessError, process.ProcessFailure, json.JSONDecodeError):
        return True, False


def _timeout() -> float:
    try:
        return max(10.0, min(timeouts.seconds_for("interactive_auth_idle"),
                             float(os.environ.get("ANVIL_AUTH_TIMEOUT", "90"))))
    except ValueError:
        return 90.0


def _run_interactive(command: list[str], timeout: float, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Forward official CLI progress and enforce an inactivity watchdog."""
    if os.name != "posix":
        try:
            result = subprocess.run(command, timeout=timeout, check=False, env=env)
            return {"returncode": result.returncode}
        except subprocess.TimeoutExpired:
            return {"timeout": True}
    import pty

    master, slave = pty.openpty()
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, stdin=None, stdout=slave, stderr=slave, close_fds=True, env=env,
                                   start_new_session=True)
    except BaseException:
        os.close(master)
        os.close(slave)
        raise
    os.close(slave)
    last_progress = time.monotonic()
    open_pty = True
    try:
        while True:
            if open_pty:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        open_pty = False
                    else:
                        last_progress = time.monotonic()
                        stream = getattr(sys.stdout, "buffer", None)
                        if stream is not None:
                            stream.write(chunk)
                            stream.flush()
                        else:
                            sys.stdout.write(chunk.decode(errors="replace"))
                            sys.stdout.flush()
            code = process.poll()
            if code is not None and not open_pty:
                return {"returncode": code}
            idle_too_long = time.monotonic() - last_progress >= timeout
            total_too_long = time.monotonic() - started >= timeouts.seconds_for("interactive_auth_max")
            if idle_too_long or total_too_long:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
                return {"timeout": True}
    except KeyboardInterrupt:
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
        raise
    finally:
        os.close(master)


def run_databricks_login(binary: str, host: str, profile: str = "DEFAULT", *,
                         config_path: str | None = None) -> dict[str, Any]:
    timeout = _timeout()
    command = [binary, "auth", "login", "--host", host, "--profile", profile,
               "--timeout", f"{max(1, int(timeout))}s"]
    try:
        result = _run_interactive(command, timeout,
                                  env=owned_config.child_environment(profile=profile,
                                                                    path=Path(config_path) if config_path else None))
    except subprocess.TimeoutExpired:
        return {"status": "FAILED", "category": "AUTH_TIMEOUT"}
    except KeyboardInterrupt:
        return {"status": "CANCELLED", "category": "AUTH_CANCELLED"}
    except OSError:
        return {"status": "FAILED", "category": "AUTH_PROVIDER_UNAVAILABLE"}
    if result.get("timeout"):
        return {"status": "FAILED", "category": "AUTH_TIMEOUT"}
    return {"status": "READY" if result.get("returncode") == 0 else "FAILED",
            "category": None if result.get("returncode") == 0 else "AUTH_REQUIRED"}


def run_azure_device_login(timeout: float | None = None) -> dict[str, Any]:
    return _run_azure_login(["login", "--use-device-code"], timeout)


def run_azure_interactive_login(timeout: float | None = None) -> dict[str, Any]:
    return _run_azure_login(["login"], timeout)


def _run_azure_login(arguments: list[str], timeout: float | None) -> dict[str, Any]:
    executable = shutil.which("az")
    if not executable:
        return {"status": "FAILED", "category": "AUTH_PROVIDER_UNAVAILABLE"}
    try:
        # Azure CLI owns the official browser/device-code UX; any one-time code
        # is streamed directly to the terminal and is never stored by Anvil.
        result = _run_interactive([executable, *arguments], timeout or _timeout(),
                                  env=owned_config.azure_login_environment())
    except subprocess.TimeoutExpired:
        return {"status": "FAILED", "category": "AUTH_TIMEOUT"}
    except KeyboardInterrupt:
        return {"status": "CANCELLED", "category": "AUTH_CANCELLED"}
    except OSError:
        return {"status": "FAILED", "category": "AUTH_PROVIDER_UNAVAILABLE"}
    if result.get("timeout"):
        return {"status": "FAILED", "category": "AUTH_TIMEOUT"}
    if result.get("returncode"):
        return {"status": "FAILED", "category": "AUTH_REQUIRED"}
    _, authenticated = azure_cli_status()
    return {"status": "READY" if authenticated else "FAILED",
            "category": None if authenticated else "AUTH_REQUIRED"}
