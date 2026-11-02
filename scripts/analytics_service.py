#!/usr/bin/env python3
"""Install and operate the managed per-user Analytics service."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from .analytics_dependencies import DependencyError, _validate, parse_lock, runtime_path
except ImportError:
    from analytics_dependencies import DependencyError, _validate, parse_lock, runtime_path

MARKER = "# Managed by Anvil Analytics Workspace"
SERVICE_NAME = "anvil-analytics.service"
DEFAULT_PORT = 8765


def _systemd_quote(value: str) -> str:
    if any(ord(char) < 32 for char in value):
        raise ValueError("service paths cannot contain control characters")
    return '"' + value.replace("%", "%%").replace("$", "$$").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _systemd_path(value: str) -> str:
    """Escape a systemd path directive without quotes (quotes become path data)."""
    if any(ord(char) < 32 for char in value):
        raise ValueError("service paths cannot contain control characters")
    return value.replace("%", "%%").replace("\\", "\\x5c").replace(" ", "\\x20").replace('"', "\\x22")


def _systemd_available() -> bool:
    binary = shutil.which("systemctl")
    if not binary:
        return False
    try:
        result = subprocess.run([binary, "--user", "show-environment"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=1, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _is_active_user_unit_dir(systemd_dir: Path, home: Path) -> bool:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser()
    return systemd_dir.expanduser().absolute() == (config_home / "systemd" / "user").absolute()


def _run_systemctl(*args: str) -> bool:
    binary = shutil.which("systemctl")
    if not binary or not _systemd_available():
        return False
    try:
        result = subprocess.run([binary, "--user", *args], check=False,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=8)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _systemctl_value(*args: str) -> str:
    binary = shutil.which("systemctl")
    if not binary or not _systemd_available():
        return ""
    try:
        result = subprocess.run([binary, "--user", *args], check=False,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _data_home(home: Path) -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share"))).expanduser().absolute()


def _service_runtime(config: Path, home: Path, *, require_ready: bool) -> Path:
    lock = config / "runtime" / "analytics-requirements.lock"
    if not lock.is_file():
        return Path(sys.executable)
    try:
        target = runtime_path(lock, _data_home(home), sys.executable) / "bin" / "python"
    except DependencyError:
        if require_ready:
            raise
        return Path(sys.executable)
    if require_ready and (not target.is_file() or not os.access(target, os.X_OK)):
        raise ValueError("Analytics dependencies are not prepared; run make upgrade")
    return target


def _unit_text(config: Path, home: Path, port: int, interpreter: Path | None = None) -> str:
    python = interpreter or Path(sys.executable)
    data_home = _data_home(home)
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser().absolute()
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local" / "state"))).expanduser().absolute()
    anvil_home = Path(os.environ.get("ANVIL_HOME", str(home / ".anvil"))).expanduser().absolute()
    return "\n".join([
        MARKER,
        "[Unit]",
        "Description=Anvil Analytics Workspace",
        "After=default.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={_systemd_path(str(config))}",
        f"Environment={_systemd_quote('HOME=' + str(home))}",
        f"Environment={_systemd_quote('ANVIL_HOME=' + str(anvil_home))}",
        f"Environment={_systemd_quote('XDG_CONFIG_HOME=' + str(config_home))}",
        f"Environment={_systemd_quote('XDG_DATA_HOME=' + str(data_home))}",
        f"Environment={_systemd_quote('XDG_STATE_HOME=' + str(state_home))}",
        f"Environment={_systemd_quote('PYTHONPATH=' + str(config))}",
        f"Environment={_systemd_quote('ANVIL_ANALYTICS_PORT=' + str(port))}",
        f"ExecStart={_systemd_quote(str(python))} -m scripts.analytics.server --host 127.0.0.1 --port {port}",
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


def _verify_unit_payload(payload: str, *, verify_interpreter: Path | None = None,
                         configured_interpreter: Path | None = None) -> None:
    """Validate systemd syntax before publishing or activating a generated unit."""
    binary = shutil.which("systemd-analyze")
    if not binary:
        return
    candidate = payload
    if verify_interpreter is not None:
        lines = candidate.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("ExecStart="):
                expected = ("ExecStart=" + _systemd_quote(str(configured_interpreter))
                            if configured_interpreter is not None else "")
                if not expected or not line.startswith(expected):
                    raise ValueError("Analytics unit candidate has an unexpected ExecStart executable")
                lines[index] = "ExecStart=" + _systemd_quote(str(verify_interpreter)) + line[len(expected):]
                break
        else:
            raise ValueError("Analytics unit candidate is missing ExecStart")
        candidate = "\n".join(lines) + "\n"
    with tempfile.TemporaryDirectory(prefix="anvil-systemd-verify.") as directory:
        unit = Path(directory) / SERVICE_NAME
        unit.write_text(candidate, encoding="utf-8")
        unit.chmod(0o600)
        try:
            result = subprocess.run([binary, "--user", "verify", str(unit)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("systemd could not validate the generated Analytics unit") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip().splitlines()
        detail = details[-1] if details else "invalid systemd unit"
        raise ValueError(f"systemd rejected the generated Analytics unit: {detail}")


def _port_owner_pids(port: int) -> list[int]:
    binary = shutil.which("ss")
    if not binary:
        return []
    try:
        result = subprocess.run([binary, "-ltnpH", f"sport = :{port}"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({int(value) for value in re.findall(r"pid=(\d+)", result.stdout)})


def _is_legacy_anvil_process(pid: int, config: Path, port: int) -> bool:
    proc = Path("/proc") / str(pid)
    try:
        if proc.stat().st_uid != os.getuid():
            return False
        argv = [part.decode("utf-8", errors="replace") for part in (proc / "cmdline").read_bytes().split(b"\0") if part]
        if not any("scripts.analytics.server" in part or "scripts/analytics/server.py" in part for part in argv):
            return False
        if not any(value == str(port) or value == f"--port={port}" for value in argv):
            return False
        return Path(os.readlink(proc / "cwd")).resolve() == config.resolve()
    except (OSError, RuntimeError):
        return False


def _migrate_legacy_listener(config: Path, port: int) -> None:
    """Stop only a same-user legacy Anvil foreground listener with verified identity."""
    if not _port_open(port):
        return
    pids = _port_owner_pids(port)
    if not pids or any(not _is_legacy_anvil_process(pid, config, port) for pid in pids):
        raise ValueError(f"Port {port} is already occupied by an unknown process; Anvil left it untouched")
    for pid in pids:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _port_open(port):
        time.sleep(0.1)
    if _port_open(port):
        raise ValueError(f"Legacy Anvil Analytics listener on port {port} did not stop cleanly")


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


def _fallback_paths(home: Path, *, create: bool = True) -> tuple[Path, Path, Path]:
    root = _data_home(home) / "anvil" / "analytics"
    logs = root / "logs"
    if create:
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if root.is_symlink():
            raise ValueError("Analytics service state directory must not be a symbolic link")
        root.chmod(0o700)
        logs.mkdir(parents=True, mode=0o700, exist_ok=True)
        logs.chmod(0o700)
    return root / "service.pid", root / "service.lock", logs / "service.log"


def _managed_pid(pid_file: Path, port: int) -> int | None:
    try:
        value = json.loads(pid_file.read_text(encoding="utf-8"))
        pid = int(value.get("pid", 0))
        if value.get("port") != port or pid <= 1:
            return None
        os.kill(pid, 0)
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        if b"scripts.analytics.server" not in command or str(port).encode() not in command:
            return None
        return pid
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_pid(path: Path, pid: int, port: int) -> None:
    fd, name = tempfile.mkstemp(prefix=".service.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": pid, "port": port}, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _http_json(port: int, path: str, timeout: float = 1.0) -> dict[str, object] | None:
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         headers={"Host": f"127.0.0.1:{port}", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read(64 * 1024).decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def health(port: int) -> bool:
    value = _http_json(port, "/api/health", timeout=0.5)
    return bool(value and value.get("status") == "OK" and value.get("service") == "anvil-analytics")


def service_state(config: Path, home: Path, systemd_dir: Path, port: int) -> dict[str, object]:
    unit = systemd_dir.expanduser().absolute() / SERVICE_NAME
    unit_installed = unit.is_file() and not unit.is_symlink() and MARKER in unit.read_text(encoding="utf-8", errors="replace")
    installed = (config / "scripts" / "analytics" / "server.py").is_file() and not (config / "scripts" / "analytics" / "server.py").is_symlink()
    manager = _is_active_user_unit_dir(systemd_dir, home) and _systemd_available()
    if manager and unit_installed:
        enabled = _systemctl_value("is-enabled", SERVICE_NAME) == "enabled"
        active_state = _systemctl_value("is-active", SERVICE_NAME)
        try:
            main_pid = int(_systemctl_value("show", "-p", "MainPID", "--value", SERVICE_NAME) or "0")
        except ValueError:
            main_pid = 0
        active = active_state == "active" and main_pid > 0
    else:
        pid_file, _, _ = _fallback_paths(home, create=False)
        main_pid = _managed_pid(pid_file, port) or 0
        enabled = False
        active = main_pid > 0
    healthy = health(port) if active else False
    return {"installed": bool(installed), "unit_installed": bool(unit_installed), "enabled": enabled, "active": active,
            "main_pid": main_pid, "healthy": healthy,
            "status": "READY" if installed and active and healthy and (enabled or not manager) else "NOT_READY"}


def _start_fallback(config: Path, home: Path, port: int, python: Path, *, no_bootstrap: bool = False) -> None:
    pid_file, lock_file, log_file = _fallback_paths(home)
    with lock_file.open("a", encoding="utf-8") as lock_stream:
        os.chmod(lock_file, 0o600)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        if _managed_pid(pid_file, port):
            return
        if _port_open(port):
            if health(port):
                raise ValueError("Analytics responds on the configured port but is not owned by its managed service")
            raise ValueError(f"Port {port} is already occupied by another process")
        environment = os.environ.copy()
        environment.update({"HOME": str(home), "ANVIL_HOME": os.environ.get("ANVIL_HOME", str(home / ".anvil")),
                            "XDG_CONFIG_HOME": os.environ.get("XDG_CONFIG_HOME", str(home / ".config")),
                            "XDG_DATA_HOME": str(_data_home(home)),
                            "XDG_STATE_HOME": os.environ.get("XDG_STATE_HOME", str(home / ".local" / "state")),
                            "PYTHONPATH": str(config) + (os.pathsep + environment.get("PYTHONPATH", "")),
                            "ANVIL_ANALYTICS_PORT": str(port)})
        if no_bootstrap:
            environment["ANVIL_ANALYTICS_NO_BOOTSTRAP"] = "1"
        with log_file.open("ab") as output:
            os.chmod(log_file, 0o600)
            process = subprocess.Popen([str(python), "-m", "scripts.analytics.server",
                                        "--host", "127.0.0.1", "--port", str(port)],
                                       cwd=config, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
                                       close_fds=True)
        _write_pid(pid_file, process.pid, port)


def _wait_converged(port: int, timeout: float = 90) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health_value = _http_json(port, "/api/health", timeout=1)
        runtime = _http_json(port, "/api/runtime", timeout=2)
        if health_value and health_value.get("status") == "OK" and runtime:
            opencode = runtime.get("opencode") or runtime.get("runtime") or {}
            canonical = runtime.get("canonical_session") or opencode.get("canonical_session")
            if isinstance(canonical, dict):
                canonical = canonical.get("status")
            if opencode.get("status") == "READY" and canonical in {"READY", "PRESENT"}:
                return True
        time.sleep(0.5)
    return False


def _stop_fallback(home: Path, port: int) -> bool:
    pid_file, _, _ = _fallback_paths(home, create=False)
    pid = _managed_pid(pid_file, port)
    if not pid:
        pid_file.unlink(missing_ok=True)
        return False
    os.kill(pid, 15)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    pid_file.unlink(missing_ok=True)
    return True


def sync(config: Path, home: Path, systemd_dir: Path, port: int, *, activate: bool = True) -> str:
    server = config / "scripts" / "analytics" / "server.py"
    frontend = config / "web" / "analytics" / "index.html"
    unit_path = systemd_dir.expanduser().absolute() / SERVICE_NAME
    if not server.is_file() or server.is_symlink() or not frontend.is_file() or frontend.is_symlink():
        if unit_path.is_symlink() or (unit_path.exists() and not unit_path.is_file()):
            raise ValueError("systemd user unit path is not a regular Anvil service file")
        if unit_path.exists() and MARKER in unit_path.read_text(encoding="utf-8", errors="replace"):
            manager = _is_active_user_unit_dir(unit_path.parent, home) and _systemd_available()
            if manager and not _run_systemctl("disable", "--now", SERVICE_NAME):
                return "STOP_PENDING"
            if not manager and not _stop_fallback(home, port) and health(port):
                return "STOP_PENDING"
            unit_path.unlink()
            if manager and not _run_systemctl("daemon-reload"):
                raise ValueError("systemd daemon-reload failed while removing Analytics")
            return "REMOVED"
        return "NOT_INSTALLED"
    unit = _safe_unit_path(systemd_dir)
    manager = _is_active_user_unit_dir(unit.parent, home) and _systemd_available()
    python = _service_runtime(config, home, require_ready=activate)
    payload = _unit_text(config.absolute(), home.absolute(), port, python)
    if not config.is_absolute() or not config.is_dir():
        raise ValueError("Analytics service WorkingDirectory must be an existing absolute config directory")
    verify_interpreter = None
    if not python.is_file() or not os.access(python, os.X_OK):
        if activate:
            raise ValueError("Analytics service interpreter is unavailable")
        # A non-activating sync may describe a content-addressed runtime that
        # has not been staged yet. Validate unit syntax with this interpreter
        # while preserving the configured ExecStart for the eventual target.
        verify_interpreter = Path(sys.executable)
    _verify_unit_payload(payload, verify_interpreter=verify_interpreter,
                         configured_interpreter=python if verify_interpreter is not None else None)
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
    if not activate:
        return "CONFIGURED_PENDING_USER_SYSTEMD" if not manager else "CONFIGURED"
    if manager:
        already_active = _systemctl_value("is-active", SERVICE_NAME) == "active"
        if not already_active:
            _migrate_legacy_listener(config.absolute(), port)
        if not _run_systemctl("daemon-reload"):
            raise ValueError("systemd daemon-reload failed; Analytics service was not converged")
        if changed and already_active:
            if not _run_systemctl("enable", SERVICE_NAME):
                raise ValueError("systemd could not enable the Analytics service")
            if not _run_systemctl("restart", SERVICE_NAME):
                raise ValueError("systemd could not restart the Analytics service")
        elif not _run_systemctl("enable", "--now", SERVICE_NAME):
            raise ValueError("systemd could not enable and start the Analytics service")
        state = service_state(config, home, unit.parent, port)
        if not state["installed"] or not state["enabled"] or not state["active"]:
            raise ValueError("Analytics systemd unit is not enabled and active with a live MainPID")
    else:
        if changed:
            _stop_fallback(home, port)
        if not _managed_pid(_fallback_paths(home, create=False)[0], port):
            _migrate_legacy_listener(config.absolute(), port)
        _start_fallback(config, home, port, python)
    if not _wait_converged(port):
        raise ValueError("Analytics service did not reach READY (service, OpenCode runtime, and canonical session)")
    return "READY"


def validate_candidate(config: Path, home: Path, systemd_dir: Path, port: int,
                       interpreter: Path | None = None) -> dict[str, str]:
    """Validate the target service artifacts without writing a unit or starting a process."""
    server = config / "scripts" / "analytics" / "server.py"
    frontend = config / "web" / "analytics" / "index.html"
    if not server.is_file() or server.is_symlink() or not frontend.is_file() or frontend.is_symlink():
        raise ValueError("Analytics target server or frontend artifact is missing or unsafe")
    staged_python = interpreter or _service_runtime(config, home, require_ready=True)
    if not staged_python.is_file() or not os.access(staged_python, os.X_OK):
        raise ValueError("Analytics service candidate interpreter is unavailable")
    # The verification runs against the staged interpreter. The installed unit
    # must reference the content-addressed final path that receives it during
    # activation; the hidden staging directory is atomically renamed away.
    service_python = _service_runtime(config, home, require_ready=False)
    generated = _unit_text(config.absolute(), home.absolute(), port, service_python)
    if not config.is_absolute() or not config.is_dir():
        raise ValueError("Analytics service WorkingDirectory must be an existing absolute config directory")
    lock = config / "runtime" / "analytics-requirements.lock"
    packages = parse_lock(lock)[1] if lock.is_file() and not lock.is_symlink() else []
    if not _validate(staged_python, packages):
        raise ValueError("Analytics staged interpreter failed execution, venv-prefix, or import validation")
    staged_root = staged_python.parent.parent.resolve()
    target_root = service_python.parent.parent.absolute()
    if staged_root != target_root.resolve() and staged_root.parent != target_root.parent.resolve():
        raise ValueError("Analytics staged interpreter is not a sibling of its content-addressed target")
    unit_dir = systemd_dir.expanduser().absolute()
    unit = unit_dir / SERVICE_NAME
    if unit_dir.is_symlink() or (unit_dir.exists() and not unit_dir.is_dir()):
        raise ValueError("Analytics service unit directory is unsafe")
    if unit.is_symlink() or (unit.exists() and not unit.is_file()):
        raise ValueError("Analytics target service unit path is unsafe")
    if unit.exists() and MARKER not in unit.read_text(encoding="utf-8", errors="replace"):
        raise ValueError("an existing user-owned Analytics service unit was left untouched")
    if f"ExecStart={_systemd_quote(str(service_python))}" not in generated:
        raise ValueError("Analytics service candidate does not use the activated runtime path")
    _verify_unit_payload(generated, verify_interpreter=staged_python,
                         configured_interpreter=service_python)
    return {"status": "PASS", "interpreter": str(staged_python),
            "service_interpreter": str(service_python), "unit": str(unit)}


def _print_state(state: dict[str, object], port: int) -> None:
    print("Anvil Analytics service")
    print(f"  installed  {'YES' if state['installed'] else 'NO'}")
    print(f"  enabled    {'YES' if state['enabled'] else 'NO'}")
    print(f"  active     {'YES' if state['active'] else 'NO'}")
    print(f"  MainPID    {state['main_pid']}")
    print(f"  health     {'READY' if state['healthy'] else 'NOT_READY'}")
    print(f"  URL        http://anvil.localhost:{port}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sync", "start", "dev", "stop", "status"))
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
            state = service_state(config, home, args.systemd_dir, args.port)
            _print_state(state, args.port)
            return 0 if state["status"] == "READY" else 1
        if args.action == "stop":
            if _is_active_user_unit_dir(args.systemd_dir, home) and _systemd_available():
                if _run_systemctl("stop", SERVICE_NAME):
                    print("Analytics service stopped")
                    return 0
            if _stop_fallback(home, args.port):
                print("Analytics service stopped")
                return 0
            print("No managed Analytics service is active.")
            return 1
        if args.action == "dev":
            if not (config / "scripts" / "analytics" / "server.py").is_file():
                print("Analytics is not installed; run make upgrade.", file=sys.stderr)
                return 1
            if _port_open(args.port):
                print(f"Port {args.port} is already occupied; stop its owner before using analytics-dev.", file=sys.stderr)
                return 1
            environment = os.environ.copy()
            environment.update({"PYTHONPATH": str(config),
                                "ANVIL_HOME": os.environ.get("ANVIL_HOME", str(home / ".anvil")),
                                "ANVIL_ANALYTICS_PORT": str(args.port)})
            return subprocess.call([sys.executable, "-m", "scripts.analytics.server", "--host",
                                    "127.0.0.1", "--port", str(args.port)], cwd=config, env=environment)
        result = sync(config, home, args.systemd_dir, args.port, activate=True)
        if result == "READY":
            print("Anvil Analytics READY")
            print(f"URL: http://anvil.localhost:{args.port}")
            return 0
        print(f"Analytics service {result}")
        return 1
    except (OSError, ValueError, DependencyError, subprocess.SubprocessError) as exc:
        print(f"Analytics service could not be converged: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
