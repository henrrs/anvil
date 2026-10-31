"""Command-line entry point for deterministic and model-backed evaluation runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.analytical.aggregation import aggregate_runs
from evals.analytical.contracts import validate_evaluation_result
from evals.analytical.evaluator import FIXTURES, GROUND_TRUTH, evaluate_candidate, evaluate_fixture
from evals.analytical.model_runner import run_blind_once
from evals.analytical.performance import benchmark_current, benchmark_historical_2_13
from evals.analytical.review import human_metrics, validate_review
from evals.analytical.semantic_certification import run_certification, write_artifacts as write_semantic_artifacts

BASELINE = ROOT / "evals" / "analytical" / "baselines" / "anvil-2.14.0-deterministic-v1.json"
FIXTURE_IDS = ("operations-v1", "services-v1")
SEVERITY = {"GRAIN": "HIGH", "ENTITY_RESOLUTION": "HIGH", "POPULATION": "HIGH", "COHORT": "HIGH",
            "COMPOSITION": "HIGH", "DISTRIBUTION": "HIGH", "CLAIM_SUPPORT": "HIGH", "CLAIM_CALIBRATION": "HIGH",
            "NUMERICAL": "HIGH", "DISCOVERY": "HIGH", "INVESTIGATION": "HIGH", "MATERIALITY": "MEDIUM",
            "COMMUNICATION": "HIGH", "CONTRIBUTION": "MEDIUM", "SEMANTIC": "HIGH", "PERFORMANCE": "MEDIUM",
            "INFRASTRUCTURE": "BLOCKER"}
ROADMAP = {
    "GRAIN": {"impact": "Wrong observation grain can turn row keys into business entities and invalidate downstream analysis.",
              "candidate_capability": "Improve evidence ranking for composite observation grain and alternate unique row identifiers.", "complexity_estimate": "MEDIUM"},
    "ENTITY_RESOLUTION": {"impact": "False entity candidates can promote dimensions as populations and distort counts/cohorts.",
                           "candidate_capability": "Improve entity candidate precision using repeated-time and dimension-role evidence.", "complexity_estimate": "MEDIUM"},
    "DISTRIBUTION": {"impact": "An average can hide material changes in tails or coverage.",
                     "candidate_capability": "Expand distribution comparison only where the observed fixture shows a missed material tail.", "complexity_estimate": "MEDIUM"},
    "DISCOVERY": {"impact": "Material phenomena can remain undiscovered without direct user prompting.",
                  "candidate_capability": "Evaluate hypothesis-driven investigation after repeated blind runs identify stable misses.", "complexity_estimate": "HIGH"},
    "INVESTIGATION": {"impact": "First-order changes may not explain cohort, contribution, or composition drivers.",
                      "candidate_capability": "Add targeted investigation steps only for human-confirmed recurrent gaps.", "complexity_estimate": "HIGH"},
    "CLAIM_CALIBRATION": {"impact": "Overstated causality or trend language can mislead decisions.",
                          "candidate_capability": "Strengthen evidence-to-claim calibration on recurrent reviewed failures.", "complexity_estimate": "MEDIUM"},
    "COMMUNICATION": {"impact": "A downstream response can contradict validated analytical facts.",
                      "candidate_capability": "Preserve shared fact references across response and artifact renderers.", "complexity_estimate": "MEDIUM"},
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_new(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _output_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().absolute()
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser()
    return base / "anvil" / "evaluations"


def _new_run_dir(base: Path) -> tuple[Path, str]:
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(base, 0o700)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = base / run_id
    directory.mkdir(mode=0o700)
    return directory, run_id


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _failure_summary(results: list[dict[str, Any]], model_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = [failure for result in results for failure in result.get("failures", [])]
    for model_run in model_runs:
        evaluation = model_run.get("evaluation")
        if evaluation:
            failures.extend(evaluation.get("failures", []))
        elif model_run.get("status") == "BLOCKED":
            failures.append({"class": "INFRASTRUCTURE", "id": model_run["run_id"],
                             "summary": model_run.get("blocker", "Model run blocked."),
                             "evidence": {"status": "BLOCKED", "fixture_id": model_run.get("fixture_id")}})
    return failures


def _gaps(failures: list[dict[str, Any]], *, model_status: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for failure in failures:
        grouped.setdefault(failure["class"], []).append(failure)
    gaps = []
    for category, items in grouped.items():
        recommendation = ROADMAP.get(category)
        if category == "INFRASTRUCTURE":
            recommendation = {"impact": "Live model quality could not be evaluated in this environment.",
                              "candidate_capability": "Configure the installed OpenCode runtime and repeat the blind evaluation.",
                              "complexity_estimate": "LOW"}
        if not recommendation:
            recommendation = {"impact": "Observed deterministic or review failure requires classification before implementation.",
                              "candidate_capability": "Inspect the cited evidence and add only a targeted follow-up evaluation.",
                              "complexity_estimate": "UNKNOWN"}
        fixtures = sorted({item.get("evidence", {}).get("fixture_id") for item in items
                           if item.get("evidence", {}).get("fixture_id")})
        gaps.append({"failure_class": category, "frequency": len(items), "fixture_count": len(fixtures),
                     "fixtures": fixtures, "severity": SEVERITY.get(category, "MEDIUM"),
                     "analytical_impact": recommendation["impact"],
                     "complexity_estimate": recommendation["complexity_estimate"],
                     "candidate_next_capability": recommendation["candidate_capability"],
                     "evidence": [{"id": item["id"], "summary": item["summary"], "evidence": item.get("evidence", {})} for item in items]})
    rank = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}
    gaps.sort(key=lambda item: (rank.get(item["severity"], 5), -item["frequency"], item["failure_class"]))
    if model_status != "COMPLETE":
        gaps.append({"failure_class": "DISCOVERY", "frequency": 0, "fixture_count": 0, "fixtures": [],
                     "severity": "UNKNOWN", "analytical_impact": "Model-backed blind discovery was not measured.",
                     "complexity_estimate": "UNKNOWN", "candidate_next_capability": "Do not select a production feature until repeated model runs and human review provide evidence.",
                     "evidence": [], "status": "NOT_MEASURED"})
    return {"schema_version": 1, "method": "Observed deterministic failures plus explicitly provisional model heuristics.",
            "roadmap_is_recommendation_only": True, "automatic_production_changes": False, "gaps": gaps}


def _classify_fast_path(performance: dict[str, Any], historical: dict[str, Any]) -> None:
    investigation = performance.get("fast_path_investigation", {})
    if historical.get("status") != "COMPLETE":
        investigation["classification"] = "UNKNOWN"
        investigation["evidence"] = "Current stage attribution is available, but no reproducible 2.13 timing was established."
        return
    if performance.get("repetitions", 0) < 3 or historical.get("repetitions", 0) < 3:
        investigation["classification"] = "UNKNOWN"
        investigation["evidence"] = "FAST-path classification requires at least three timing repetitions for both 2.13 and 2.14."
        return
    current = performance["depths"]["FAST"]
    previous = historical["depths"]["FAST"]
    total_delta = current["total"]["median_ms"] - previous["total_median_ms"]
    profile_delta = current["profile"]["median_ms"] - previous["profile_median_ms"]
    execution_delta = current["execute_plan_including_second_scan"]["median_ms"] - previous["execution_median_ms"]
    semantic_ms = performance["profile_stage_attribution"]["semantic_inference_median_ms"]
    evidence = {"2_13_total_median_ms": previous["total_median_ms"],
                "2_14_total_median_ms": current["total"]["median_ms"],
                "2_13_profile_median_ms": previous["profile_median_ms"],
                "2_14_profile_median_ms": current["profile"]["median_ms"],
                "2_13_execute_median_ms": previous["execution_median_ms"],
                "2_14_execute_median_ms": current["execute_plan_including_second_scan"]["median_ms"],
                "semantic_inference_median_ms": semantic_ms,
                "total_regression_ms": round(total_delta, 3),
                "semantic_inference_share_of_total_regression": round(semantic_ms / total_delta, 3) if total_delta > 0 else None}
    if total_delta > 0 and profile_delta > 0 and execution_delta <= 0 and semantic_ms >= profile_delta * 0.9:
        investigation["classification"] = "NECESSARY_CORRECTNESS_COST"
        investigation["evidence"] = evidence
        investigation["reasoning"] = "FAST latency growth is localized to profiling; measured semantic inference explains at least 90% of the profile-stage increase, while execution time did not increase. This stage produces the grain/entity safeguards used by the analysis result. No hypothesis, artifact, or unused deep-analysis initialization ran."
        investigation["action"] = "Keep semantic safeguards. A future optimization should preserve candidate-grain/entity checks and compare the same independent fixtures."
    else:
        investigation["classification"] = "MIXED" if total_delta > 0 else "UNKNOWN"
        investigation["evidence"] = evidence
        investigation["reasoning"] = "Measured stage changes do not isolate the FAST regression to semantic inference."


def _summary(run_id: str, mode: str, results: list[dict[str, Any]], model_runs: list[dict[str, Any]],
             performance: dict[str, Any], historical: dict[str, Any], gaps: dict[str, Any]) -> str:
    lines = ["# Anvil Analytical Intelligence Evaluation", "", f"Run: `{run_id}`", f"Mode: `{mode}`", "",
             "## Deterministic results", "", "| Fixture | L1 numerical | L2 semantic | L3 discovery | L4 reasoning | L5 fidelity |",
             "|---|---:|---:|---|---|---|"]
    for result in results:
        levels = result["levels"]
        lines.append(f"| {result['evaluation']['fixture']['id']} | {levels['L1']['score']:.1%} ({levels['L1']['correct']}/{levels['L1']['total']}) | {levels['L2']['score']:.1%} ({levels['L2']['correct']}/{levels['L2']['total']}) | {levels['L3']['status']} | {levels['L4']['status']} | {levels['L5']['status']} |")
    lines += ["", "## Model runs", ""]
    if not model_runs:
        lines.append("Not requested.")
    else:
        lines += ["| Fixture | Run | Status | Model | Duration | Tool calls | Tokens |",
                  "|---|---|---|---|---:|---:|---:|"]
        for item in model_runs:
            evaluation = item.get("evaluation", {})
            metric = evaluation.get("performance", {})
            token_total = (metric.get("tokens") or {}).get("total")
            lines.append(f"| {item['fixture_id']} | `{item['run_id']}` | {item['status']} | {item.get('model','')} | {metric.get('elapsed_ms','—')} ms | {metric.get('tool_calls','—')} | {token_total if token_total is not None else '—'} |")
            if item.get("blocker"):
                lines.append(f"\nBlocker for `{item['run_id']}`: {item['blocker']}\n")
    lines += ["", "## Quality and cost together", "",
              "| Fixture | L1 numerical | L2 semantic | 10k-row FAST helper latency | Model latency | Model/tool calls | Tokens |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    fast_latency = performance.get("depths", {}).get("FAST", {}).get("total", {}).get("median_ms")
    for result in results:
        fixture_id = result["evaluation"]["fixture"]["id"]
        observed = [item for item in model_runs if item.get("fixture_id") == fixture_id and item.get("status") == "COMPLETE"]
        durations = [item["duration_ms"] for item in observed if isinstance(item.get("duration_ms"), (int, float))]
        model_latency = round(sum(durations) / len(durations), 3) if durations else None
        calls = len(observed)
        token_values = [item.get("tokens") for item in observed if isinstance(item.get("tokens"), dict)]
        tokens = sum(value.get("total", value.get("input", 0) + value.get("output", 0)) for value in token_values) if token_values else None
        lines.append(f"| {fixture_id} | {result['levels']['L1']['score']:.1%} | {result['levels']['L2']['score']:.1%} | {fast_latency} ms | {model_latency if model_latency is not None else '—'} ms | {calls} / {sum(item.get('tool_calls') or 0 for item in observed)} | {tokens if tokens is not None else '—'} |")
    lines += ["", "## Performance", "", "| Depth | Operations | Median wall time | Median profile | Median execute |",
              "|---|---:|---:|---:|---:|"]
    for depth, item in performance.get("depths", {}).items():
        lines.append(f"| {depth} | {item['operations']} | {item['total']['median_ms']} ms | {item['profile']['median_ms']} ms | {item['execute_plan_including_second_scan']['median_ms']} ms |")
    if historical.get("status") == "COMPLETE":
        lines += ["", f"Historical 2.13 comparison used committed `{historical['revision'][:12]}` with the same 10k-row generator and operation counts."]
        lines += ["", "| Depth | 2.13 median | 2.14 median | Change |", "|---|---:|---:|---:|"]
        for depth, candidate in performance["depths"].items():
            old = historical["depths"][depth]["total_median_ms"]
            new = candidate["total"]["median_ms"]
            change = (new / old - 1) * 100 if old else 0
            lines.append(f"| {depth} | {old} ms | {new} ms | {change:+.1f}% |")
    else:
        lines += ["", "Historical comparison: `BASELINE_UNAVAILABLE`.", f"Reason: {historical.get('reason', 'not run')}" ]
    investigation = performance.get("fast_path_investigation", {})
    attribution = performance.get("profile_stage_attribution", {})
    lines += ["", "## FAST-path investigation", "",
              f"Classification: **{investigation.get('classification', 'UNKNOWN')}**.",
              f"FAST semantic-inference median: {attribution.get('semantic_inference_median_ms', '—')} ms; "
              f"share of FAST profile: {attribution.get('semantic_inference_share_of_FAST_profile', '—')}.",
              str(investigation.get("reasoning", investigation.get("evidence", "No comparison was available."))),
              "This stage attribution is observational; it is not a safeguard ablation and does not prove every measured operation is necessary."]
    lines += ["", "## Evidence gaps", ""]
    if gaps["gaps"]:
        for gap in gaps["gaps"]:
            lines.append(f"- **{gap['failure_class']}** — {gap['frequency']} observed failure(s), severity {gap['severity']}. {gap['candidate_next_capability']}")
    else:
        lines.append("No deterministic or review failures observed in this run.")
    lines += ["", "## Interpretation", "",
              "L1 and L2 are reported separately. L3–L5 require blind model output and/or structured human review; lexical matching is provisional and is not semantic scoring.",
              "Quality and execution cost are shown together; there is no combined quality score while discovery and communication remain unreviewed.",
              "No analytical production feature was changed to improve this baseline.", "",
              "## Release recommendation", "", "**NOT READY**", "",
              "The controlled model-backed blind evaluation and complete human review have not established analytical discovery, reasoning, claim calibration, and communication quality.", ""]
    return "\n".join(lines)


def _review_template(model_runs: list[dict[str, Any]]) -> dict[str, Any]:
    model_run = next((item for item in model_runs if item.get("evaluation", {}).get("evaluation", {}).get("candidate_output")), None)
    if not model_run:
        return {"schema_version": 1, "note": "No structured model result exists to review.",
                "fixture_id": None, "run_id": None, "finding_annotations": [], "missed_finding_ids": [],
                "claim_annotations": [], "semantic_error_annotations": [], "communication_parity": [],
                "communication_issues": [], "investigation_sufficient": None}
    evaluation = model_run["evaluation"]["evaluation"]
    candidate = evaluation["candidate_output"]
    return {"schema_version": 1, "fixture_id": model_run["fixture_id"], "run_id": model_run["run_id"],
            "reviewer_id": "", "finding_annotations": [
                {"finding_index": index, "matched_ground_truth_ids": [], "supported": False,
                 "materiality_correct": False, "notes": ""} for index, _ in enumerate(candidate["findings"])],
            "missed_finding_ids": [], "claim_annotations": [
                {"claim_index": index, "supported": False, "calibrated": False, "notes": ""}
                for index, _ in enumerate(candidate["claims"])],
            "semantic_error_annotations": [], "communication_parity": [],
            "communication_issues": [], "investigation_sufficient": None}


def run_evaluation(args: argparse.Namespace) -> int:
    if args.dataset and not args.ground_truth:
        raise ValueError("--dataset requires an explicit --ground-truth manifest")
    if args.ground_truth and not args.dataset:
        raise ValueError("--ground-truth is supported with --dataset only")
    if args.dataset:
        private_truth = _read_json(Path(args.ground_truth).expanduser().absolute())
        private_fixture_id = private_truth.get("fixture", {}).get("id") if isinstance(private_truth.get("fixture"), dict) else None
        if not isinstance(private_fixture_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", private_fixture_id):
            raise ValueError("private manifest requires a safe fixture.id identifier")
        if args.fixture not in {"all", private_fixture_id}:
            raise ValueError("--fixture must match fixture.id in the supplied private manifest")
        selected = [private_fixture_id]
    else:
        if args.fixture != "all" and args.fixture not in FIXTURE_IDS:
            raise ValueError("unknown synthetic fixture; private cases require --dataset and --ground-truth")
        selected = [args.fixture] if args.fixture != "all" else list(FIXTURE_IDS)
    mode = args.mode.upper()
    if mode in {"MODEL", "FULL"} and not args.model:
        raise ValueError("MODEL and FULL modes require --model provider/model")
    if not 1 <= args.runs <= 20:
        raise ValueError("--runs must be between 1 and 20")
    if not 1 <= args.benchmark_repetitions <= 20:
        raise ValueError("--benchmark-repetitions must be between 1 and 20")
    output_dir, run_id = _new_run_dir(_output_root(args.output_dir))
    deterministic: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    for fixture_id in selected:
        data_path = args.dataset if args.dataset else None
        truth_path = args.ground_truth if args.ground_truth else None
        result, detail = evaluate_fixture(fixture_id, dataset_path=data_path, ground_truth_path=truth_path,
                                          run_id=f"{run_id}-{fixture_id}-deterministic")
        deterministic.append(result)
        details[fixture_id] = detail

    model_runs: list[dict[str, Any]] = []
    if mode in {"MODEL", "FULL"}:
        for fixture_id in selected:
            for _ in range(args.runs):
                executed = run_blind_once(fixture_id, args.model, dataset_path=args.dataset,
                                          timeout_seconds=args.timeout, binary=args.opencode_bin)
                record: dict[str, Any] = {"fixture_id": fixture_id, **executed}
                if executed["status"] == "COMPLETE":
                    truth = details[fixture_id]["ground_truth"]
                    result = evaluate_candidate(deterministic[selected.index(fixture_id)], executed["candidate"], truth,
                                                model=args.model, runtime=executed["runtime"], run_id=executed["run_id"],
                                                duration_ms=executed["duration_ms"], tool_calls=executed["tool_calls"],
                                                tokens=executed["tokens"])
                    record["evaluation"] = result
                elif executed["status"] == "UNSTRUCTURED_OUTPUT":
                    base = deterministic[selected.index(fixture_id)]
                    result = evaluate_candidate(base, None, details[fixture_id]["ground_truth"], model=args.model,
                                                runtime=executed["runtime"], run_id=executed["run_id"],
                                                duration_ms=executed["duration_ms"], tool_calls=executed["tool_calls"],
                                                tokens=executed["tokens"])
                    record["evaluation"] = result
                model_runs.append(record)

    performance = benchmark_current(repetitions=args.benchmark_repetitions)
    historical = benchmark_historical_2_13(repetitions=args.benchmark_repetitions) if args.compare_2_13 else {
        "status": "BASELINE_UNAVAILABLE", "reason": "Historical comparison was disabled by the caller."}
    _classify_fast_path(performance, historical)
    failures = _failure_summary(deterministic, model_runs)
    model_status = "COMPLETE" if model_runs and all(item["status"] == "COMPLETE" for item in model_runs) else "BLOCKED"
    gaps = _gaps(failures, model_status=model_status)
    baseline_info: dict[str, Any] = {"status": "NOT_FROZEN", "path": str(BASELINE.relative_to(ROOT))}
    if args.freeze_baseline:
        if mode != "DETERMINISTIC" or selected != list(FIXTURE_IDS):
            raise ValueError("the immutable 2.14 baseline can only be frozen from the complete deterministic fixture set")
        baseline_payload = {"schema_version": 1, "baseline_id": "anvil-2.14.0-deterministic-v1",
                            "immutable": True, "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                            "fixture_version": deterministic[0]["evaluation"]["fixture"]["version"],
                            "prompt_version": deterministic[0]["evaluation"]["prompt_version"],
                            "candidate": deterministic[0]["evaluation"]["candidate"],
                            "performance": performance, "historical_2_13": historical,
                            "results": deterministic}
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        _write_new(BASELINE, _json_bytes(baseline_payload), mode=0o444)
        baseline_info = {"status": "FROZEN", "path": str(BASELINE.relative_to(ROOT)),
                         "sha256": __import__("hashlib").sha256(_json_bytes(baseline_payload)).hexdigest()}
    report = {"schema_version": 1, "run_id": run_id, "mode": mode,
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "baseline": baseline_info, "historical_2_13": historical,
              "results": deterministic, "model_run_ids": [item["run_id"] for item in model_runs],
              "release_recommendation": "NOT READY"}
    run_artifact = {"schema_version": 1, "run_id": run_id, "model_runs": model_runs,
                    "aggregation": aggregate_runs(model_runs)}
    summary = _summary(run_id, mode, deterministic, model_runs, performance, historical, gaps)
    artifacts = {"report.json": _json_bytes(report), "runs.json": _json_bytes(run_artifact),
                 "failures.json": _json_bytes({"schema_version": 1, "failures": failures}),
                 "performance.json": _json_bytes({"candidate": performance, "historical_2_13": historical}),
                 "gaps.json": _json_bytes(gaps), "review-template.json": _json_bytes(_review_template(model_runs)),
                 "summary.md": summary.encode("utf-8")}
    for filename, data in artifacts.items():
        target = output_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_new(target, data)
    for item in model_runs:
        if item.get("evaluation", {}).get("evaluation", {}).get("candidate_output"):
            template = _review_template([item])
            _write_new(output_dir / "review-templates" / f"{item['run_id']}.json", _json_bytes(template))
    print(summary)
    print(f"\nArtifacts: {output_dir}")
    if baseline_info["status"] == "FROZEN":
        print(f"Immutable baseline frozen: {baseline_info['path']} ({baseline_info['sha256']})")
    return 0


def apply_review(args: argparse.Namespace) -> int:
    report_path = Path(args.report).expanduser().absolute()
    run_path = report_path.parent / "runs.json"
    review_path = Path(args.review).expanduser().absolute()
    report, run_artifact, review = _read_json(report_path), _read_json(run_path), _read_json(review_path)
    selected = next((item for item in run_artifact.get("model_runs", []) if item.get("run_id") == review.get("run_id")), None)
    if not selected or not selected.get("evaluation"):
        raise ValueError("review run_id must identify a completed structured model run in runs.json")
    fixture_id = selected["fixture_id"]
    truth_path = Path(args.ground_truth).expanduser().absolute() if args.ground_truth else GROUND_TRUTH / f"{fixture_id}.json"
    truth = _read_json(truth_path)
    evaluation = selected["evaluation"]
    normalized = validate_review(review, evaluation, truth)
    metrics = human_metrics(normalized, evaluation, truth)
    evaluation["evaluation"]["human_review"] = metrics
    evaluation["levels"]["L3"].update({"status": "HUMAN_REVIEWED", "material_insight_recall": metrics["material_insight_recall"],
                                        "material_insight_precision": metrics["material_insight_precision"]})
    evaluation["levels"]["L4"].update({"status": "HUMAN_REVIEWED", "claim_calibration": metrics["claim_calibration"],
                                        "unsupported_claim_rate": metrics["unsupported_claim_rate"],
                                        "investigation_sufficient": metrics["investigation_sufficient"]})
    evaluation["levels"]["L5"].update({"status": "HUMAN_REVIEWED", "communication_fidelity": metrics["communication_fidelity"],
                                        "communication_issues": metrics["communication_issues"]})
    evaluation["metrics"].update({key: metrics[key] for key in ("material_insight_recall", "material_insight_precision",
                                      "unsupported_claim_rate", "claim_calibration", "materiality", "communication_fidelity")})
    for item in metrics["semantic_error_annotations"]:
        evaluation["failures"].append({"class": item["class"], "id": "human-semantic-review",
                                        "summary": item["summary"], "evidence": item.get("evidence", {})})
    for issue in metrics["communication_issues"]:
        evaluation["failures"].append({"class": "COMMUNICATION", "id": "human-communication-review",
                                        "summary": issue, "evidence": {"reviewed": True}})
    validate_evaluation_result(evaluation)
    output_dir, new_id = _new_run_dir(_output_root(args.output_dir))
    reviewed = {"schema_version": 1, "source_report": str(report_path.name), "source_run_id": report["run_id"],
                "reviewed_run_id": review["run_id"], "fixture_id": fixture_id, "metrics": metrics,
                "evaluation": evaluation}
    _write_new(output_dir / "review.json", _json_bytes(normalized))
    _write_new(output_dir / "reviewed-report.json", _json_bytes(reviewed))
    md = ["# Human-reviewed analytical evaluation", "", f"Run: `{review['run_id']}`", f"Review artifact: `{new_id}`", "",
          "| Metric | Value |", "|---|---:|"]
    for key in ("material_insight_recall", "material_insight_precision", "unsupported_claim_rate", "claim_calibration",
                "materiality", "communication_fidelity", "investigation_sufficient"):
        md.append(f"| {key.replace('_', ' ')} | {metrics.get(key)} |")
    _write_new(output_dir / "summary.md", ("\n".join(md) + "\n").encode())
    print("\n".join(md))
    print(f"\nReview artifacts: {output_dir}")
    return 0


def run_semantic_certification(args: argparse.Namespace) -> int:
    report = run_certification(repetitions=args.benchmark_repetitions)
    output_root = _output_root(args.output_dir)
    directory = write_semantic_artifacts(report, output_root)
    summary = (directory / "summary.md").read_text(encoding="utf-8")
    print(summary, end="")
    print(f"\nSemantic certification artifacts: {directory}")
    return 0 if all(report["release_gates"].values()) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run offline deterministic and optional blind-model evaluation")
    run.add_argument("--mode", choices=("deterministic", "model", "full"), default="deterministic")
    run.add_argument("--fixture", default="all", help="all, a versioned synthetic fixture, or the id in a private manifest")
    run.add_argument("--dataset", help="explicit local/private table for a single fixture manifest")
    run.add_argument("--ground-truth", help="local/private machine-readable manifest matching --dataset")
    run.add_argument("--model", help="explicit OpenCode provider/model identifier")
    run.add_argument("--runs", type=int, default=1)
    run.add_argument("--timeout", type=int, default=300)
    run.add_argument("--opencode-bin", help="explicit OpenCode executable path")
    run.add_argument("--benchmark-repetitions", type=int, default=5)
    run.add_argument("--output-dir", help="base directory for private, immutable-by-run result artifacts")
    run.add_argument("--compare-2-13", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--freeze-baseline", action="store_true", help="create the checked-in 2.14 baseline once; refuses overwrite")
    review = sub.add_parser("review", help="apply a structured human review as a new immutable artifact")
    review.add_argument("--report", required=True, help="original report.json from a MODEL/FULL run")
    review.add_argument("--review", required=True, help="completed review annotation JSON")
    review.add_argument("--ground-truth", help="local/private manifest; defaults to the versioned synthetic fixture")
    review.add_argument("--output-dir", help="base directory for the review overlay")
    semantic = sub.add_parser("semantic", help="run adversarial semantic certification and bounded performance evaluation")
    semantic.add_argument("--benchmark-repetitions", type=int, default=3)
    semantic.add_argument("--output-dir", help="base directory for private, immutable-by-run result artifacts")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run_evaluation(args)
        if args.command == "review":
            return apply_review(args)
        return run_semantic_certification(args)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR EVALUATION: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
