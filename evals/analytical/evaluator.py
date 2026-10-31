"""Deterministic scoring and evidence summaries for the analytical fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from analysis.primitives import execute_plan  # noqa: E402
from analysis.profiling import profile_file  # noqa: E402

from . import EVALUATION_VERSION, FIXTURE_VERSION, PROMPT_VERSION
from .contracts import FAILURE_CLASSES, validate_candidate, validate_evaluation_result
from .parity import obvious_claim_failures, parity_failures

FIXTURES = ROOT / "evals" / "analytical" / "fixtures"
GROUND_TRUTH = ROOT / "evals" / "analytical" / "ground_truth"

_CATEGORY_BY_FACT = {
    "observations": "NUMERICAL", "entities_total": "ENTITY_RESOLUTION", "composite_observations": "GRAIN",
    "baseline_population": "POPULATION", "current_population": "POPULATION", "retained_population": "COHORT",
    "entrants": "POPULATION", "exits": "POPULATION", "quality_delta_retained": "COHORT",
    "quality_breadth": "COHORT", "response_p95_base": "DISTRIBUTION", "response_p95_current": "DISTRIBUTION",
    "coverage_base": "DISTRIBUTION", "coverage_current": "DISTRIBUTION", "top_two_contribution": "CONTRIBUTION",
}

_DISCOVERY_TERMS = {
    "population-composition": ("population composition", "population changed", "population mix", "retained cohort", "like-for-like"),
    "broad-retained-improvement": ("broad-based improvement", "retained entities improved", "most retained entities", "16 of 16"),
    "concentrated-output": ("concentrated output", "top two entities", "few entities dominate", "contribution concentrated"),
    "stable-mean-worse-tail": ("upper tail", "p95", "tail deteriorated", "distribution worsened"),
    "coverage-decline": ("coverage fell", "coverage declined", "coverage dropped", "coverage decline"),
    "event-vs-service": ("events exceed services", "event count and service count", "more events than services"),
    "composite-service": ("service-zone pairs", "service and zone", "services appear across multiple zones"),
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_fingerprint() -> dict[str, str]:
    evaluation_root = ROOT / "evals" / "analytical"
    paths = [ROOT / "VERSION", ROOT / "scripts" / "runtime_state.py",
             ROOT / "scripts" / "analysis", ROOT / "scripts" / "communication",
             ROOT / "config" / "AGENTS.md", ROOT / "config" / "opencode.jsonc",
             ROOT / "config" / "runtimes" / "opencode-v1.jsonc",
             ROOT / "config" / "skills" / "anvil-communication" / "SKILL.md", evaluation_root]
    result: dict[str, str] = {}
    for path in paths:
        if path.is_file():
            result[str(path.relative_to(ROOT))] = _sha256(path)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if not child.is_file() or "__pycache__" in child.parts:
                    continue
                if path == evaluation_root and child.relative_to(evaluation_root).parts[0] == "baselines":
                    continue
                if child.suffix not in {".py", ".md", ".csv", ".json"}:
                    continue
                result[str(child.relative_to(ROOT))] = _sha256(child)
    return result


def _git_revision() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _path(value: Any, path: list[Any]) -> Any:
    result = value
    for part in path:
        result = result[part]
    return result


def _selected_result(operation: dict[str, Any], binding: dict[str, Any]) -> Any:
    results = operation["results"]
    selector = binding.get("selector")
    if selector:
        def matches(item: Any) -> bool:
            for dotted, expected in selector.items():
                current = item
                for key in dotted.split("."):
                    current = current[key]
                if str(current) != str(expected):
                    return False
            return True
        selected = [item for item in results if matches(item)]
        if len(selected) != 1:
            raise KeyError("selector must resolve to one result row")
        results = selected[0]
    return _path(results, binding.get("path", []))


def _fact_value(binding: dict[str, Any], operations: dict[str, dict[str, Any]]) -> Any:
    operation = operations[binding["operation"]]
    if binding.get("aggregate") == "top_two_absolute_share":
        groups = operation["results"][0]["groups"]
        return sum((_number(item.get("share_of_absolute_change")) or Decimal(0) for item in groups[:2]), Decimal(0))
    return _selected_result(operation, binding)


def _failure(failures: list[dict[str, Any]], category: str, identifier: str, summary: str,
             evidence: dict[str, Any] | None = None) -> None:
    if category not in FAILURE_CLASSES:
        category = "SEMANTIC"
    failures.append({"class": category, "id": identifier, "summary": summary,
                     "evidence": evidence or {}})


def _attach_fixture_id(failures: list[dict[str, Any]], fixture_id: str) -> None:
    for item in failures:
        evidence = item.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        evidence.setdefault("fixture_id", fixture_id)
        item["evidence"] = evidence


def _score_facts(truth: dict[str, Any], operation_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected = {item["id"]: item for item in truth.get("expected_facts", [])}
    records = []
    failures: list[dict[str, Any]] = []
    for fact_id, binding in truth.get("fact_bindings", {}).items():
        target = expected.get(fact_id)
        if target is None:
            continue
        try:
            actual = _fact_value(binding, operation_map)
            expected_number, actual_number = _number(target.get("value")), _number(actual)
            tolerance = _number(target.get("tolerance", "0.000001")) or Decimal("0.000001")
            if expected_number is not None and actual_number is not None:
                correct = abs(expected_number - actual_number) <= tolerance
                expected_value, actual_value = str(expected_number), str(actual_number)
            else:
                correct = target.get("value") == actual
                expected_value, actual_value = target.get("value"), actual
            category = _CATEGORY_BY_FACT.get(fact_id, "NUMERICAL")
            records.append({"fact_id": fact_id, "expected": expected_value, "actual": actual_value,
                            "unit": target.get("unit", "unknown"), "tolerance": str(tolerance),
                            "correct": bool(correct), "evidence_operation": binding["operation"]})
            if not correct:
                _failure(failures, category, f"fact-{fact_id}", f"Deterministic fact {fact_id} differs from hidden ground truth.",
                         {"expected": expected_value, "actual": actual_value, "unit": target.get("unit")})
        except (KeyError, IndexError, TypeError, ValueError, InvalidOperation) as exc:
            records.append({"fact_id": fact_id, "expected": target.get("value"), "actual": None,
                            "unit": target.get("unit", "unknown"), "correct": False,
                            "error": type(exc).__name__, "evidence_operation": binding.get("operation")})
            _failure(failures, _CATEGORY_BY_FACT.get(fact_id, "NUMERICAL"), f"fact-{fact_id}",
                     f"Deterministic result did not expose fact {fact_id} in the expected contract.")
    correct_count = sum(bool(item["correct"]) for item in records)
    return {"level": "L1", "status": "SCORED", "score": correct_count / len(records) if records else None,
            "correct": correct_count, "total": len(records), "facts": records, "failures": failures}


def _semantic_score(profile: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    context = profile.get("semantic_context") or {}
    semantics = truth.get("semantics", {})
    errors: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    expected_observations = next((fact["value"] for fact in truth["expected_facts"] if fact["id"] == "observations"), None)
    observed_count = context.get("observations", {}).get("count")
    count_ok = observed_count == expected_observations
    checks.append({"id": "observation-cardinality", "expected": expected_observations, "actual": observed_count, "correct": count_ok})
    if not count_ok:
        _failure(errors, "NUMERICAL", "semantic-observation-count", "Semantic profile observation count differs from ground truth.",
                 {"expected": expected_observations, "actual": observed_count})

    expected_grain = set(semantics.get("observation_grain", []))
    candidates = [set(item.get("fields", [])) for item in context.get("grain_candidates", [])]
    grain_ok = bool(expected_grain and expected_grain in candidates)
    checks.append({"id": "observation-grain", "expected": sorted(expected_grain),
                   "candidate_grains": [sorted(item) for item in candidates], "correct": grain_ok})
    if not grain_ok:
        _failure(errors, "GRAIN", "observation-grain", "The true observation grain is absent from the semantic grain candidates.",
                 {"expected": sorted(expected_grain), "candidate_grains": [sorted(item) for item in candidates]})

    expected_entities = set(semantics.get("entity_fields", []))
    if semantics.get("entity_field"):
        expected_entities.add(semantics["entity_field"])
    actual_entities = {item["fields"][0] for item in context.get("entities", []) if item.get("fields")}
    missing, extras = sorted(expected_entities - actual_entities), sorted(actual_entities - expected_entities)
    entity_ok = bool(expected_entities) and not missing and not extras
    checks.append({"id": "entity-resolution", "expected": sorted(expected_entities), "actual": sorted(actual_entities),
                   "missing": missing, "false_positive_candidates": extras, "correct": entity_ok})
    if not entity_ok:
        _failure(errors, "ENTITY_RESOLUTION", "entity-resolution", "Entity candidates omit a known entity field or promote non-entity dimensions.",
                 {"expected": sorted(expected_entities), "actual": sorted(actual_entities), "missing": missing, "false_positive_candidates": extras})

    return {"level": "L2", "status": "SCORED", "score": sum(bool(item["correct"]) for item in checks) / len(checks),
            "correct": sum(bool(item["correct"]) for item in checks), "total": len(checks),
            "checks": checks, "semantic_errors": errors}


def _lexical_discovery(candidate: dict[str, Any] | None, truth: dict[str, Any]) -> dict[str, Any]:
    material = truth.get("material_findings", [])
    if not candidate:
        return {"status": "NOT_RUN", "matched": [], "missed": [item["id"] for item in material], "coverage": None}
    text = " ".join([candidate.get("summary", ""),
                     *[item.get("statement", "") for item in candidate.get("findings", [])]]).casefold()
    matched = []
    for finding in material:
        terms = _DISCOVERY_TERMS.get(finding["id"], ())
        if any(term in text for term in terms):
            matched.append(finding["id"])
    missed = [item["id"] for item in material if item["id"] not in matched]
    return {"status": "PROVISIONAL_LEXICAL_ONLY", "matched": matched, "missed": missed,
            "coverage": len(matched) / len(material) if material else None,
            "warning": "Lexical coverage is not semantic equivalence and must not be reported as human-reviewed recall."}


def evaluate_fixture(fixture_id: str, *, dataset_path: str | Path | None = None,
                     ground_truth_path: str | Path | None = None, run_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run production profile/plan and evaluate its observable AnalysisResult evidence."""
    data_path = Path(dataset_path) if dataset_path else FIXTURES / f"{fixture_id}.csv"
    truth_path = Path(ground_truth_path) if ground_truth_path else GROUND_TRUTH / f"{fixture_id}.json"
    truth = _json(truth_path)
    profile = profile_file(data_path)
    plan = truth.get("evaluation_plan")
    if not plan or plan.get("source_sha256") != profile.get("source", {}).get("sha256"):
        raise ValueError("hidden evaluation plan does not match this fixture snapshot")
    execution = execute_plan(str(data_path), plan, profile=profile)
    operation_map = {item["id"]: item for item in execution.get("operations", [])}
    l1 = _score_facts(truth, operation_map)
    l2 = _semantic_score(profile, truth)
    failures = l1["failures"] + l2["semantic_errors"]
    _attach_fixture_id(failures, fixture_id)
    material_count = len(truth.get("material_findings", []))
    numeric_score, semantic_score = l1["score"], l2["score"]
    result = {
        "schema_version": 1,
        "evaluation": {
            "run_id": run_id or "deterministic-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "mode": "DETERMINISTIC", "fixture": {"id": fixture_id, "version": truth["fixture"]["version"],
                "seed": truth["fixture"]["seed"], "sha256": profile["source"]["sha256"],
                "ground_truth_sha256": _sha256(truth_path)},
            "candidate": {"anvil_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
                "git_revision": _git_revision(), "source_fingerprint": _source_fingerprint()},
            "model": None, "runtime": None, "prompt_version": PROMPT_VERSION,
            "evaluation_version": EVALUATION_VERSION, "status": "DETERMINISTIC_COMPLETE",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "levels": {
            "L1": {key: value for key, value in l1.items() if key != "failures"},
            "L2": {key: value for key, value in l2.items() if key != "semantic_errors"},
            "L3": {"status": "NOT_REVIEWED", "material_insight_recall": None,
                   "material_insight_precision": None, "material_findings_expected": material_count,
                   "candidate_findings": 0, "heuristic": _lexical_discovery(None, truth)},
            "L4": {"status": "NOT_REVIEWED", "investigation_depth": None, "claim_calibration": None,
                   "unsupported_claim_rate": None, "candidate_claims": 0},
            "L5": {"status": "NOT_AVAILABLE", "communication_fidelity": None,
                   "surfaces_checked": [], "parity_failures": []},
        },
        "metrics": {"numerical_correctness": numeric_score, "semantic_correctness": semantic_score,
                    "material_insight_recall": None, "material_insight_precision": None,
                    "unsupported_claim_rate": None, "claim_calibration": None, "materiality": None,
                    "communication_fidelity": None,
                    "semantic_error_rate": len(l2["semantic_errors"]) / max(l2["total"], 1),
                    "quality_cost_north_star": None},
        "performance": {}, "failures": failures,
        "observations": ["Production AnalysisResult has deterministic metrics but no model-generated findings or claims.",
                         "L3-L5 are intentionally unscored until a blind model run and structured human review are available."],
    }
    return validate_evaluation_result(result), {"profile": profile, "execution": execution, "ground_truth": truth}


