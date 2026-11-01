#!/usr/bin/env python3
"""Install and operate the optional per-user Analytics service."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

MARKER = "# Managed by Anvil Analytics Workspace"
SERVICE_NAME = "anvil-analytics.service"
DEFAULT_PORT = 8765


def _systemd_quote(value: str) -> str:
    if any(ord(char) < 32 for char in value):
        raise ValueError("service paths cannot contain control characters")
    return '"' + value.replace("%", "%%").replace("$", "$$").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _systemd_available() -> bool:
    binary = shutil.which("systemctl")
    if not binary:
        return False
    try:
        result = subprocess.run([binary, "--user", "show-environment"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=1, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_active_user_unit_dir(systemd_dir: Path, home: Path) -> bool:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser()
    expected = (config_home / "systemd" / "user").absolute()
    return systemd_dir.expanduser().absolute() == expected


def _run_systemctl(*args: str) -> bool:
    binary = shutil.which("systemctl")
    if not binary or not _systemd_available():
        return False
    try:
        result = subprocess.run([binary, "--user", *args], check=False,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=8)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _unit_text(config: Path, home: Path, port: int) -> str:
    return "\n".join([
        MARKER,
        "[Unit]",
        "Description=Anvil Analytics Workspace",
        "After=default.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={_systemd_quote(str(config))}",
        f"Environment={_systemd_quote('HOME=' + str(home))}",
        f"Environment={_systemd_quote('ANVIL_HOME=' + str(home / '.anvil'))}",
        f"Environment={_systemd_quote('PYTHONPATH=' + str(config))}",
        f"Environment={_systemd_quote('ANVIL_ANALYTICS_PORT=' + str(port))}",
        f"ExecStart={_systemd_quote(sys.executable)} -m scripts.analytics.server --host 127.0.0.1 --port {port}",
        "Restart=on-failure",
        "RestartSec=3",
        "UMask=0077",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def _safe_unit_path(systemd_dir: Path) -> Path:
    unit_dir = systemd_dir.expanduser().absolute()
    if unit_dir.is_symlink():
        raise ValueError("systemd user unit directory is a symbolic link")
    unit_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not unit_dir.is_dir() or unit_dir.is_symlink():
        raise ValueError("systemd user unit directory is not a regular directory")
    unit_dir.chmod(0o700)
    unit = unit_dir / SERVICE_NAME
    if unit.is_symlink() or (unit.exists() and not unit.is_file()):
        raise ValueError("Analytics service unit is not a regular file")
    if unit.exists() and MARKER not in unit.read_text(encoding="utf-8", errors="replace"):
        raise ValueError("an existing user-owned Analytics service unit was left untouched")
    return unit


def sync(config: Path, home: Path, systemd_dir: Path, port: int, *, activate: bool = True) -> str:
    server = config / "scripts" / "analytics" / "server.py"
    frontend = config / "web" / "analytics" / "index.html"
    if not server.is_file() or server.is_symlink() or not frontend.is_file() or frontend.is_symlink():
        unit_dir = systemd_dir.expanduser().absolute()
        unit = unit_dir / SERVICE_NAME
        if unit_dir.is_symlink() or unit.is_symlink() or (unit.exists() and not unit.is_file()):
            raise ValueError("systemd user unit path is not a regular Anvil service file")
        if unit.exists() and MARKER in unit.read_text(encoding="utf-8", errors="replace"):
            manager_ready = _is_active_user_unit_dir(unit_dir, home) and _systemd_available()
            if manager_ready and not _run_systemctl("disable", "--now", SERVICE_NAME):
                return "STOP_PENDING"
            if not manager_ready and health(port):
                return "STOP_PENDING"
            unit.unlink()
            if manager_ready:
                _run_systemctl("daemon-reload")
            return "REMOVED"
        return "NOT_INSTALLED"
    unit = _safe_unit_path(systemd_dir)
    payload = _unit_text(config.absolute(), home.absolute(), port)
    changed = not unit.exists() or unit.read_text(encoding="utf-8") != payload
    if changed:
        fd, temporary_name = tempfile.mkstemp(prefix=".anvil-analytics.", dir=unit.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, unit)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    manager_ready = _is_active_user_unit_dir(unit.parent, home) and _systemd_available()
    if manager_ready:
        _run_systemctl("daemon-reload")
        if activate:
            if changed and _run_systemctl("is-active", SERVICE_NAME):
                _run_systemctl("restart", SERVICE_NAME)
            else:
                _run_systemctl("enable", "--now", SERVICE_NAME)
        return "READY" if _run_systemctl("is-active", SERVICE_NAME) else "CONFIGURED"
    return "CONFIGURED_PENDING_USER_SYSTEMD"


def health(port: int) -> bool:
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"Host": f"127.0.0.1:{port}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=0.5) as response:
            return response.status == 200 and b'"status":"OK"' in response.read(4096)
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sync", "start", "stop", "status"))
    parser.add_argument("--config-dir", type=Path,
                        default=Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "opencode")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--systemd-dir", type=Path,
                        default=Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd" / "user")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ANVIL_ANALYTICS_PORT", DEFAULT_PORT)))
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    config, home = args.config_dir.expanduser().absolute(), args.home.expanduser().absolute()
    try:
        if args.action == "sync":
            print(f"Analytics service {sync(config, home, args.systemd_dir, args.port, activate=not args.no_activate)}")
            return 0
        if args.action == "status":
            status = "READY" if health(args.port) else "STOPPED"
            print(f"Analytics service {status}")
            print(f"URL http://anvil.localhost:{args.port}")
            return 0 if status == "READY" else 1
        if args.action == "stop":
            if _run_systemctl("stop", SERVICE_NAME):
                print("Analytics service stopped")
                return 0
            print("No active systemd user service; stop the foreground server with Ctrl-C.")
            return 1
        if health(args.port):
            print(f"Analytics is already serving at http://anvil.localhost:{args.port}")
            return 0
        unit = args.systemd_dir / SERVICE_NAME
        if unit.is_file() and MARKER in unit.read_text(encoding="utf-8", errors="replace") and _systemd_available():
            if _run_systemctl("start", SERVICE_NAME):
                print(f"Analytics is serving at http://anvil.localhost:{args.port}")
                return 0
            print("systemd user service could not start; starting a foreground server instead.", file=sys.stderr)
        if not (config / "scripts" / "analytics" / "server.py").is_file():
            print("Analytics is not installed in the managed Anvil configuration; run make reforge or make upgrade.", file=sys.stderr)
            return 1
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(config) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
        environment["ANVIL_HOME"] = str(home / ".anvil")
        environment["ANVIL_ANALYTICS_PORT"] = str(args.port)
        print(f"Starting Anvil Analytics at http://anvil.localhost:{args.port}; press Ctrl-C to stop.", flush=True)
        return subprocess.call([sys.executable, "-m", "scripts.analytics.server", "--host", "127.0.0.1", "--port", str(args.port)],
                               cwd=config, env=environment)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Analytics service could not be managed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
