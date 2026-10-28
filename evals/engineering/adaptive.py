#!/usr/bin/env python3
"""Offline evaluation of task-local expansion hints; does not run an LLM."""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from engineering import specification

BASELINE_COMMIT = "6b6401d"
BASELINE_KERNEL_BYTES = 3930


def structured_route(request: str, signals: dict) -> str:
    """Reproduce the Anvil 2.9 deterministic activation rule for comparison."""
    names = [key for key in ("architecture_change", "migration", "schema_change", "distributed_behavior", "cross_component")
             if signals.get(key) is True]
    for key, threshold in (("requirements", 8), ("subsystems", 3), ("files", 8), ("milestones", 2), ("acceptance_criteria", 5)):
        if signals.get(key, 0) >= threshold:
            names.append(key)
    if len(request) > 6000:
        names.append("specification_length")
    return "LONG_HORIZON" if names else "DIRECT"


def evaluate() -> dict:
    cases = json.loads((ROOT / "evals/engineering/adaptive-cases.json").read_text(encoding="utf-8"))["cases"]
    results = []
    for case in cases:
        baseline = structured_route(case["request"], case["signals"])
        adaptive = specification.assess(case["request"], case["signals"])
        results.append({"id": case["id"], "expected": case["expected_workflow"], "structured_baseline": baseline,
                        "adaptive": adaptive["workflow"], "matches": adaptive["workflow"] == case["expected_workflow"],
                        "branch_rubric": case["branches"]})
    false_before = sum(item["expected"] == "DIRECT" and item["structured_baseline"] != "DIRECT" for item in results)
    false_after = sum(item["expected"] == "DIRECT" and item["adaptive"] != "DIRECT" for item in results)
    missed_before = sum(item["expected"] == "EXPAND" and item["structured_baseline"] == "DIRECT" for item in results)
    missed_after = sum(item["expected"] == "EXPAND" and item["adaptive"] != "EXPAND" for item in results)
    candidate_bytes = (ROOT / "config/AGENTS.md").stat().st_size
    baseline_replay = json.loads((ROOT / "evals/engineering/adaptive-baseline.json").read_text(encoding="utf-8"))
    candidate_replay = json.loads((ROOT / "evals/engineering/results.json").read_text(encoding="utf-8"))
    baseline_fixtures = {item["name"]: item for item in baseline_replay["fixtures"]}
    candidate_fixtures = {item["fixture"]: item for item in candidate_replay["results"]}
    replay_comparison = {}
    for name, before in baseline_fixtures.items():
        after = candidate_fixtures[name]["runs"]
        baseline_runs = before["runs"]
        old_checks = statistics.mean(row["architecture_check_evaluations"] for row in baseline_runs)
        new_checks = statistics.mean(row["architecture_check_evaluations"] for row in after)
        replay_comparison[name] = {
            "baseline": {"successes": sum(row["success"] for row in baseline_runs), "runs": len(baseline_runs),
                         "verified_requirements_per_run": baseline_runs[0]["verified_requirements"],
                         "all_architecture_invariants_pass": all(set(row["architecture"].values()) == {"PASS"} for row in baseline_runs),
                         "mean_architecture_check_evaluations": old_checks,
                         "mean_state_writes": statistics.mean(row["state_writes"] for row in baseline_runs),
                         "mean_verification_commands": statistics.mean(row["verification_commands"] for row in baseline_runs),
                         "mean_elapsed_seconds": statistics.mean(row["elapsed_seconds"] for row in baseline_runs)},
            "adaptive": {"successes": sum(row["task_success"] for row in after), "runs": len(after),
                         "verified_requirements_per_run": after[0]["requirements"]["counts"]["VERIFIED"],
                         "all_architecture_invariants_pass": all(set(row["architecture"].values()) == {"PASS"} for row in after),
                         "mean_architecture_check_evaluations": new_checks,
                         "mean_state_writes": statistics.mean(row["state_writes"] for row in after),
                         "mean_verification_commands": statistics.mean(row["verification_commands"] for row in after),
                         "mean_elapsed_seconds": statistics.mean(row["latency_seconds"] for row in after)},
            "architecture_check_delta": new_checks - old_checks,
            "architecture_check_reduction_percent": round((old_checks - new_checks) * 100 / old_checks, 1) if old_checks else None,
            "state_write_delta": statistics.mean(row["state_writes"] for row in after) - statistics.mean(row["state_writes"] for row in baseline_runs),
        }
    return {
        "schema_version": 1,
        "method": "Offline deterministic route evaluation against paired task rubrics; not model execution.",
        "structured_baseline": {"release": "Anvil 2.9.0", "commit_prefix": BASELINE_COMMIT,
                                 "kernel_bytes": BASELINE_KERNEL_BYTES, "activation": "repository/request thresholds"},
        "adaptive_candidate": {"release": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
                               "kernel_bytes": candidate_bytes, "workflow_recommendation": "task triggers only; model judgment selects relevant branch"},
        "metrics": {"cases": len(results), "adaptive_route_matches": sum(item["matches"] for item in results),
                    "direct_cases_false_expanded_before": false_before, "direct_cases_false_expanded_after": false_after,
                    "required_expansions_missed_before": missed_before, "required_expansions_missed_after": missed_after,
                    "kernel_bytes_delta": candidate_bytes - BASELINE_KERNEL_BYTES,
                    "tool_calls": None, "files_read": None, "tests_run_by_model": None, "state_writes_by_model": None,
                    "elapsed_model_seconds": None, "model_tokens": None},
        "long_horizon_replay_comparison": replay_comparison,
        "results": results,
        "limitations": ["Branch rubrics are evaluation expectations; the offline runner validates only deterministic task signals.",
                        "No OpenCode executable is installed in this environment, so real-model behavior, tool usage, file reads, tests and tokens were not measured.",
                        "Kernel bytes are a source-size proxy, not a token or latency measurement."]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    report = evaluate()
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(f"Wrote adaptive route evaluation: {args.output}")
    else:
        print(serialized, end="")
    metrics = report["metrics"]
    return 0 if metrics["adaptive_route_matches"] == metrics["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
