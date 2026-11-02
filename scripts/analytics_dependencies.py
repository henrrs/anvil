#!/usr/bin/env python3
"""Stage the release-pinned Analytics runtime with safe package-source policy."""

from __future__ import annotations

import argparse
import configparser
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

MIN_PYTHON = (3, 11)
PACKAGE_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$")
REQUIRED = {"duckdb", "pyarrow"}
PUBLIC_INDEX = "https://pypi.org/simple"
PACKAGE_CODES = {
    "PACKAGE_NOT_FOUND", "VERSION_NOT_FOUND", "REGISTRY_UNAVAILABLE", "NETWORK_BLOCKED", "AUTHENTICATION_FAILED",
    "TLS_FAILURE", "PROXY_FAILURE", "NETWORK_FAILURE", "RESOLUTION_CONFLICT", "WHEEL_NOT_AVAILABLE",
    "PYTHON_VERSION_INCOMPATIBLE", "INSTALLER_FAILURE", "IMPORT_VALIDATION_FAILED", "DISK_FAILURE",
    "UNKNOWN_INSTALL_FAILURE",
}


@dataclass(frozen=True)
class PackageSource:
    index_url: str
    source_type: str
    label: str
    trusted_hosts: tuple[str, ...] = ()

    def public(self) -> dict[str, object]:
        return {"source_type": self.source_type, "label": self.label}


@dataclass(frozen=True)
class PackageResolutionPolicy:
    primary: PackageSource
    public_fallback: bool
    fallback_source: PackageSource | None
    policy: str
    configured_by: str
    ignored_extra_indexes: int = 0

    def public(self) -> dict[str, object]:
        return {
            "policy": self.policy,
            "configured_by": self.configured_by,
            "primary": self.primary.public(),
            "corporate_registry_configured": self.primary.source_type == "CORPORATE_REGISTRY",
            "selected_source": self.primary.public(),
            "public_fallback": "enabled" if self.public_fallback else "disabled",
            "fallback_source": self.fallback_source.public() if self.fallback_source else None,
            "ignored_extra_indexes": self.ignored_extra_indexes,
            "availability": "NOT_CHECKED",
        }

    def sources(self) -> tuple[PackageSource, ...]:
        return (self.primary, self.fallback_source) if self.fallback_source else (self.primary,)


class DependencyError(RuntimeError):
    def __init__(self, dependency: str, message: str, *, version: str = "", reason_code: str = "UNKNOWN_INSTALL_FAILURE",
                 stage: str = "package installation", python: str = "", registry: str = "unknown",
                 log_path: str = "", public_fallback: str = "disabled") -> None:
        super().__init__(message)
        self.dependency = dependency
        self.version = version
        self.reason_code = reason_code if reason_code in PACKAGE_CODES else "UNKNOWN_INSTALL_FAILURE"
        self.stage = stage
        self.python = python
        self.registry = registry
        self.log_path = log_path
        self.public_fallback = public_fallback

    def public(self) -> dict[str, str]:
        return {"dependency": self.dependency, "version": self.version, "reason_code": self.reason_code,
                "stage": self.stage, "python": self.python, "registry": self.registry,
                "public_fallback": self.public_fallback, "log_path": self.log_path}


def parse_lock(path: Path) -> tuple[str, list[tuple[str, str]]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DependencyError("manifest", "the Analytics dependency manifest is missing",
                              reason_code="PACKAGE_NOT_FOUND", stage="manifest validation") from exc
    release = ""
    packages: list[tuple[str, str]] = []
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("# anvil-release:"):
            release = line.split(":", 1)[1].strip()
        elif line and not line.startswith("#"):
            match = PACKAGE_LINE.fullmatch(line)
            if not match:
                raise DependencyError("manifest", "the Analytics dependency manifest is invalid",
                                      reason_code="INSTALLER_FAILURE", stage="manifest validation")
            packages.append((match.group(1).lower().replace("_", "-"), match.group(2)))
    if not release or not REQUIRED.issubset({name for name, _ in packages}):
        raise DependencyError("manifest", "the Analytics dependency manifest is incomplete",
                              reason_code="INSTALLER_FAILURE", stage="manifest validation")
    if len({name for name, _ in packages}) != len(packages):
        raise DependencyError("manifest", "the Analytics dependency manifest contains duplicate packages",
                              reason_code="INSTALLER_FAILURE", stage="manifest validation")
    return release, packages


def _pip_config(home: Path, env: dict[str, str]) -> tuple[str, list[str], list[str], str]:
    """Read existing pip settings without changing them or returning secrets to renderers."""
    candidates: list[Path] = []
    if env.get("PIP_CONFIG_FILE"):
        if env["PIP_CONFIG_FILE"] not in {os.devnull, "/dev/null"}:
            candidates.append(Path(env["PIP_CONFIG_FILE"]).expanduser())
    else:
        candidates.append(Path("/etc/pip.conf"))
        if env.get("VIRTUAL_ENV"):
            candidates.append(Path(env["VIRTUAL_ENV"]) / "pip.conf")
        candidates.extend((
            Path(env.get("XDG_CONFIG_HOME", str(home / ".config"))) / "pip" / "pip.conf",
            home / ".pip" / "pip.conf",
        ))
    indexes: list[tuple[str, str]] = []
    extras: list[str] = []
    trusted: list[str] = []
    for path in candidates:
        if not path.is_file():
            continue
        parser = configparser.RawConfigParser(interpolation=None, strict=False)
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error, UnicodeError):
            continue
        for section in ("global", "install"):
            if not parser.has_section(section):
                continue
            index = parser.get(section, "index-url", fallback="").strip()
            if index:
                indexes.append((index, "pip.conf"))
            value = parser.get(section, "extra-index-url", fallback="").strip()
            if value:
                extras.extend(value.split())
            value = parser.get(section, "trusted-host", fallback="").strip()
            if value:
                trusted.extend(value.split())
    if env.get("PIP_TRUSTED_HOST"):
        trusted = env["PIP_TRUSTED_HOST"].split()
    # A corporate index in any existing pip configuration takes precedence
    # over a public default, while higher-precedence user/venv settings win
    # over lower-precedence corporate settings when both are corporate.
    corporate = [item for item in indexes if _source(item[0], trusted).source_type == "CORPORATE_REGISTRY"]
    selected = corporate[-1] if corporate else indexes[-1] if indexes else ("", "pip-default")
    return selected[0], extras, trusted, selected[1]


