#!/usr/bin/env python3
"""Resolve and verify an official stable OpenCode 1 GitHub release artifact."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


API = "https://api.github.com/repos/anomalyco/opencode"
USER_AGENT = "Anvil/2.1.0 (official OpenCode 1 release resolver)"


def request_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"official GitHub release request returned HTTP {exc.code} from {url}; check this machine's proxy/firewall access to api.github.com") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach official GitHub release endpoint {url}: {exc.reason}; check this machine's network and proxy settings") from exc
    if not isinstance(value, dict) and not isinstance(value, list):
        raise ValueError("official GitHub release response has an unexpected shape")
    return value


def platform_asset() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if not arch:
        raise ValueError(f"unsupported OpenCode architecture: {machine}")
    if system == "linux":
        libc, _ = platform.libc_ver()
        musl = Path("/etc/alpine-release").exists() or "musl" in libc.lower()
        try:
            result = subprocess.run(["ldd", "--version"], capture_output=True, text=True, timeout=3)
            musl = musl or "musl" in (result.stdout + result.stderr).lower()
        except (OSError, subprocess.SubprocessError):
            pass
        baseline = False
        if arch == "x64":
            try:
                baseline = "avx2" not in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                baseline = False
        return f"opencode-linux-{arch}{'-baseline' if baseline else ''}{'-musl' if musl else ''}.tar.gz"
    if system == "darwin":
        baseline = False
        if arch == "x64":
            try:
                result = subprocess.run(["sysctl", "-n", "hw.optional.avx2_0"], capture_output=True, text=True, timeout=3)
                baseline = result.stdout.strip() != "1"
            except (OSError, subprocess.SubprocessError):
                baseline = True
        return f"opencode-darwin-{arch}{'-baseline' if baseline else ''}.zip"
    raise ValueError(f"unsupported OpenCode platform: {system}")


def selected_release(version: str | None = None) -> dict:
    releases = request_json(f"{API}/releases?per_page=100") if version is None else request_json(f"{API}/releases/tags/v{version.lstrip('v')}")
    if isinstance(releases, dict):
        candidates = [releases]
    else:
        candidates = releases
    selected = None
    if version:
        exact = version.lstrip("v")
        if not re.fullmatch(r"1\.\d+\.\d+", exact):
            raise ValueError(f"OpenCode 1 candidate must be an exact stable 1.x.y version, got {exact!r}")
        selected = next((item for item in candidates if item.get("tag_name") == f"v{exact}" and not item.get("draft") and not item.get("prerelease")), None)
        if selected is None:
            raise ValueError(f"OpenCode {exact} is not an official stable GitHub release")
    else:
        selected = next((item for item in candidates if re.fullmatch(r"v1\.\d+\.\d+", item.get("tag_name", "")) and not item.get("draft") and not item.get("prerelease")), None)
        if selected is None:
            raise ValueError("official GitHub releases do not currently expose a stable OpenCode 1.x release")
    version_value = selected["tag_name"].removeprefix("v")
    asset_name = platform_asset()
    asset = next((item for item in selected.get("assets", []) if item.get("name") == asset_name), None)
    if not isinstance(asset, dict) or not isinstance(asset.get("browser_download_url"), str):
        raise ValueError(f"official OpenCode {version_value} release has no {asset_name} artifact")
    digest = asset.get("digest")
    match = re.fullmatch(r"sha256:([a-fA-F0-9]{64})", digest or "")
    if not match:
        raise ValueError(f"official OpenCode release does not publish a supported SHA-256 digest for {asset_name}")
    return {
        "version": version_value,
        "channel": "latest-1.x" if version is None else "exact-stable",
        "published_at": selected.get("published_at"),
        "release_url": selected.get("html_url"),
        "registry": API,
        "asset": {
            "name": asset_name,
            "url": asset["browser_download_url"],
            "integrity": f"sha256-{match.group(1).lower()}",
            "size": asset.get("size"),
        },
    }


def download(candidate: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".part-{os.getpid()}")
    expected = candidate["asset"]["integrity"].removeprefix("sha256-")
    digest = hashlib.sha256()
    request = urllib.request.Request(candidate["asset"]["url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected:
            raise ValueError("OpenCode release artifact does not match the official GitHub SHA-256 digest")
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except urllib.error.HTTPError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"official OpenCode release asset request returned HTTP {exc.code} from {candidate['asset']['url']}; check proxy/firewall access to github.com") from exc
    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"could not reach official OpenCode release asset {candidate['asset']['url']}: {exc.reason}; check proxy/firewall settings") from exc
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("--version")
    p_download = sub.add_parser("download")
    p_download.add_argument("--version", required=True)
    p_download.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        candidate = selected_release(args.version)
        if args.action == "resolve":
            print(json.dumps(candidate, indent=2))
        else:
            download(candidate, args.destination)
            print(json.dumps(candidate, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
