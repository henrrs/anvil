#!/usr/bin/env python3
"""Separate response structure from explicit semantic rubric adjudication."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from engineering.contracts import CONFIDENCE, require, safe_content
from engineering.errors import EngineeringError


def evaluate(suite: dict, responses: list[dict], adjudications: list[dict]) -> dict:
    cases = {c["id"]: c for c in suite["cases"]}
    answers = {r["id"]: r for r in responses}
    require(len(answers) == len(responses) and set(answers) <= set(cases), "Responses need unique known case IDs.")
    reviews = {r["id"]: r for r in adjudications}
    results = []
    allowed = {"id", "decision", "evidence", "alternatives", "trade_off", "verification", "confidence", "unknowns", "references"}
    for key, response in answers.items():
        safe_content(response)
        require(not (set(response) - allowed), "Responses contain only public decisions/evidence, never hidden reasoning fields.")
        require(response.get("decision") and response.get("trade_off") and response.get("confidence") in CONFIDENCE,
                "Responses need decision, trade-off and confidence.")
        require(isinstance(response.get("alternatives"), list) and isinstance(response.get("unknowns"), list)
                and isinstance(response.get("verification"), list) and response["verification"], "Responses need high-level alternatives, unknowns and verification/experiment steps.")
        require(isinstance(response.get("evidence"), list) and response["evidence"], "Responses need scoped evidence, including UNKNOWN where absent.")
        for item in response["evidence"]:
            require(item.get("claim") and item.get("confidence") in CONFIDENCE and item.get("source"), "Evidence needs claim, confidence and source/explicit missing-source marker.")
        verdict = "PENDING_SEMANTIC_REVIEW"
        review = reviews.get(key)
        if review:
            require(review.get("reviewer") in {"human", "model"} and review.get("evidence_ref"), "Semantic adjudication needs reviewer and response evidence reference.")
            items = review.get("rubric_results", [])
            require(len(items) == len(cases[key]["rubric"]) and all(i.get("result") in {"PASS", "FAIL", "UNKNOWN"} and i.get("finding") for i in items), "Adjudicate each substantive rubric item with a finding.")
            verdict = "FAIL" if any(i["result"] == "FAIL" for i in items) else "UNKNOWN" if any(i["result"] == "UNKNOWN" for i in items) else "PASS"
        results.append({"id": key, "structure": "PASS", "semantic": verdict,
                        "rubric": cases[key]["rubric"], "adjudication": review,
                        "response": response})
    return {"results": results, "missing_cases": sorted(set(cases) - set(answers)),
            "method": "Structure is mechanical; semantic judgments are explicitly attributed and are not inferred from wording."}


def read(path: Path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 2 * 1024 * 1024, "Use a bounded regular JSON input.")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("spark", "system-design"), required=True)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate(read(Path(__file__).parent / f"{args.suite}-cases.json"), read(args.responses), read(args.adjudications) if args.adjudications else [])
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        return 0 if not report["missing_cases"] and all(r["semantic"] == "PASS" for r in report["results"]) else 1
    except (EngineeringError, ValueError, TypeError, KeyError, OSError) as exc:
        print(f"ERROR EVAL_CONTRACT: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