def _source(url: str, trusted_hosts: list[str] | tuple[str, ...] = ()) -> PackageSource:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    public = host in {"pypi.org", "www.pypi.org", "test.pypi.org"} or host.endswith(".pythonhosted.org")
    if public:
        source_type, label = "PUBLIC_PYPI", "Public PyPI"
    elif parsed.scheme == "file":
        source_type, label = "CORPORATE_REGISTRY", "Configured local package registry"
    elif host:
        source_type, label = "CORPORATE_REGISTRY", f"Configured registry ({host})"
    else:
        source_type, label = "CONFIGURED_REGISTRY", "Configured package registry"
    return PackageSource(url, source_type, label, tuple(trusted_hosts))


def package_resolution_policy(*, env: dict[str, str] | None = None, home: Path | None = None,
                              public_index_url: str = PUBLIC_INDEX) -> PackageResolutionPolicy:
    """Choose one authoritative index at a time to prevent accidental source mixing."""
    env = dict(os.environ if env is None else env)
    home = (home or Path(env.get("HOME", str(Path.home())))).expanduser().absolute()
    config_index, config_extras, trusted, config_source = _pip_config(home, env)
    env_index = env.get("PIP_INDEX_URL", "").strip()
    env_extras = env.get("PIP_EXTRA_INDEX_URL", "").split()
    anvil_index = env.get("ANVIL_PACKAGE_INDEX_URL", "").strip()
    candidates: list[tuple[str, str]] = []
    if anvil_index:
        candidates.append((anvil_index, "Anvil package policy"))
    else:
        if config_index:
            candidates.append((config_index, config_source))
        if env_index:
            candidates.append((env_index, "PIP_INDEX_URL"))
        candidates.extend((url, "PIP_EXTRA_INDEX_URL") for url in env_extras)
        candidates.extend((url, "pip.conf extra-index-url") for url in config_extras)
    if anvil_index:
        index, configured_by = anvil_index, "Anvil package policy"
    else:
        corporate = next(((url, origin) for url, origin in candidates
                          if _source(url, trusted).source_type == "CORPORATE_REGISTRY"), None)
        if corporate:
            index, configured_by = corporate
        elif candidates:
            index, configured_by = candidates[0]
        else:
            # With no enterprise configuration, preserve the established
            # public-only installation path. It is shown as the primary source,
            # never as a fallback from a corporate registry.
            index, configured_by = public_index_url, "Anvil default public-only policy"
    extras = [url for url, _ in candidates if url != index]
    if env.get("PIP_TRUSTED_HOST"):
        trusted = env["PIP_TRUSTED_HOST"].split()
    primary = _source(index, trusted)
    explicit_fallback = env.get("ANVIL_ALLOW_PUBLIC_PYPI", "").strip().casefold()
    if explicit_fallback not in {"", "1", "true", "yes", "0", "false", "no"}:
        raise ValueError("ANVIL_ALLOW_PUBLIC_PYPI must be true or false")
    if explicit_fallback:
        allow_public = explicit_fallback in {"1", "true", "yes"}
    else:
        # The default public-only source permits PyPI. Configured corporate
        # sources are authoritative and never fall back without an opt-in.
        allow_public = primary.source_type == "PUBLIC_PYPI"
    fallback = (_source(public_index_url) if allow_public and primary.source_type != "PUBLIC_PYPI" else None)
    policy = "corporate-first" if primary.source_type == "CORPORATE_REGISTRY" else "configured-index"
    if primary.source_type == "PUBLIC_PYPI":
        policy = "public-only"
    return PackageResolutionPolicy(primary, allow_public, fallback, policy, configured_by, len(extras))


