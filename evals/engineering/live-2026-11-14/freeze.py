"""Freeze model-visible fixture and private-grader hashes before any live run."""
from __future__ import annotations

import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
EVALUATION = pathlib.Path(__file__).resolve().parent
SCENARIOS = ("retry-policy", "refactor", "ingestion", "queue-preview", "long-horizon", "context-recovery", "fast-control")
HOLDOUTS = ("holdout-atomic-recovery", "holdout-api-compat")


def digest_visible(name: str) -> str:
    base = ROOT / "evals/engineering" / name
    records = []
    for path in (base / "fixture").rglob("*"):
        if not path.is_file() or path.name == "acceptance.py" or "__pycache__" in path.parts or "private" in path.parts or ".git" in path.parts:
            continue
        records.append((path.relative_to(base / "fixture").as_posix(), path.read_bytes()))
    records.append(("specification.md", (base / "specification.md").read_bytes()))
    digest = hashlib.sha256()
    for relative, content in sorted(records):
        digest.update(relative.encode() + b"\0" + content)
    return digest.hexdigest()


def grader_path(name: str) -> pathlib.Path:
    base = ROOT / "evals/engineering" / name
    candidates = (base / "private/acceptance.py", base / "acceptance.py", base / "fixture/acceptance.py")
    return next(path for path in candidates if path.is_file())


def main() -> None:
    path = EVALUATION / "benchmarks.json"
    report = json.loads(path.read_text())
    visible_names = tuple(case["fixture"] for case in report["scenarios"])
    holdout_names = tuple(case["fixture"] for case in report.get("holdouts", []))
    if visible_names != SCENARIOS or holdout_names != HOLDOUTS:
        raise SystemExit("Benchmark manifest scenario set/order differs from the registered freeze list")
    for case in report["scenarios"] + report.get("holdouts", []):
        name = case["fixture"]
        grader = grader_path(name)
        case["visible_fixture_sha256"] = digest_visible(name)
        case["specification_sha256"] = hashlib.sha256((ROOT / "evals/engineering" / name / "specification.md").read_bytes()).hexdigest()
        case["private_grader"] = str(grader.relative_to(ROOT))
        case["private_grader_sha256"] = hashlib.sha256(grader.read_bytes()).hexdigest()
    path.write_text(json.dumps(report, indent=2) + "\n")
    config_path = EVALUATION / "config.json"
    config = json.loads(config_path.read_text())
    config["benchmarks_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Frozen {len(report['scenarios'])} primary/control scenarios and {len(report.get('holdouts', []))} holdouts; manifest sha256={config['benchmarks_sha256']}")


if __name__ == "__main__":
    main()
