#!/usr/bin/env python3
"""Resolve and download an exact stable OpenCode release from official GitHub assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import urllib.request
from pathlib import Path


API = "https://api.github.com/repos/anomalyco/opencode/releases"
RELEASES = "https://github.com/anomalyco/opencode/releases"
USER_AGENT = "Anvil/0.1.0 (official OpenCode release resolver)"


def request_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("GitHub release response was not an object")
    return data


def stable_release(version: str | None = None) -> dict:
    endpoint = f"{API}/latest" if version is None else f"{API}/tags/v{version.lstrip('v')}"
    data = request_json(endpoint)
    if data.get("draft") or data.get("prerelease"):
        raise ValueError("selected OpenCode release is a draft or prerelease")
    tag = str(data.get("tag_name", ""))
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", tag)
    if not match:
        raise ValueError(f"official release has an unsupported version tag: {tag!r}")
    if version and match.group(1) != version.lstrip("v"):
        raise ValueError("resolved release did not match the requested version")
    if not data.get("published_at"):
        raise ValueError("official stable release has no publication date")
    return data


def asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        raise ValueError(f"unsupported OpenCode architecture: {machine}")
    if system == "linux":
        target = f"linux-{arch}"
        if arch == "x64":
            try:
                cpu = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                cpu = ""
            if "avx2" not in cpu:
                target += "-baseline"
        libc, _ = platform.libc_ver()
        is_musl = Path("/etc/alpine-release").exists() or "musl" in libc.lower()
        try:
            import subprocess
            result = subprocess.run(["ldd", "--version"], capture_output=True, text=True, timeout=3)
            is_musl = is_musl or "musl" in (result.stdout + result.stderr).lower()
        except (OSError, subprocess.SubprocessError):
            pass
        if is_musl:
            target += "-musl"
        return f"opencode-{target}.tar.gz"
    if system == "darwin":
        if arch == "x64":
            try:
                import subprocess
                result = subprocess.run(["sysctl", "-n", "hw.optional.avx2_0"], capture_output=True, text=True, timeout=3)
                if result.stdout.strip() != "1":
                    arch += "-baseline"
            except (OSError, subprocess.SubprocessError):
                arch += "-baseline"
        return f"opencode-darwin-{arch}.zip"
    raise ValueError(f"unsupported OpenCode platform: {system}")


def select_asset(release: dict) -> dict:
    wanted = asset_name()
    for item in release.get("assets", []):
        if item.get("name") == wanted:
            digest = item.get("digest")
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
                raise ValueError("official release API did not provide a SHA-256 digest for the candidate")
            url = item.get("browser_download_url", "")
            expected_prefix = f"https://github.com/anomalyco/opencode/releases/download/{release['tag_name']}/"
            if not url.startswith(expected_prefix):
                raise ValueError("candidate download URL is outside the official OpenCode GitHub release")
            return {"name": wanted, "url": url, "sha256": digest.split(":", 1)[1].lower(), "size": item.get("size")}
    raise ValueError(f"official release does not publish the platform artifact {wanted}")


def resolve(version: str | None = None) -> dict:
    release = stable_release(version)
    asset = select_asset(release)
    return {
        "version": release["tag_name"].lstrip("v"),
        "tag": release["tag_name"],
        "published_at": release["published_at"],
        "release_url": release["html_url"],
        "asset": asset,
    }


def download(candidate: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".part-{os.getpid()}")
    request = urllib.request.Request(candidate["asset"]["url"], headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                digest.update(block)
                size += len(block)
            output.flush()
            os.fsync(output.fileno())
        expected_size = candidate["asset"].get("size")
        if expected_size and size != expected_size:
            raise ValueError(f"candidate artifact size mismatch: received {size}, expected {expected_size}")
        if digest.hexdigest() != candidate["asset"]["sha256"]:
            raise ValueError("candidate artifact SHA-256 does not match the official release metadata")
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("--version")
    p_download = sub.add_parser("download")
    p_download.add_argument("--version", required=True)
    p_download.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        candidate = resolve(args.version if args.action == "resolve" else args.version)
        if args.action == "resolve":
            print(json.dumps(candidate, indent=2))
            return 0
        download(candidate, args.destination)
        print(json.dumps(candidate, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