def runtime_path(lock: Path, data_root: Path, python: str = sys.executable) -> Path:
    parse_lock(lock)
    try:
        version = subprocess.run([python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                                 capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise DependencyError("python", "the selected Python runtime could not be inspected",
                              reason_code="INSTALLER_FAILURE", stage="Python inspection") from exc
    if not re.fullmatch(r"\d+\.\d+", version) or tuple(map(int, version.split("."))) < MIN_PYTHON:
        raise DependencyError("python", "Analytics requires Python 3.11 or newer",
                              reason_code="PYTHON_VERSION_INCOMPATIBLE", stage="Python inspection", python=version)
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()[:20]
    return data_root / "anvil" / "analytics" / "runtimes" / f"py{version}-{digest}"


def _validate(interpreter: Path, packages: list[tuple[str, str]], *, expected_prefix: Path | None = None) -> bool:
    """Validate a venv by execution semantics; normal bin/python symlinks are valid."""
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        return False
    prefix = (expected_prefix or interpreter.parent.parent).expanduser().absolute()
    expected = json.dumps(dict(packages), separators=(",", ":"))
    code = ("import importlib, importlib.metadata, json, pathlib, sys; "
            "expected_prefix=pathlib.Path(" + repr(str(prefix)) + ").resolve(); "
            "actual_prefix=pathlib.Path(sys.prefix).resolve(); "
            "assert actual_prefix == expected_prefix; "
            "expected=json.loads(" + repr(expected) + "); "
            "[importlib.import_module(name.replace('-', '_')) for name in expected]; "
            "actual={name:importlib.metadata.version(name) for name in expected}; "
            "raise SystemExit(0 if all(actual.get(k)==v for k,v in expected.items()) else 1)")
    try:
        return subprocess.run([str(interpreter), "-c", code], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=10, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _safe_operation_id(value: str | None) -> str:
    if value and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        return value
    return f"analytics-runtime-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"


def _log_path(operation_id: str) -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser().absolute()
    root = state_home / "anvil"
    operations = root / "operations"
    directory = operations / operation_id
    for candidate in (state_home, root, operations, directory):
        if candidate.is_symlink():
            raise DependencyError("runtime", "Analytics operation log path is unsafe",
                                  reason_code="DISK_FAILURE", stage="diagnostic log creation")
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory / "dependency-install.log"


def _redact(text: str, env: dict[str, str] | None = None) -> str:
    value = text
    env = os.environ if env is None else env
    secrets: set[str] = set()
    for key, raw in env.items():
        if not key.startswith(("PIP_", "ANVIL_PACKAGE_")) or not raw:
            continue
        if re.search(r"(?i)(?:token|password|secret|credential|api[_-]?key)", key) and len(raw) >= 3:
            secrets.add(raw)
        for candidate in raw.split():
            parsed = urlsplit(candidate)
            for secret in (parsed.password, parsed.username):
                if secret and len(secret) >= 3:
                    secrets.add(secret)
        for item in re.findall(r"(?i)[A-Za-z0-9_.-]*(?:token|password|secret|key|auth)[A-Za-z0-9_.-]*=([^&\s]+)", raw):
            secrets.add(item)
    for secret in sorted(secrets, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)(https?://)([^/@\s]+)@", r"\1[REDACTED]@", value)
    value = re.sub(r"(?i)([?&][^=&\s]*(?:token|password|secret|key|auth)[^=&\s]*=)[^&\s]+",
                   r"\1[REDACTED]", value)
    return value


def _append_log(path: Path, title: str, output: str, env: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(f"\n== {title} ==\n")
            redaction_env = dict(os.environ)
            redaction_env.update(env)
            stream.write(_redact(output, redaction_env))
            if not output.endswith("\n"):
                stream.write("\n")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _failure_reason(output: str, exc: BaseException | None = None) -> str:
    lower = output.casefold()
    if any(item in lower for item in ("external network disabled", "network blocked", "offline test fixture",
                                      "network is blocked by policy")):
        return "NETWORK_BLOCKED"
    if any(item in lower for item in ("401 unauthorized", "403 forbidden", "authentication failed", "invalid credentials")):
        return "AUTHENTICATION_FAILED"
    if any(item in lower for item in ("proxyerror", "proxy error", "tunnel connection failed", "proxy authentication")):
        return "PROXY_FAILURE"
    if any(item in lower for item in ("certificate_verify_failed", "ssl: certificate", "tlsv", "sslerror")):
        return "TLS_FAILURE"
    if any(item in lower for item in ("resolutionimpossible", "conflicting dependencies", "dependency conflict")):
        return "RESOLUTION_CONFLICT"
    if "requires-python" in lower or "requires a different python" in lower:
        return "PYTHON_VERSION_INCOMPATIBLE"
    if "none of the wheel's tags" in lower or "not a supported wheel" in lower or "no compatible wheel" in lower:
        return "WHEEL_NOT_AVAILABLE"
    if any(item in lower for item in ("failed to establish a new connection", "max retries exceeded",
                                      "could not fetch url", "connection refused", "name or service not known",
                                      "temporary failure in name resolution")):
        return "REGISTRY_UNAVAILABLE"
    if any(item in lower for item in ("connectionerror", "connection reset", "network is unreachable",
                                      "timed out", "timeout")):
        return "NETWORK_FAILURE"
    if "no matching distribution" in lower or "could not find a version that satisfies" in lower:
        return "VERSION_NOT_FOUND"
    if any(item in lower for item in ("404 client error", "package not found", "project not found")):
        return "PACKAGE_NOT_FOUND"
    if isinstance(exc, OSError) and exc.errno in {28, 122}:
        return "DISK_FAILURE"
    return "INSTALLER_FAILURE" if output or exc else "UNKNOWN_INSTALL_FAILURE"


def _pip_env(source: PackageSource, base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    # Use one selected index for an entire staged runtime. Keep proxy and CA
    # environment settings; never merge a configured private index with PyPI.
    for key in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_CONFIG_FILE", "PIP_FIND_LINKS",
                "PIP_NO_INDEX", "PIP_TRUSTED_HOST"):
        env.pop(key, None)
    env["PIP_CONFIG_FILE"] = os.devnull
    env["PIP_INDEX_URL"] = source.index_url
    if source.trusted_hosts:
        env["PIP_TRUSTED_HOST"] = " ".join(source.trusted_hosts)
    return env


def _pip_install(staged_python: Path, name: str, version: str, source: PackageSource,
                 log_path: Path, env: dict[str, str], python_version_text: str,
                 timeout: int = 900) -> None:
    command = [str(staged_python), "-m", "pip", "install", "--no-input",
               "--no-deps", "--only-binary=:all:"]
    command.append(f"{name}=={version}")
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=timeout, check=False, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        output = str(exc)
        _append_log(log_path, f"pip install {name}=={version} ({source.label})", output, env)
        raise DependencyError(name, "pinned package installation failed", version=version,
                              reason_code=_failure_reason(output, exc), stage="package installation",
                              python=python_version_text, registry=source.label,
                              log_path=str(log_path)) from exc
    _append_log(log_path, f"pip install {name}=={version} ({source.label})", result.stdout or "", env)
    if result.returncode != 0:
        raise DependencyError(name, "pinned package installation failed", version=version,
                              reason_code=_failure_reason(result.stdout or ""), stage="package installation",
                              python=python_version_text, registry=source.label,
                              log_path=str(log_path))


def _build_staging(root: Path, operation_id: str, source: PackageSource, packages: list[tuple[str, str]],
                   python: str, log_path: Path, env: dict[str, str]) -> Path:
    _, python_version_text = python_version(python)
    staging = Path(tempfile.mkdtemp(prefix=f".runtime-{operation_id}-", dir=root))
    try:
        try:
            result = subprocess.run([python, "-m", "venv", str(staging)], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, timeout=60, check=False, env=env)
        except (OSError, subprocess.SubprocessError) as exc:
            output = str(exc)
            _append_log(log_path, "create isolated Analytics runtime", output, env)
            raise DependencyError("python", "the isolated Analytics runtime could not be created",
                                  reason_code=_failure_reason(output, exc), stage="runtime creation",
                                  python=python_version_text, registry=source.label, log_path=str(log_path)) from exc
        _append_log(log_path, "create isolated Analytics runtime", result.stdout or "", env)
        if result.returncode != 0:
            raise DependencyError("python", "the isolated Analytics runtime could not be created",
                                  reason_code=_failure_reason(result.stdout or ""), stage="runtime creation",
                                  python=python_version_text, registry=source.label, log_path=str(log_path))
        staged_python = staging / "bin" / "python"
        if not staged_python.is_file() or not os.access(staged_python, os.X_OK):
            raise DependencyError("python", "the isolated Analytics interpreter is unavailable",
                                  reason_code="INSTALLER_FAILURE", stage="runtime creation",
                                  python=python_version_text, registry=source.label, log_path=str(log_path))
        for name, version in packages:
            injected = os.environ.get("ANVIL_TEST_FAIL_ANALYTICS_PACKAGE", "")
            if os.environ.get("ANVIL_TEST_MODE") == "1" and injected in {name, f"{name}=={version}"}:
                raise DependencyError(name, "injected package source reported no matching pinned release",
                                      version=version, reason_code="VERSION_NOT_FOUND",
                                      stage="package installation", python=python_version_text,
                                      registry=source.label, log_path=str(log_path))
            _pip_install(staged_python, name, version, source, log_path, env, python_version_text)
        return staging
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _runtime_root(data_root: Path) -> Path:
    return data_root / "anvil" / "analytics" / "runtimes"


def _operation_dir(data_root: Path) -> Path:
    return data_root / "anvil" / "analytics" / "operations"


def _operation_marker(data_root: Path, operation_id: str) -> Path:
    return _operation_dir(data_root) / f"{_safe_operation_id(operation_id)}.json"


def _write_private_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise DependencyError("runtime", "Analytics operation state path is unsafe",
                              reason_code="DISK_FAILURE", stage="operation state")
    fd, temporary = tempfile.mkstemp(prefix=".operation.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_operation(data_root: Path, operation_id: str) -> tuple[Path, dict[str, object]]:
    marker_path = _operation_marker(data_root, operation_id)
    for parent in (data_root, data_root / "anvil", data_root / "anvil" / "analytics", _operation_dir(data_root)):
        if parent.is_symlink():
            raise DependencyError("runtime", "Analytics operation state path is unsafe",
                                  reason_code="DISK_FAILURE", stage="staged runtime lookup")
    if marker_path.is_symlink() or not marker_path.is_file():
        raise DependencyError("runtime", "staged Analytics runtime operation was not found",
                              reason_code="IMPORT_VALIDATION_FAILED", stage="staged runtime lookup")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DependencyError("runtime", "staged Analytics runtime operation is unreadable",
                              reason_code="DISK_FAILURE", stage="staged runtime lookup") from exc
    if (not isinstance(marker, dict) or marker.get("schema_version") != 1
            or marker.get("operation_id") != _safe_operation_id(operation_id)):
        raise DependencyError("runtime", "staged Analytics runtime operation is invalid",
                              reason_code="DISK_FAILURE", stage="staged runtime lookup")
    return marker_path, marker


def _marker_child(root: Path, name: object) -> Path | None:
    if not isinstance(name, str) or not name or Path(name).name != name:
        return None
    candidate = root / name
    if candidate.is_symlink():
        raise DependencyError("runtime", "staged Analytics runtime path is unsafe",
                              reason_code="DISK_FAILURE", stage="staged runtime validation")
    return candidate


def _runtime_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise DependencyError("runtime", "Analytics runtime directory must not be a symbolic link",
                              reason_code="DISK_FAILURE", stage="runtime path validation")
    os.chmod(root, 0o700)
    lock_path = root / ".prepare.lock"
    if lock_path.is_symlink():
        raise DependencyError("runtime", "Analytics runtime lock must not be a symbolic link",
                              reason_code="DISK_FAILURE", stage="runtime path validation")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    os.fchmod(fd, 0o600)
    stream = os.fdopen(fd, "a+", encoding="utf-8")
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    return stream


def stage(lock: Path, data_root: Path, python: str = sys.executable, *, operation_id: str | None = None,
          policy: PackageResolutionPolicy | None = None) -> Path:
    _, packages = parse_lock(lock)
    destination = runtime_path(lock, data_root, python)
    interpreter = destination / "bin" / "python"
    root = _runtime_root(data_root)
    for candidate in (data_root, data_root / "anvil", data_root / "anvil" / "analytics",
                      root, _operation_dir(data_root)):
        if candidate.is_symlink():
            raise DependencyError("runtime", "Analytics runtime paths must not contain symbolic links",
                                  reason_code="DISK_FAILURE", stage="runtime path validation")
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise DependencyError("runtime", "Analytics runtime target is not a regular directory",
                              reason_code="DISK_FAILURE", stage="runtime path validation")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise DependencyError("runtime", "Analytics runtime directory must not be a symbolic link",
                              reason_code="DISK_FAILURE", stage="runtime path validation")
    operation = _safe_operation_id(operation_id)
    log_path = _log_path(operation)
    policy = policy or package_resolution_policy()
    base_env = dict(os.environ)
    marker_path = _operation_marker(data_root, operation)
    with _runtime_lock(root):
        if marker_path.exists() or marker_path.is_symlink():
            raise DependencyError("runtime", "an Analytics staging operation with this id already exists",
                                  reason_code="DISK_FAILURE", stage="operation state")
        if destination.is_dir() and _validate(interpreter, packages):
            resolution_path = destination / "anvil-package-resolution.json"
            selected: dict[str, object] | None = None
            if resolution_path.is_file() and not resolution_path.is_symlink():
                try:
                    existing = json.loads(resolution_path.read_text(encoding="utf-8"))
                    selected = existing.get("selected_source") if isinstance(existing, dict) else None
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            _write_private_json(marker_path, {
                "schema_version": 1, "operation_id": operation, "target": destination.name,
                "staging": None, "backup": None, "reused_existing": True,
                "destination_existed": True, "phase": "staged", "packages": dict(packages),
                "selected_source": selected,
            })
            return interpreter

        previous_error: DependencyError | None = None
        staging: Path | None = None
        selected: PackageSource | None = None
        for source in policy.sources():
            env = _pip_env(source, base_env)
            try:
                staging = _build_staging(root, operation, source, packages, python, log_path, env)
                if not _validate(staging / "bin" / "python", packages):
                    raise DependencyError("duckdb/pyarrow", "Analytics imports or pinned versions failed validation",
                                          reason_code="IMPORT_VALIDATION_FAILED", stage="import validation",
                                          python=str(staging / "bin" / "python"), registry=source.label,
                                          log_path=str(log_path),
                                          public_fallback="enabled" if policy.public_fallback else "disabled")
                selected = source
                break
            except DependencyError as exc:
                previous_error = exc
                if source == policy.primary and policy.fallback_source and exc.reason_code in {
                    "PACKAGE_NOT_FOUND", "VERSION_NOT_FOUND", "REGISTRY_UNAVAILABLE", "NETWORK_FAILURE",
                    "NETWORK_BLOCKED",
                }:
                    _append_log(log_path, "source fallback decision",
                                "Primary registry failed; explicit policy permits a separate public-source attempt.", base_env)
                    if staging is not None:
                        shutil.rmtree(staging, ignore_errors=True)
                        staging = None
                    continue
                raise DependencyError(exc.dependency, str(exc), version=exc.version, reason_code=exc.reason_code,
                                      stage=exc.stage, python=exc.python, registry=exc.registry,
                                      log_path=str(log_path),
                                      public_fallback="enabled" if policy.public_fallback else "disabled") from exc
        if staging is None or selected is None:
            raise previous_error or DependencyError("runtime", "no package source could prepare Analytics",
                                                    reason_code="UNKNOWN_INSTALL_FAILURE")
        try:
            for directory, _, files in os.walk(staging):
                os.chmod(directory, 0o700)
                for filename in files:
                    path = Path(directory) / filename
                    if not path.is_symlink():
                        os.chmod(path, 0o700 if os.access(path, os.X_OK) else 0o600)
            resolution = {"schema_version": 1, "packages": dict(packages),
                          "selected_source": selected.public(), "policy": policy.public(),
                          "operation_id": operation}
            resolution_path = staging / "anvil-package-resolution.json"
            resolution_path.write_text(json.dumps(resolution, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            resolution_path.chmod(0o600)
            _write_private_json(marker_path, {
                "schema_version": 1, "operation_id": operation, "target": destination.name,
                "staging": staging.name, "backup": f".runtime-before-{operation}",
                "reused_existing": False,
                "destination_existed": destination.exists() or destination.is_symlink(),
                "phase": "staged", "packages": dict(packages),
                "selected_source": selected.public(), "log_path": str(log_path),
            })
            return staging / "bin" / "python"
        except DependencyError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise DependencyError("runtime", "the isolated Analytics runtime could not be staged",
                                  reason_code=_failure_reason(str(exc), exc), stage="runtime staging",
                                  python=python, registry=selected.label, log_path=str(log_path),
                                  public_fallback="enabled" if policy.public_fallback else "disabled") from exc


def staged_interpreter(lock: Path, data_root: Path, operation_id: str) -> Path:
    _, packages = parse_lock(lock)
    root = _runtime_root(data_root)
    _, marker = _read_operation(data_root, operation_id)
    target = _marker_child(root, marker.get("target"))
    staging = _marker_child(root, marker.get("staging"))
    if target is None or (marker.get("reused_existing") is not True and staging is None):
        raise DependencyError("runtime", "staged Analytics runtime paths are invalid",
                              reason_code="DISK_FAILURE", stage="staged runtime validation")
    if marker.get("reused_existing") is True or marker.get("phase") in {"activated", "activation-started"}:
        selected = target
    else:
        selected = staging
    if selected is None or not selected.is_dir() or not _validate(selected / "bin" / "python", packages):
        raise DependencyError("duckdb/pyarrow", "staged Analytics dependencies failed import validation",
                              reason_code="IMPORT_VALIDATION_FAILED", stage="staged runtime verification",
                              python=str(selected / "bin" / "python") if selected else "")
    return selected / "bin" / "python"


def activate(lock: Path, data_root: Path, operation_id: str) -> Path:
    _, packages = parse_lock(lock)
    root = _runtime_root(data_root)
    marker_path, _ = _read_operation(data_root, operation_id)
    with _runtime_lock(root):
        marker_path, marker = _read_operation(data_root, operation_id)
        target = _marker_child(root, marker.get("target"))
        staging = _marker_child(root, marker.get("staging"))
        backup = _marker_child(root, marker.get("backup"))
        if target is None:
            raise DependencyError("runtime", "staged Analytics target path is invalid",
                                  reason_code="DISK_FAILURE", stage="runtime activation")
        if marker.get("phase") == "activated":
            if not _validate(target / "bin" / "python", packages):
                raise DependencyError("duckdb/pyarrow", "activated Analytics runtime failed validation",
                                      reason_code="IMPORT_VALIDATION_FAILED", stage="runtime activation")
            return target / "bin" / "python"
        if marker.get("reused_existing") is True:
            if not _validate(target / "bin" / "python", packages):
                raise DependencyError("duckdb/pyarrow", "reused Analytics runtime failed validation",
                                      reason_code="IMPORT_VALIDATION_FAILED", stage="runtime activation")
            marker["phase"] = "activated"
            _write_private_json(marker_path, marker)
            return target / "bin" / "python"
        if staging is None or not staging.is_dir():
            raise DependencyError("runtime", "staged Analytics runtime is missing",
                                  reason_code="DISK_FAILURE", stage="runtime activation")
        marker["phase"] = "activation-started"
        _write_private_json(marker_path, marker)
        displaced_target = False
        published_target = False
        try:
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_dir():
                    raise DependencyError("runtime", "Analytics target path is unsafe",
                                          reason_code="DISK_FAILURE", stage="runtime activation")
                if backup and (backup.exists() or backup.is_symlink()):
                    raise DependencyError("runtime", "Analytics rollback path already exists",
                                          reason_code="DISK_FAILURE", stage="runtime activation")
                if backup:
                    os.replace(target, backup)
                    displaced_target = True
            os.replace(staging, target)
            published_target = True
            if not _validate(target / "bin" / "python", packages):
                raise DependencyError("duckdb/pyarrow", "activated Analytics runtime failed validation",
                                      reason_code="IMPORT_VALIDATION_FAILED", stage="runtime activation",
                                      python=str(target / "bin" / "python"))
            marker["phase"] = "activated"
            _write_private_json(marker_path, marker)
            return target / "bin" / "python"
        except BaseException:
            if published_target and target.exists() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=True)
            if displaced_target and backup and backup.exists() and not backup.is_symlink():
                os.replace(backup, target)
            raise


def restore_operation(data_root: Path, operation_id: str) -> None:
    marker_path, _ = _read_operation(data_root, operation_id)
    root = _runtime_root(data_root)
    with _runtime_lock(root):
        marker_path, marker = _read_operation(data_root, operation_id)
        target = _marker_child(root, marker.get("target"))
        staging = _marker_child(root, marker.get("staging"))
        backup = _marker_child(root, marker.get("backup"))
        if target is None:
            raise DependencyError("runtime", "Analytics rollback target path is invalid",
                                  reason_code="DISK_FAILURE", stage="runtime restoration")
        if marker.get("phase") in {"activation-started", "activated"} and marker.get("reused_existing") is not True:
            config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
            active_lock = config_home / "opencode" / "runtime" / "analytics-requirements.lock"
            if active_lock.is_file() and not active_lock.is_symlink():
                active_target = runtime_path(active_lock, data_root)
                if active_target.resolve(strict=False) == target.resolve(strict=False):
                    raise DependencyError(
                        "runtime", "restore the previous managed config pointer before removing its staged Analytics runtime",
                        reason_code="DISK_FAILURE", stage="runtime restoration",
                    )
            if backup and backup.exists():
                if target.exists() and not target.is_symlink():
                    shutil.rmtree(target)
                os.replace(backup, target)
            elif marker.get("destination_existed") is True:
                if not target.exists() or target.is_symlink():
                    raise DependencyError("runtime", "the previous Analytics runtime is missing",
                                          reason_code="DISK_FAILURE", stage="runtime restoration")
            elif target.exists() and not target.is_symlink():
                shutil.rmtree(target)
        if staging and staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)
        marker_path.unlink(missing_ok=True)


def abort(data_root: Path, operation_id: str) -> None:
    root = _runtime_root(data_root)
    operation = _safe_operation_id(operation_id)
    marker_path = _operation_marker(data_root, operation)
    for parent in (data_root, data_root / "anvil", data_root / "anvil" / "analytics", _operation_dir(data_root)):
        if parent.is_symlink():
            raise DependencyError("runtime", "Analytics operation state path is unsafe",
                                  reason_code="DISK_FAILURE", stage="staging abort")
    if marker_path.is_symlink():
        raise DependencyError("runtime", "Analytics operation marker is unsafe",
                              reason_code="DISK_FAILURE", stage="staging abort")
    marker: dict[str, object] = {}
    if marker_path.is_file():
        marker_path, marker = _read_operation(data_root, operation)
        if marker.get("phase") in {"activation-started", "activated"}:
            raise DependencyError("runtime", "activated Analytics runtime requires baseline restoration, not staging abort",
                                  reason_code="DISK_FAILURE", stage="staging abort")
    staging = _marker_child(root, marker.get("staging"))
    if staging and staging.exists() and not staging.is_symlink():
        shutil.rmtree(staging)
    marker_path.unlink(missing_ok=True)
    if root.is_dir() and not root.is_symlink():
        for candidate in root.glob(f".runtime-{operation}-*"):
            if candidate.is_dir() and not candidate.is_symlink():
                shutil.rmtree(candidate, ignore_errors=True)


def finalize(data_root: Path, operation_id: str) -> None:
    marker_path, marker = _read_operation(data_root, operation_id)
    if marker.get("phase") != "activated":
        raise DependencyError("runtime", "Analytics runtime cannot be finalized before activation",
                              reason_code="DISK_FAILURE", stage="runtime finalization")
    root = _runtime_root(data_root)
    backup = _marker_child(root, marker.get("backup"))
    if backup and backup.exists() and not backup.is_symlink():
        shutil.rmtree(backup)
    staging = _marker_child(root, marker.get("staging"))
    if staging and staging.exists() and not staging.is_symlink():
        shutil.rmtree(staging, ignore_errors=True)
    marker_path.unlink(missing_ok=True)


def prepare(lock: Path, data_root: Path, python: str = sys.executable, *, operation_id: str | None = None,
            policy: PackageResolutionPolicy | None = None) -> Path:
    operation = _safe_operation_id(operation_id)
    stage(lock, data_root, python, operation_id=operation, policy=policy)
    interpreter = activate(lock, data_root, operation)
    finalize(data_root, operation)
    return interpreter


def resolution_status(lock: Path, data_root: Path, python: str = sys.executable,
                      operation_id: str | None = None) -> dict[str, object]:
    release, packages = parse_lock(lock)
    target = runtime_path(lock, data_root, python)
    _, version = python_version(python)
    policy = package_resolution_policy()
    resolution_file = target / "anvil-package-resolution.json"
    selected: dict[str, object] | None = None
    if resolution_file.is_file() and not resolution_file.is_symlink():
        try:
            value = json.loads(resolution_file.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("selected_source"), dict):
                selected = value["selected_source"]
        except (OSError, ValueError, json.JSONDecodeError):
            selected = None
    active_interpreter = target / "bin" / "python"
    staged_path = None
    if operation_id and _operation_marker(data_root, operation_id).is_file():
        staged_path = staged_interpreter(lock, data_root, operation_id)
    return {"release": release, "python": version, "runtime": str(target),
            "ready": _validate(staged_path or active_interpreter, packages),
            "packages": dict(packages), "resolution_policy": policy.public(),
            "selected_source": selected, "staged_interpreter": str(staged_path) if staged_path else None,
            "availability": "NOT_CHECKED"}


def python_version(python: str) -> tuple[tuple[int, int], str]:
    try:
        version = subprocess.run([python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                                 capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise DependencyError("python", "the selected Python runtime could not be inspected",
                              reason_code="INSTALLER_FAILURE", stage="Python inspection") from exc
    if not re.fullmatch(r"\d+\.\d+", version) or tuple(map(int, version.split("."))) < MIN_PYTHON:
        raise DependencyError("python", "Analytics requires Python 3.11 or newer",
                              reason_code="PYTHON_VERSION_INCOMPATIBLE", stage="Python inspection", python=version)
    return tuple(map(int, version.split("."))), version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    lock_actions = {"prepare", "stage", "activate", "resolve", "status", "plan"}
    operation_actions = {"prepare", "stage", "activate", "abort", "restore", "finalize", "resolve", "status"}
    for action in ("prepare", "stage", "activate", "abort", "restore", "finalize",
                   "resolve", "status", "plan"):
        command = subparsers.add_parser(action)
        command.add_argument("--data-root", type=Path,
                             default=Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")))
        command.add_argument("--format", choices=("text", "json"), default="text")
        if action in lock_actions:
            command.add_argument("--lock", type=Path, required=True)
            command.add_argument("--python", default=sys.executable)
        if action in operation_actions:
            command.add_argument("--operation-id", required=action in {"activate", "abort", "restore", "finalize"},
                                 default=os.environ.get("ANVIL_LIFECYCLE_OPERATION_ID"))
    args = parser.parse_args(argv)
    try:
        if args.action in {"abort", "restore", "finalize"}:
            if args.action == "abort":
                abort(args.data_root, args.operation_id)
            elif args.action == "restore":
                restore_operation(args.data_root, args.operation_id)
            else:
                finalize(args.data_root, args.operation_id)
            result = {"operation_id": args.operation_id, "status": args.action.upper()}
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        release, packages = parse_lock(args.lock)
        target = runtime_path(args.lock, args.data_root, args.python)
        if args.action == "prepare":
            interpreter = prepare(args.lock, args.data_root, args.python, operation_id=args.operation_id)
            result = resolution_status(args.lock, args.data_root, args.python, args.operation_id)
            result["interpreter"] = str(interpreter)
        elif args.action == "stage":
            interpreter = stage(args.lock, args.data_root, args.python, operation_id=args.operation_id)
            result = resolution_status(args.lock, args.data_root, args.python, args.operation_id)
            result["interpreter"] = str(interpreter)
            result["status"] = "STAGED"
        elif args.action == "activate":
            if not args.operation_id:
                raise ValueError("activate requires --operation-id")
            interpreter = activate(args.lock, args.data_root, args.operation_id)
            result = resolution_status(args.lock, args.data_root, args.python, args.operation_id)
            result["interpreter"] = str(interpreter)
            result["status"] = "ACTIVATED"
        elif args.action == "plan":
            policy = package_resolution_policy()
            _, version = python_version(args.python)
            result = {"release": release, "python": version, "runtime": str(target),
                      "action": "REUSE VALIDATED ENVIRONMENT" if _validate(target / "bin" / "python", packages)
                                else "PREPARE ISOLATED ENVIRONMENT",
                      "dependencies": [{"package": name, "version": version,
                                        "policy": policy.policy,
                                        "source_policy": policy.primary.public(),
                                        "public_fallback": "enabled" if policy.public_fallback else "disabled",
                                        "availability": "NOT_CHECKED"} for name, version in packages],
                      "resolution_policy": policy.public(), "service": "sync/activate after staged validation",
                      "opencode": "bootstrap occurs only after service activation"}
        else:
            result = resolution_status(args.lock, args.data_root, args.python, args.operation_id)
            if args.action != "status" and not result["ready"]:
                raise DependencyError("duckdb/pyarrow", "the prepared Analytics runtime is missing or unhealthy",
                                      reason_code="IMPORT_VALIDATION_FAILED", stage="runtime status",
                                      python=args.python, registry=str(result["resolution_policy"]["primary"]["label"]))
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif args.action == "plan":
            print(f"Analytics runtime staging plan (Anvil {release})")
            print(f"  Python           {result['python']}")
            print(f"  runtime          {result['runtime']}")
            for item in result["dependencies"]:
                print(f"  dependency       {item['package']}=={item['version']}")
                print(f"    source policy  {item['policy']} ({item['source_policy']['label']})")
                print(f"    public fallback {item['public_fallback']}")
                print("    availability   NOT_CHECKED")
            print("  service          unit candidate validated before activation; service starts after config activation")
            print("  OpenCode         bootstrap happens after activation; dry run performs no network checks")
        elif args.action in {"status", "resolve"}:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif args.action == "prepare":
            print(result["interpreter"])
            print(f"Analytics dependency source: {result['selected_source']['source_type']} ({result['selected_source']['label']})")
        else:
            print(target / "bin" / "python")
        return 0
    except (DependencyError, OSError, ValueError, configparser.Error) as exc:
        if isinstance(exc, DependencyError):
            details = exc.public()
            print("Analytics dependency staging failed.", file=sys.stderr)
            print(f"Dependency       {details['dependency']}{'=='+details['version'] if details['version'] else ''}", file=sys.stderr)
            print(f"Python           {details['python'] or getattr(args, 'python', sys.executable)}", file=sys.stderr)
            print(f"Registry         {details['registry']}", file=sys.stderr)
            print(f"Stage            {details['stage']}", file=sys.stderr)
            print(f"Reason           {details['reason_code']}", file=sys.stderr)
            print(f"Public fallback  {details['public_fallback']}", file=sys.stderr)
            if details["log_path"]:
                print(f"Details          {details['log_path']}", file=sys.stderr)
            print("The target Analytics runtime was not activated.", file=sys.stderr)
        else:
            print(f"ERROR ANALYTICS_DEPENDENCY: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
