"""Structured post-apply verification, independent of human-facing doctor."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import managed_config
from lifecycle_contributors import AnalyticsContributor, MemoryContributor, OpenCodeContributor
from semver import compare as compare_versions
from public_errors import run_public


@dataclass(frozen=True)
class Probe:
    name: str
    status: str
    reason: str = ""
    required: bool = True


@dataclass(frozen=True)
class VerificationResult:
    status: str
    probes: tuple[Probe, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def verify(config: Path, memory: Path, binary: Path, *, product_version: str,
           runtime_version: str, runtime_major: int, test_mode: bool = False,
           allow_repairable_drift: bool = False) -> VerificationResult:
    probes: list[Probe] = []

    def probe(name: str, fn, *, required: bool = True) -> None:
        try:
            fn()
            probes.append(Probe(name, "PASS", required=required))
        except (OSError, ValueError, RuntimeError) as exc:
            probes.append(Probe(name, "FAIL", type(exc).__name__, required))

    def managed() -> None:
        try:
            managed_config.validate_installed(config, product_version, product_version, None)
        except (OSError, ValueError, json.JSONDecodeError):
            if not allow_repairable_drift:
                raise
            drift = managed_config.classify_installed_drift(config, product_version,
                                                            (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip(),
                                                            None)
            if drift.get("classification") != "REPAIRABLE_MANAGED_DRIFT":
                raise ValueError("restored managed state is not a verified repairable drift")

    def runtime() -> None:
        OpenCodeContributor().verify(binary, runtime_version, runtime_major)

    def config_audit() -> None:
        import configure
        path = config / "opencode.jsonc"
        compatible = compare_versions(product_version, (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()) != 0
        problems = (configure._audit_v1(path, source_compatible=compatible) if runtime_major == 1
                    else configure.audit(path, source_compatible=compatible))
        if problems:
            raise ValueError("managed runtime profile failed its audit")

    def memory_root() -> None:
        MemoryContributor().verify(memory)

    probe("managed_artifacts", managed)
    probe("runtime_profile", config_audit)
    probe("opencode_runtime", runtime)
    probe("memory", memory_root)

    lock = config / "runtime" / "analytics-requirements.lock"
    if lock.is_file() and not test_mode:
        analytics = AnalyticsContributor()
        probe("analytics_dependencies", lambda: analytics.verify(config, memory))
        probe("analytics_service", lambda: analytics.verify_service(
            config, Path(os.environ.get("HOME", str(Path.home()))).expanduser()))
    status = "PASS" if all(item.status == "PASS" for item in probes if item.required) else "FAIL"
    return VerificationResult(status, tuple(probes))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--product-version", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--runtime-major", type=int, choices=(1, 2), required=True)
    parser.add_argument("--allow-repairable-drift", action="store_true",
                        help="Accept a verified pre-existing repairable Anvil-managed file during rollback")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    result = verify(args.config, args.memory, args.binary, product_version=args.product_version,
                    runtime_version=args.runtime_version, runtime_major=args.runtime_major,
                    test_mode=os.environ.get("ANVIL_TEST_MODE") == "1",
                    allow_repairable_drift=args.allow_repairable_drift)
    if args.format == "json":
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print("Anvil post-apply verification")
        for item in result.probes:
            print(f"  {item.name:24} {item.status}")
        print("Status: HEALTHY" if result.status == "PASS" else "Status: BROKEN")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run_public(main, command="Anvil lifecycle verification"))
