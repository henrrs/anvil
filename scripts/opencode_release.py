#!/usr/bin/env python3
"""Resolve and verify an exact stable OpenCode 2 CLI package from npm."""

from __future__ import annotations

import argparse
import base64
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


REGISTRY = "https://registry.npmjs.org"
PACKAGE = "@opencode/cli"
USER_AGENT = "Anvil/2.1.0 (official OpenCode release resolver)"


def open_url(request: urllib.request.Request, timeout: int):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"official npm request returned HTTP {exc.code} from {request.full_url}; "
            "check this machine's proxy/firewall access to registry.npmjs.org"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"could not reach official npm endpoint {request.full_url}: {exc.reason}; "
            "check this machine's network and proxy settings"
        ) from exc


def request_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with open_url(request, timeout=30) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("npm registry response was not an object")
    return data


def asset_name() -> str:
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
        suffix = "-musl" if musl else ""
        baseline = False
        if arch == "x64":
            try:
                cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                cpuinfo = ""
            baseline = "avx2" not in cpuinfo
        variant = "-baseline" if baseline else ""
        return f"@opencode/cli-linux-{arch}{variant}{suffix}"
    if system == "darwin":
        baseline = False
        if arch == "x64":
            try:
                result = subprocess.run(["sysctl", "-n", "hw.optional.avx2_0"], capture_output=True, text=True, timeout=3)
                baseline = result.stdout.strip() != "1"
            except (OSError, subprocess.SubprocessError):
                baseline = True
        variant = "-baseline" if baseline else ""
        return f"@opencode/cli-darwin-{arch}{variant}"
    raise ValueError(f"unsupported OpenCode platform: {system}")


def integrity_parts(value: str) -> tuple[str, bytes]:
    match = re.fullmatch(r"(sha512)-([A-Za-z0-9+/]+={0,2})", value)
    if not match:
        raise ValueError("npm registry did not provide a supported SHA-512 integrity value")
    return match.group(1), base64.b64decode(match.group(2), validate=True)


def resolve(version: str | None = None) -> dict:
    package_url = f"{REGISTRY}/@opencode%2fcli"
    root = request_json(package_url)
    tags = root.get("dist-tags")
    if not isinstance(tags, dict) or not isinstance(tags.get("latest"), str):
        raise ValueError("official npm package has no latest stable dist-tag")
    selected = version.lstrip("v") if version else tags["latest"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", selected) or not selected.startswith("2."):
        raise ValueError(f"OpenCode stable candidate must be an exact 2.x.y release, got {selected!r}")
    if version and selected != tags["latest"]:
        # Explicit versions are accepted for tests only when the official stable dist-tag identifies them.
        # This prevents passing an arbitrary beta/dev package as a production candidate.
        stable_versions = root.get("versions", {})
        if selected not in stable_versions:
            raise ValueError("requested candidate is absent from the official package registry")
    target = asset_name()
    asset = request_json(f"{REGISTRY}/{target.replace('/', '%2f')}/{selected}")
    if asset.get("version") != selected:
        raise ValueError("platform package version does not match the selected stable CLI version")
    dist = asset.get("dist", {})
    tarball = dist.get("tarball", "")
    expected_prefix = f"{REGISTRY}/{target}/-/{target.rsplit('/', 1)[-1]}-{selected}.tgz"
    if tarball != expected_prefix:
        raise ValueError("platform package tarball URL is outside the expected official npm artifact")
    integrity = dist.get("integrity", "")
    integrity_parts(integrity)
    if target not in root.get("versions", {}).get(selected, {}).get("optionalDependencies", {}):
        raise ValueError("official CLI package does not declare the selected platform binary dependency")
    return {
        "version": selected,
        "channel": "latest",
        "published_at": root.get("time", {}).get(selected),
        "release_url": f"https://www.npmjs.com/package/{target}/v/{selected}",
        "registry": REGISTRY,
        "asset": {
            "name": target,
            "url": tarball,
            "integrity": integrity,
            "size": dist.get("unpackedSize"),
        },
    }


def download(candidate: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".part-{os.getpid()}")
    algorithm, expected = integrity_parts(candidate["asset"]["integrity"])
    digest = hashlib.new(algorithm)
    request = urllib.request.Request(candidate["asset"]["url"], headers={"User-Agent": USER_AGENT})
    try:
        with open_url(request, timeout=120) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        if digest.digest() != expected:
            raise ValueError("candidate tarball does not match official npm SHA-512 integrity metadata")
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
        candidate = resolve(args.version)
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