def evaluate_candidate(base_result: dict[str, Any], candidate_raw: dict[str, Any] | None,
                       truth: dict[str, Any], *, model: str, runtime: str | None,
                       run_id: str, duration_ms: float, tool_calls: int | None,
                       tokens: dict[str, int] | None = None) -> dict[str, Any]:
    """Score a blind model response without confusing deterministic facts and semantics."""
    result = deepcopy(base_result)
    evaluation = result["evaluation"]
    evaluation.update({"run_id": run_id, "mode": "MODEL", "model": model, "runtime": runtime,
                       "status": "MODEL_COMPLETE", "duration_ms": round(duration_ms, 3),
                       "tool_calls": tool_calls, "tokens": tokens})
    result["performance"] = {"elapsed_ms": round(duration_ms, 3), "model_calls": 1,
                              "tool_calls": tool_calls, "tokens": tokens}
    if candidate_raw is None:
        evaluation["status"] = "MODEL_UNSTRUCTURED"
        result["levels"]["L3"]["status"] = "UNSTRUCTURED_OUTPUT"
        result["levels"]["L4"]["status"] = "UNSTRUCTURED_OUTPUT"
        result["levels"]["L5"]["status"] = "UNSTRUCTURED_OUTPUT"
        result["failures"].append({"class": "INFRASTRUCTURE", "id": "model-output-contract",
                                    "summary": "The model response did not match the versioned observable-output JSON contract.", "evidence": {}})
        return validate_evaluation_result(result)
    candidate = validate_candidate(candidate_raw)
    semantics = truth.get("semantics", {})
    expected_grain = set(semantics.get("observation_grain", []))
    observed_grain = set(candidate["semantics"]["observation_grain"])
    expected_entities = set(semantics.get("entity_fields", []))
    if semantics.get("entity_field"):
        expected_entities.add(semantics["entity_field"])
    observed_entities = set(candidate["semantics"]["entity_fields"])
    candidate_l2_errors = []
    if expected_grain != observed_grain:
        _failure(candidate_l2_errors, "GRAIN", "model-observation-grain", "Blind model identified an observation grain different from ground truth.",
                 {"expected": sorted(expected_grain), "actual": sorted(observed_grain)})
    if expected_entities != observed_entities:
        _failure(candidate_l2_errors, "ENTITY_RESOLUTION", "model-entity-fields", "Blind model entity fields differ from the fixture semantics.",
                 {"expected": sorted(expected_entities), "actual": sorted(observed_entities)})
    result["levels"]["L2"]["model_candidate"] = {"score": 1 - len(candidate_l2_errors) / 2,
        "checks": [{"id": "observation-grain", "expected": sorted(expected_grain), "actual": sorted(observed_grain), "correct": expected_grain == observed_grain},
                   {"id": "entity-resolution", "expected": sorted(expected_entities), "actual": sorted(observed_entities), "correct": expected_entities == observed_entities}],
        "errors": candidate_l2_errors}
    result["failures"].extend(candidate_l2_errors)

    heuristic = _lexical_discovery(candidate, truth)
    result["levels"]["L3"] = {"status": "PROVISIONAL_HEURISTIC", "material_insight_recall": None,
        "material_insight_precision": None, "material_findings_expected": len(truth.get("material_findings", [])),
        "candidate_findings": len(candidate["findings"]), "heuristic": heuristic}
    for missing in heuristic["missed"]:
        _failure(result["failures"], "DISCOVERY", f"heuristic-missed-{missing}",
                 f"Lexical screen did not find material phenomenon {missing}; human semantic review is required.", {"ground_truth_finding_id": missing})

    period_count = next((int(item["value"]) for item in truth.get("expected_facts", [])
                         if item.get("id") == "time_periods"), None)
    claim_failures = obvious_claim_failures(candidate, period_count=period_count,
                                             forbidden_claims=truth.get("forbidden_claims", []))
    parity = parity_failures(candidate)
    result["levels"]["L4"] = {"status": "PARTIAL_RULES_ONLY", "investigation_depth": None,
        "claim_calibration": None, "unsupported_claim_rate": None, "candidate_claims": len(candidate["claims"]),
        "obvious_rule_failures": claim_failures,
        "note": "Human review is still required for semantic support, reasoning depth, and calibration."}
    result["levels"]["L5"] = {"status": "PARTIAL_RULES_ONLY", "communication_fidelity": None,
        "surfaces_checked": sorted(name for name, entries in candidate["surfaces"].items() if entries),
        "parity_failures": parity,
        "note": "Structured fact parity is deterministic; prose and visual hierarchy require human review."}
    result["failures"].extend(claim_failures)
    result["failures"].extend(parity)
    _attach_fixture_id(result["failures"], evaluation["fixture"]["id"])
    result["metrics"].update({"material_insight_recall": None, "material_insight_precision": None,
        "unsupported_claim_rate": None, "claim_calibration": None, "materiality": None,
        "communication_fidelity": None})
    evaluation["candidate_output"] = candidate
    result["observations"].append("Lexical discovery coverage is provisional and is not reported as semantic recall.")
    return validate_evaluation_result(result)
