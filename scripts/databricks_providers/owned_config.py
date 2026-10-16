"""Anvil-owned Databricks config paths, isolated child environments, and writes."""

from __future__ import annotations

import configparser
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .state import config_root


def config_file() -> Path:
    return config_root() / "anvil" / "databricks" / "databrickscfg"


def external_config_file() -> Path:
    configured = os.environ.get("DATABRICKS_CONFIG_FILE")
    return Path(configured).expanduser() if configured else Path.home() / ".databrickscfg"


def environment_conflicts() -> list[str]:
    """Return names only; never expose values from external Databricks settings."""
    return sorted(key for key, value in os.environ.items()
                  if key.upper().startswith("DATABRICKS_") and value)


def child_environment(*, profile: str | None = None, path: Path | None = None) -> dict[str, str]:
    """Isolate Databricks-specific environment variables for Anvil child tools."""
    result = dict(os.environ)
    for key in tuple(result):
        if key.upper().startswith("DATABRICKS_"):
            result.pop(key, None)
    result["DATABRICKS_CONFIG_FILE"] = str(path or config_file())
    if profile:
        result["DATABRICKS_CONFIG_PROFILE"] = profile
    return result


def azure_login_environment() -> dict[str, str]:
    """Keep cloud/proxy settings but prevent Databricks overrides leaking to az."""
    result = dict(os.environ)
    for key in tuple(result):
        if key.upper().startswith("DATABRICKS_"):
            result.pop(key, None)
    return result


def read_profiles(path: Path | None = None) -> list[dict[str, str]]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str.lower
    selected = path or config_file()
    try:
        with selected.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, configparser.Error):
        return []
    return [{"name": name, "host": parser[name].get("host", "").strip(),
             "auth_type": parser[name].get("auth_type", "").strip()}
            for name in parser.sections() if name != "__settings__"]


def valid_config(path: Path | None = None) -> bool:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    selected = path or config_file()
    try:
        with selected.open(encoding="utf-8") as stream:
            parser.read_file(stream)
        return True
    except FileNotFoundError:
        return True
    except (OSError, UnicodeError, configparser.Error):
        return False


def plaintext_credential_fields(path: Path) -> list[str]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str.lower
    try:
        with path.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except (OSError, UnicodeError, configparser.Error):
        return ["unreadable-config"]
    forbidden = {"token", "password", "client_secret", "secret", "refresh_token", "access_token"}
    return sorted({key for section in parser.sections() for key in parser[section] if key in forbidden})


def _section_names(text: str) -> set[str]:
    return {match.group(1).strip().casefold()
            for match in re.finditer(r"(?m)^\s*\[([^\]\r\n]+)\]\s*(?:[#;].*)?$", text)}


def stage_profile(profile: str, host: str, *, auth_type: str | None = None,
                  base_path: Path | None = None) -> Path:
    """Create a private same-directory candidate config without changing active config."""
    if not re.fullmatch(r"anvil-[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?", profile):
        raise ValueError("invalid Anvil profile name")
    from urllib.parse import urlsplit
    parsed = urlsplit(host)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("invalid Databricks workspace URL")
    target = config_file()
    owned_root = target.parent.parent
    if owned_root.is_symlink() or target.parent.is_symlink() or target.is_symlink():
        raise OSError("Anvil Databricks config path must not be a symbolic link")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    base = base_path or target
    try:
        text = base.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    names = _section_names(text)
    if profile.casefold() in names:
        existing = next((item for item in read_profiles(base) if item["name"].casefold() == profile.casefold()), None)
        if existing is None or existing["host"].rstrip("/").casefold() != host.rstrip("/").casefold():
            raise FileExistsError("Anvil profile name already exists with different or unreadable configuration")
        if auth_type and existing.get("auth_type", "").casefold() != auth_type.casefold():
            raise FileExistsError("Anvil profile authentication differs; explicit reset is required")
        candidate = text
    else:
        candidate = text.rstrip() + ("\n\n" if text.strip() else "")
        candidate += f"[{profile}]\nhost = {host}\n"
        if auth_type:
            candidate += f"auth_type = {auth_type}\n"
    fd, name = tempfile.mkstemp(prefix=".databrickscfg.pending.", dir=target.parent)
    stage = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        stage.unlink(missing_ok=True)
        raise
    return stage


def commit_staged(stage: Path) -> Path:
    target = config_file()
    owned_root = target.parent.parent
    if owned_root.is_symlink() or target.parent.is_symlink() or target.is_symlink():
        raise OSError("Anvil Databricks config path must not be a symbolic link")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    os.replace(stage, target)
    os.chmod(target, 0o600)
    directory_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return target


def set_profile_auth_type(stage: Path, profile: str, auth_type: str) -> None:
    if auth_type not in {"azure-cli"}:
        raise ValueError("unsupported Anvil-managed authentication type")
    text = stage.read_text(encoding="utf-8")
    matches = list(re.finditer(r"(?m)^\s*\[([^\]\r\n]+)\]\s*(?:[#;].*)?$", text))
    for index, match in enumerate(matches):
        if match.group(1).strip().casefold() != profile.casefold():
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        if re.search(r"(?im)^\s*(?:token|password|client_secret)\s*=", body):
            raise ValueError("Anvil profile contains an unsafe plaintext credential field")
        auth_match = re.search(r"(?im)^\s*auth_type\s*=.*$", body)
        if auth_match:
            body = body[:auth_match.start()] + f"auth_type = {auth_type}" + body[auth_match.end():]
        else:
            body = f"\nauth_type = {auth_type}" + body
        updated = text[:match.end()] + body + text[end:]
        fd, temporary = tempfile.mkstemp(prefix=".databrickscfg.auth.", dir=stage.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, stage)
            os.chmod(stage, 0o600)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            Path(temporary).unlink(missing_ok=True)
            raise
        return
    raise ValueError("Anvil profile section is missing")


def backup_existing(*, reset: bool = False) -> Path | None:
    target = config_file()
    if not target.exists():
        return None
    if target.is_symlink() or not target.is_file():
        raise OSError("Anvil Databricks config path must be a regular file")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    label = "reset" if reset else "backup"
    backup = target.with_name(f"databrickscfg.{label}-{stamp}-{os.getpid()}")
    counter = 1
    while backup.exists():
        backup = target.with_name(f"databrickscfg.{label}-{stamp}-{os.getpid()}-{counter}")
        counter += 1
    fd, temporary_name = tempfile.mkstemp(prefix=f".{backup.name}.pending.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with target.open("rb") as source, os.fdopen(fd, "wb") as destination:
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, backup)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise
    return backup


def restore_backup(backup: Path | None) -> None:
    target = config_file()
    if backup is None:
        target.unlink(missing_ok=True)
        return
    if backup.is_symlink() or not backup.is_file() or target.parent.is_symlink():
        raise OSError("Anvil Databricks rollback config is not a regular file")
    temporary = target.with_name(f".databrickscfg.restore-{os.getpid()}")
    shutil.copy2(backup, temporary)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    os.chmod(target, 0o600)
    directory_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def discard_stage(stage: Path | None) -> None:
    if stage is not None:
        stage.unlink(missing_ok=True)


def reset_backup_paths() -> list[str]:
    return [str(path) for path in sorted(config_file().parent.glob("databrickscfg.reset-*"))]
