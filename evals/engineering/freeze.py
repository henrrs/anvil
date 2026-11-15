"""Freeze visible fixture and independent-grader hashes before live runs."""
from __future__ import annotations

import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "evals/engineering/benchmarks.json"
SCENARIOS = ("retry-policy", "refactor", "ingestion", "queue-preview", "long-horizon", "context-recovery", "fast-control")


def digest_visible(name: str) -> str:
    base = ROOT / "evals/engineering" / name
    records = []
    for path in (base / "fixture").rglob("*"):
        if (not path.is_file() or path.name == "acceptance.py" or "__pycache__" in path.parts
                or "private" in path.parts or ".git" in path.parts):
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
    report = json.loads(MANIFEST.read_text(encoding="utf-8"))
    visible_names = tuple(case["fixture"] for case in report["scenarios"])
    if visible_names != SCENARIOS:
        raise SystemExit("Benchmark manifest scenario set/order differs from the supported OpenCode 1 suite")
    for case in report["scenarios"]:
        name = case["fixture"]
        grader = grader_path(name)
        case["visible_fixture_sha256"] = digest_visible(name)
        case["specification_sha256"] = hashlib.sha256(
            (ROOT / "evals/engineering" / name / "specification.md").read_bytes()
        ).hexdigest()
        case["private_grader"] = str(grader.relative_to(ROOT))
        case["private_grader_sha256"] = hashlib.sha256(grader.read_bytes()).hexdigest()
    MANIFEST.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    print(f"Frozen {len(report['scenarios'])} engineering scenarios; manifest sha256={digest}")


if __name__ == "__main__":
    main()
