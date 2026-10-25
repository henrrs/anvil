"""Safe user-local installation of the official Databricks CLI release."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .state import data_root


RELEASE_API = "https://api.github.com/repos/databricks/cli/releases/latest"
MAX_DOWNLOAD = 80 * 1024 * 1024


def _request(url: str, limit: int = MAX_DOWNLOAD) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Anvil-Databricks-Setup"})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("download exceeded the Anvil safety limit")
    return data


def _asset(release: dict[str, Any]) -> tuple[dict[str, Any], str]:
    system = platform.system().casefold()
    machine = platform.machine().casefold()
    os_key = {"linux": "linux", "darwin": "darwin"}.get(system)
    arch_key = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if not os_key or not arch_key:
        raise OSError("unsupported-platform")
    expected = f"_{os_key}_{arch_key}.zip"
    assets = release.get("assets", [])
    binary = next((a for a in assets if str(a.get("name", "")).endswith(expected)), None)
    sums = next((a for a in assets if str(a.get("name", "")).endswith("_SHA256SUMS")), None)
    if not isinstance(binary, dict) or not isinstance(sums, dict):
        raise ValueError("official release does not contain a supported archive and SHA-256 manifest")
    return binary, str(sums["browser_download_url"])


def attempt_cli_install() -> dict[str, Any]:
    """Install to Anvil-owned user data only; never requests privilege elevation."""
    destination = data_root() / "bin" / "databricks"
    try:
        release = json.loads(_request(RELEASE_API, 2_000_000).decode("utf-8"))
        binary, sums_url = _asset(release)
        archive_name = str(binary["name"])
        archive = _request(str(binary["browser_download_url"]))
        sums = _request(sums_url, 100_000).decode("utf-8")
        expected_match = re.search(r"(?m)^([0-9a-fA-F]{64})\s+\*?" + re.escape(archive_name) + r"\s*$", sums)
        if not expected_match:
            return {"status": "BLOCKED", "failure": "binary-invalid", "message": "official SHA-256 manifest did not contain the selected asset"}
        actual = hashlib.sha256(archive).hexdigest()
        if actual.casefold() != expected_match.group(1).casefold():
            return {"status": "BLOCKED", "failure": "binary-invalid", "message": "download checksum did not match the official release manifest"}
        with tempfile.TemporaryDirectory(prefix="anvil-databricks-cli-") as temp:
            archive_path = Path(temp) / archive_name
            archive_path.write_bytes(archive)
            with zipfile.ZipFile(archive_path) as package:
                members = [entry for entry in package.infolist() if Path(entry.filename).name == "databricks" and not entry.is_dir()]
                if len(members) != 1:
                    return {"status": "BLOCKED", "failure": "binary-invalid", "message": "official archive did not contain one Databricks executable"}
                binary_bytes = package.read(members[0])
        for private_dir in (data_root().parent, data_root(), destination.parent):
            private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(private_dir, 0o700)
        fd, temporary = tempfile.mkstemp(prefix=".databricks.", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(binary_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            result = subprocess.run([temporary, "-v"], capture_output=True, text=True, timeout=8, check=False)
            output = result.stdout + result.stderr
            version = re.search(r"(?<!\d)v?(\d+\.\d+\.\d+)", output)
            if result.returncode or not version:
                return {"status": "BLOCKED", "failure": "binary-invalid", "message": "downloaded executable failed its local version check"}
            parsed_version = tuple(int(part) for part in version.group(1).split("."))
            if parsed_version < (1, 0, 0):
                return {"status": "BLOCKED", "failure": "unsupported-version", "message": "official release executable is below Anvil's supported CLI minimum"}
            os.replace(temporary, destination)
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        return {"status": "READY", "failure": None, "executable": str(destination.resolve()),
                "version": version.group(1), "method": "official-github-release-user-local"}
    except urllib.error.HTTPError as exc:
        category = "policy-blocked" if exc.code in {401, 403, 407} else "download-failed"
        return {"status": "BLOCKED", "failure": category, "message": f"official release request returned HTTP {exc.code}"}
    except PermissionError:
        return {"status": "BLOCKED", "failure": "permission-denied", "message": "user-local installation path is not writable"}
    except urllib.error.URLError:
        return {"status": "BLOCKED", "failure": "download-failed", "message": "official release could not be reached"}
    except TimeoutError:
        return {"status": "BLOCKED", "failure": "download-failed", "message": "official release request timed out"}
    except OSError as exc:
        category = str(exc) if str(exc) == "unsupported-platform" else "unknown"
        return {"status": "BLOCKED", "failure": category, "message": "official CLI could not be installed in the user-local path"}
    except (ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
        return {"status": "BLOCKED", "failure": "binary-invalid", "message": "official release metadata or archive was invalid"}


def install_sdk() -> dict[str, Any]:
    """Create/reuse Anvil's private SDK environment without touching global Python."""
    root = data_root()
    python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    invocation = str(python.expanduser().absolute())

    def blocked(failure: str, message: str) -> dict[str, Any]:
        return {"status": "BLOCKED", "failure": failure, "message": message}

    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        system_python = Path(sys.executable).expanduser().absolute()
        if not system_python.is_file() or not os.access(system_python, os.X_OK):
            return blocked("python-unavailable", "A working Python executable is required to prepare the isolated Databricks SDK environment.")
        if not python.is_file():
            try:
                subprocess.run([str(system_python), "-m", "venv", str(root / "venv")], check=True, timeout=90,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError:
                # Some distributions create the environment but report that
                # ensurepip is unavailable. Detect that specifically.
                if python.is_file() and os.access(python, os.X_OK):
                    pip_check = subprocess.run([invocation, "-m", "pip", "--version"], check=False,
                                               capture_output=True, text=True, timeout=8)
                    if pip_check.returncode:
                        return blocked("pip-unavailable", "pip is unavailable in Anvil's isolated Python environment.")
                return blocked("venv-unavailable", "Anvil could not create a working isolated Python environment.")
            os.chmod(root / "venv", 0o700)
        if not python.is_file() or not os.access(python, os.X_OK):
            return blocked("python-unavailable", "Anvil's isolated Python executable is missing or not executable.")
        sanity = subprocess.run([invocation, "-c", "import sys; print(sys.prefix)"],
                                capture_output=True, text=True, timeout=8, check=False)
        if sanity.returncode:
            return blocked("python-unavailable", "Anvil's isolated Python executable could not start.")
        check = subprocess.run([invocation, "-c", "import importlib.metadata as m; print(m.version('databricks-sdk'))"],
                               capture_output=True, text=True, timeout=8, check=False)
        if check.returncode == 0:
            return {"status": "READY", "python": invocation, "version": check.stdout.strip(), "reused": True}
        pip_check = subprocess.run([invocation, "-m", "pip", "--version"], check=False,
                                   capture_output=True, text=True, timeout=8)
        if pip_check.returncode:
            return blocked("pip-unavailable", "pip is unavailable in Anvil's isolated Python environment.")
        subprocess.run([invocation, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "databricks-sdk==0.141.0"],
                       check=True, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        result = subprocess.run([invocation, "-c", "import importlib.metadata as m; print(m.version('databricks-sdk'))"],
                                capture_output=True, text=True, timeout=8, check=True)
        return {"status": "READY", "python": invocation, "version": result.stdout.strip(), "reused": False}
    except subprocess.TimeoutExpired:
        return {"status": "BLOCKED", "failure": "download-failed", "message": "SDK setup timed out"}
    except subprocess.CalledProcessError as exc:
        detail = str(exc.stderr or "").casefold()
        category = "policy-blocked" if any(term in detail for term in ("http error 403", "http error 407", "proxy authentication", "blocked by policy")) else "download-failed"
        return {"status": "BLOCKED", "failure": category, "message": "SDK could not be installed in Anvil's isolated environment"}
    except OSError:
        return {"status": "BLOCKED", "failure": "permission-denied", "message": "Anvil's isolated SDK path is not writable"}
