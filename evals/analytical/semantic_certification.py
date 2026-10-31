"""Adversarial semantic certification built on the production profile contract.

Public inputs and hidden expected answers stay separate. This module is evaluator
code; production inference never imports it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import subprocess
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "evals" / "analytical" / "fixtures" / "semantic-foundation-v1.json"
TRUTH_PATH = ROOT / "evals" / "analytical" / "ground_truth" / "semantic-foundation-v1.json"
PROTOCOL = "semantic-certification-v1"
CONFIDENCE_VALUE = {"HIGH": 0.95, "MEDIUM": 0.75, "LOW": 0.55, "UNKNOWN": 0.50}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    public, truth = _json(FIXTURE_PATH), _json(TRUTH_PATH)
    if public.get("schema_version") != 1 or public.get("fixture_version") != "semantic-foundation-v1":
        raise ValueError("unsupported semantic fixture snapshot")
    if truth.get("evaluation_protocol") != PROTOCOL or truth.get("fixture_version") != public["fixture_version"]:
        raise ValueError("semantic ground truth protocol does not match public fixture snapshot")
    if [item["id"] for item in public.get("cases", [])] != [item["id"] for item in truth.get("cases", [])]:
        raise ValueError("public semantic cases and hidden ground truth do not have identical case IDs")
    return public["cases"], {item["id"]: item for item in truth["cases"]}


def _profile(case: dict[str, Any], *, depth: str = "STANDARD") -> dict[str, Any]:
    """Run the real profile entry point on an isolated temporary CSV."""
    from scripts.analysis.profiling import profile_file

    with tempfile.TemporaryDirectory(prefix="anvil-semantic-case-") as temporary:
        path = Path(temporary) / "input.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=case["columns"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(case["rows"])
        return profile_file(path, semantic_depth=depth,
                            semantic_metadata=case.get("semantic_metadata"))["semantic_context"]


def _entity_keys(context: dict[str, Any]) -> list[tuple[str, ...]]:
    return sorted({tuple(item.get("fields", [])) for item in context.get("entities", []) if item.get("fields")})


def _field_roles(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["field"]: item for item in context.get("field_roles", []) if isinstance(item.get("field"), str)}


def _grain_fields(context: dict[str, Any]) -> tuple[str, ...]:
    return tuple(context.get("grain", {}).get("fields", []))


def _role_score(context: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    actual = _field_roles(context)
    checks = [{"field": name, "expected": role, "actual": actual.get(name, {}).get("role"),
               "correct": actual.get(name, {}).get("role") == role}
              for name, role in expected.items()]
    return {"correct": sum(item["correct"] for item in checks), "total": len(checks),
            "accuracy": sum(item["correct"] for item in checks) / len(checks) if checks else None,
            "checks": checks}


def _grain_class(actual: tuple[str, ...], expected: tuple[str, ...],
                 rows: list[dict[str, Any]]) -> str:
    if not actual:
        return "UNKNOWN"
    if set(actual) == set(expected):
        return "EXACT"
    if not expected:
        return "WRONG"
    def partition(fields: tuple[str, ...]) -> tuple[int, ...]:
        labels: dict[str, int] = {}
        result = []
        for row in rows:
            key = json.dumps([row.get(field) for field in fields], ensure_ascii=False, sort_keys=True, default=str)
            if key not in labels:
                labels[key] = len(labels)
            result.append(labels[key])
        return tuple(result)
    if set(actual) <= set(rows[0]) and set(expected) <= set(rows[0]) and partition(actual) == partition(expected):
        return "SEMANTICALLY_EQUIVALENT"
    if set(actual) <= set(expected):
        return "UNDER_SPECIFIED"
    if set(expected) < set(actual):
        return "OVER_SPECIFIED"
    if set(actual) & set(expected):
        return "PARTIAL"
    return "WRONG"


def _case_metrics(case: dict[str, Any], truth: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    expected_entities = {tuple(group) for group in truth.get("entity_keys", [])}
    actual_entities = set(_entity_keys(context))
    true_positives = actual_entities & expected_entities
    false_positives = actual_entities - expected_entities
    false_negatives = expected_entities - actual_entities
    candidates = {tuple(item["fields"]): item for item in context.get("entities", []) if item.get("fields")}
    high = {fields for fields, item in candidates.items() if item.get("confidence") == "HIGH"}
    grain = _grain_fields(context)
    expected_grain = tuple(truth.get("grain", []))
    grain_result = _grain_class(grain, expected_grain, case["rows"])
    event_actual = {tuple(item.get("fields", [])) for item in context.get("event_key_candidates", [])}
    event_expected = {tuple(group) for group in truth.get("event_keys", [])}
    roles = _role_score(context, truth.get("roles", {}))
    entity_expected_empty = bool(truth.get("abstain_entity"))
    grain_expected_empty = bool(truth.get("abstain_grain"))
    entity_abstention_correct = not actual_entities if entity_expected_empty else True
    grain_abstention_correct = not grain if grain_expected_empty else True
    confidence_pairs = []
    for fields, item in candidates.items():
        confidence_pairs.append({"fields": list(fields), "confidence": item.get("confidence", "UNKNOWN"),
                                 "correct": fields in expected_entities,
                                 "predicted_probability": CONFIDENCE_VALUE.get(item.get("confidence"), 0.5)})
    for fields in false_negatives:
        confidence_pairs.append({"fields": list(fields), "confidence": "UNKNOWN", "correct": False,
                                 "predicted_probability": 0.5, "missed_expected_candidate": True})
    if not expected_entities:
        confidence_pairs.append({"fields": [], "confidence": "UNKNOWN", "correct": not actual_entities,
                                 "predicted_probability": CONFIDENCE_VALUE["UNKNOWN"],
                                 "decision": "entity_abstention"})
    brier = (sum((item["predicted_probability"] - float(item["correct"])) ** 2 for item in confidence_pairs)
             / len(confidence_pairs)) if confidence_pairs else None
    def determinant_fields(item: dict[str, Any]) -> tuple[str, ...]:
        determinant = item["determinant"]
        return (determinant,) if isinstance(determinant, str) else tuple(determinant)
    expected_fds = {(determinant_fields(item), item["dependent"])
                    for item in truth.get("functional_dependencies", [])}
    forbidden_fds = {(determinant_fields(item), item["dependent"])
                     for item in truth.get("forbidden_functional_dependencies", [])}
    actual_fds = {(tuple(item.get("determinant", [])), item.get("dependent"))
                  for item in context.get("functional_dependencies", [])}
    fd_checks = [{"determinant": list(determinant), "dependent": dependent, "expected": True,
                  "correct": (determinant, dependent) in actual_fds}
                 for determinant, dependent in sorted(expected_fds)]
    fd_checks += [{"determinant": list(determinant), "dependent": dependent, "expected": False,
                   "correct": (determinant, dependent) not in actual_fds}
                  for determinant, dependent in sorted(forbidden_fds)]
    expected_composite_entity_keys = {fields for fields in expected_entities if len(fields) > 1}
    actual_composite_entity_keys = {fields for fields in actual_entities if len(fields) > 1}
    return {
        "id": case["id"],
        "entities": {"expected": [list(x) for x in sorted(expected_entities)],
                     "actual": [list(x) for x in sorted(actual_entities)],
                     "true_positive": [list(x) for x in sorted(true_positives)],
                     "false_positive": [list(x) for x in sorted(false_positives)],
                     "false_negative": [list(x) for x in sorted(false_negatives)],
                     "high_confidence_false_positive": [list(x) for x in sorted(high - expected_entities)],
                     "confidence": [{"fields": list(fields), "confidence": candidates[fields].get("confidence", "UNKNOWN")}
                                    for fields in sorted(candidates)]},
        "grain": {"expected": list(expected_grain), "actual": list(grain), "classification": grain_result,
                  "composite": len(expected_grain) > 1, "expected_unknown": grain_expected_empty,
                  "confidence": context.get("grain", {}).get("confidence", "UNKNOWN")},
        "event_keys": {"expected": [list(x) for x in sorted(event_expected)],
                       "actual": [list(x) for x in sorted(event_actual)],
                       "correct": event_expected == event_actual},
        "composite_entity_keys": {"expected": [list(x) for x in sorted(expected_composite_entity_keys)],
                                  "actual": [list(x) for x in sorted(actual_composite_entity_keys)],
                                  "correct": expected_composite_entity_keys == actual_composite_entity_keys},
        "roles": roles,
        "abstention": {"entity_expected": entity_expected_empty, "entity_correct": entity_abstention_correct,
                       "grain_expected": grain_expected_empty, "grain_correct": grain_abstention_correct},
        "confidence_observations": confidence_pairs,
        "confidence_brier": brier,
        "duplicate_risk_expected": bool(truth.get("duplicate_risk")),
        "duplicate_risk_actual": any(item.get("code") == "DUPLICATE_OBSERVATIONS"
                                      for item in context.get("quality_risks", [])),
        "metadata_expected": bool(truth.get("metadata_expected")),
        "metadata_used": bool(context.get("metadata_evidence", {}).get("provided")),
        "functional_dependencies": context.get("functional_dependencies", []),
        "functional_dependency_checks": fd_checks,
        "technical_time_roles": {name: next((item["temporal_role"] for item in context.get("temporal_dimensions", [])
                                              if item.get("field") == name), None)
                                 for name in truth.get("technical_times", {})},
        "expected_technical_time_roles": truth.get("technical_times", {}),
        "dataset_shape": context.get("dataset_shape"),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _aggregate(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    expected_entities = sum(len(item["entities"]["expected"]) for item in case_results)
    predicted_entities = sum(len(item["entities"]["actual"]) for item in case_results)
    correct_entities = sum(len(item["entities"]["true_positive"]) for item in case_results)
    high_correct = sum(1 for item in case_results for candidate in item["entities"]["confidence"]
                       if candidate["confidence"] == "HIGH" and candidate["fields"] in item["entities"]["expected"])
    high_false = sum(len(item["entities"]["high_confidence_false_positive"]) for item in case_results)
    false_positive = sum(len(item["entities"]["false_positive"]) for item in case_results)
    role_correct = sum(item["roles"]["correct"] for item in case_results)
    role_total = sum(item["roles"]["total"] for item in case_results)
    grain_counts: dict[str, int] = defaultdict(int)
    for item in case_results:
        grain_counts[item["grain"]["classification"]] += 1
    grain_evaluable = [item for item in case_results if not item["grain"]["expected_unknown"]]
    grain_correct = sum(item["grain"]["classification"] in {"EXACT", "SEMANTICALLY_EQUIVALENT"}
                        for item in grain_evaluable)
    confidence = [entry for result in case_results for entry in result["confidence_observations"]]
    brier_values = [item["confidence_brier"] for item in case_results if item["confidence_brier"] is not None]
    calibration_by_level = {}
    for level in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        values = [item for item in confidence if item["confidence"] == level]
        calibration_by_level[level] = {"count": len(values), "empirical_accuracy": _ratio(sum(item["correct"] for item in values), len(values)),
                                       "mean_predicted_probability": CONFIDENCE_VALUE[level] if values else None}
    abstention_checks = [item for result in case_results for key, value in result["abstention"].items()
                         if key.endswith("_correct") and result["abstention"][key.replace("_correct", "_expected")]]
    composite = [item for item in case_results if item["grain"]["composite"]]
    composite_exact = sum(item["grain"]["classification"] in {"EXACT", "SEMANTICALLY_EQUIVALENT"} for item in composite)
    return {
        "case_count": len(case_results),
        "entity_precision": _ratio(correct_entities, predicted_entities),
        "entity_recall": _ratio(correct_entities, expected_entities),
        "entity_counts": {"true_positive": correct_entities, "predicted": predicted_entities,
                          "expected": expected_entities, "false_positive": false_positive},
        "false_entity_candidate_rate": _ratio(false_positive, predicted_entities),
        "high_confidence_entity_precision": _ratio(high_correct, high_correct + high_false),
        "high_confidence_entity_counts": {"correct": high_correct, "false_positive": high_false},
        "grain_accuracy": _ratio(grain_correct, len(grain_evaluable)),
        "grain_evaluable_counts": {"correct": grain_correct, "total": len(grain_evaluable)},
        "grain_classifications": dict(sorted(grain_counts.items())),
        "composite_grain_accuracy": _ratio(composite_exact, len(composite)),
        "composite_grain_counts": {"correct": composite_exact, "total": len(composite)},
        "composite_entity_key_accuracy": _ratio(
            sum(item["composite_entity_keys"]["correct"] for item in case_results
                if item["composite_entity_keys"]["expected"] or item["composite_entity_keys"]["actual"]),
            sum(bool(item["composite_entity_keys"]["expected"] or item["composite_entity_keys"]["actual"])
                for item in case_results)),
        "functional_dependency_accuracy": _ratio(
            sum(check["correct"] for item in case_results for check in item["functional_dependency_checks"]),
            sum(len(item["functional_dependency_checks"]) for item in case_results)),
        "role_classification_accuracy": _ratio(role_correct, role_total),
        "role_counts": {"correct": role_correct, "total": role_total},
        "event_key_accuracy": _ratio(sum(item["event_keys"]["correct"] for item in case_results
                                          if item["event_keys"]["expected"] or item["event_keys"]["actual"]),
                                      sum(bool(item["event_keys"]["expected"] or item["event_keys"]["actual"])
                                          for item in case_results)),
        "technical_time_role_accuracy": _ratio(
            sum(actual.get(name) == role for item in case_results
                for name, role in item["expected_technical_time_roles"].items()
                for actual in [item["technical_time_roles"]]),
            sum(len(item["expected_technical_time_roles"]) for item in case_results)),
        "abstention_accuracy": _ratio(sum(item["abstention"][key] for item in case_results
                                           for key in ("entity_correct", "grain_correct")
                                           if item["abstention"][key.replace("_correct", "_expected")]),
                                      sum(1 for item in case_results for key in ("entity_correct", "grain_correct")
                                          if item["abstention"][key.replace("_correct", "_expected")])),
        "confidence_calibration": {"brier_score": _ratio(sum(brier_values), len(brier_values)),
                                   "by_level": calibration_by_level,
                                   "interpretation": "Confidence maps to explicit evaluator probabilities; this score is comparative, not a claim of statistical calibration."},
    }


def _signature(context: dict[str, Any]) -> tuple[Any, ...]:
    return (tuple(_entity_keys(context)), tuple(sorted(_grain_fields(context))),
            tuple(sorted((item["field"], item["role"]) for item in context.get("field_roles", []))))


def _case_with_rows(case: dict[str, Any], rows: list[dict[str, Any]], columns: list[str] | None = None) -> dict[str, Any]:
    return {**case, "columns": columns or case["columns"], "rows": rows}


def _metamorphic(cases: list[dict[str, Any]], contexts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base_case = next(item for item in cases if item["id"] == "A-repeated-entity")
    base = contexts[base_case["id"]]
    base_sig = _signature(base)
    rows, columns = base_case["rows"], base_case["columns"]
    checks = []

    shuffled = list(rows)
    random.Random(71231).shuffle(shuffled)
    check = _signature(_profile(_case_with_rows(base_case, shuffled))) == base_sig
    checks.append({"id": "row_shuffle", "passed": check, "invariant": "entity, grain and roles are row-order independent"})

    reversed_columns = list(reversed(columns))
    reordered_rows = [{name: row[name] for name in reversed_columns} for row in rows]
    check = _signature(_profile(_case_with_rows(base_case, reordered_rows, reversed_columns))) == base_sig
    checks.append({"id": "column_order", "passed": check, "invariant": "entity, grain and roles are column-order independent"})

    renamed = {old: f"field_{index}" for index, old in enumerate(columns)}
    renamed_case = _case_with_rows(base_case, [{renamed[key]: value for key, value in row.items()} for row in rows],
                                   [renamed[key] for key in columns])
    renamed_context = _profile(renamed_case)
    mapped_entities = {tuple(sorted(renamed.get(field, field) for field in group)) for group in _entity_keys(renamed_context)}
    expected_entities = {tuple(sorted(renamed[field] for field in group)) for group in _entity_keys(base)}
    mapped_grain = tuple(sorted(renamed.get(field, field) for field in _grain_fields(renamed_context)))
    expected_grain = tuple(sorted(renamed[field] for field in _grain_fields(base)))
    passed = mapped_entities == expected_entities and mapped_grain == expected_grain
    checks.append({"id": "safe_renaming", "passed": passed,
                   "invariant": "neutral renaming preserves structurally supported entity and grain"})

    with_row_id = [{**row, "row_uuid": f"row-{index:06d}"} for index, row in enumerate(rows)]
    technical_case = _case_with_rows(base_case, with_row_id, [*columns, "row_uuid"])
    technical_context = _profile(technical_case)
    technical_roles = _field_roles(technical_context)
    passed = _entity_keys(technical_context) == _entity_keys(base) and _grain_fields(technical_context) == _grain_fields(base)
    passed = passed and technical_roles.get("row_uuid", {}).get("role") in {"TECHNICAL_KEY_CANDIDATE", "CANDIDATE_KEY"}
    checks.append({"id": "add_technical_id", "passed": passed,
                   "invariant": "unique row identifier does not replace entity or observation grain"})

    with_dimension = [{**row, "operator_note": ("a", "b", "c")[index % 3]} for index, row in enumerate(rows)]
    dimension_context = _profile(_case_with_rows(base_case, with_dimension, [*columns, "operator_note"]))
    passed = _entity_keys(dimension_context) == _entity_keys(base) and _grain_fields(dimension_context) == _grain_fields(base)
    checks.append({"id": "add_irrelevant_dimension", "passed": passed,
                   "invariant": "an unrelated non-key category does not alter entity or grain"})

    duplicated_context = _profile(_case_with_rows(base_case, rows + [dict(row) for row in rows]))
    passed = _entity_keys(duplicated_context) == _entity_keys(base)
    passed = passed and any(item.get("code") == "DUPLICATE_OBSERVATIONS" for item in duplicated_context.get("quality_risks", []))
    checks.append({"id": "duplicate_dataset", "passed": passed,
                   "invariant": "duplicating rows preserves entity candidates and reports duplicate risk"})

    subset_rows = [row for row in rows if row["period"] in {"2025-01", "2025-02"}]
    subset_context = _profile(_case_with_rows(base_case, subset_rows))
    passed = _entity_keys(subset_context) == _entity_keys(base)
    passed = passed and set(_grain_fields(subset_context)) == set(_grain_fields(base))
    checks.append({"id": "representative_subsample", "passed": passed,
                   "invariant": "representative temporal subset retains the semantic key with possible confidence reduction"})

    no_time_rows = [{key: value for key, value in row.items() if key != "period"} for row in rows]
    no_time_context = _profile(_case_with_rows(base_case, no_time_rows, ["entity_id", "metric"]))
    passed = _entity_keys(no_time_context) == _entity_keys(base) and "period" not in _grain_fields(no_time_context)
    checks.append({"id": "remove_time", "passed": passed,
                   "invariant": "entity remains while removed time no longer appears in grain"})

    ingestion_rows = [{**row, "ingested_at": f"2025-06-01T00:00:{index % 60:02d}.{index:06d}"}
                      for index, row in enumerate(rows)]
    ingestion_case = _case_with_rows(base_case, ingestion_rows, [*columns, "ingested_at"])
    ingestion_context = _profile(ingestion_case)
    passed = _entity_keys(ingestion_context) == _entity_keys(base)
    passed = passed and set(_grain_fields(ingestion_context)) == set(_grain_fields(base))
    checks.append({"id": "add_ingestion_timestamp", "passed": passed,
                   "invariant": "technical ingestion time does not expand business grain"})
    return {"checks": checks, "passed": sum(item["passed"] for item in checks), "total": len(checks),
            "stability": _ratio(sum(item["passed"] for item in checks), len(checks))}


def _sensitivity() -> dict[str, Any]:
    cases = []
    for size in (10, 100, 1_000, 10_000):
        from datetime import timedelta
        rows = [{"entity_id": f"E{index % 5:03d}",
                 "period": (datetime(2025, 1, 1) + timedelta(days=index // 5)).date().isoformat(),
                 "metric": index % 97} for index in range(size)]
        case = {"id": f"sample-size-{size}", "columns": ["entity_id", "period", "metric"], "rows": rows}
        context = _profile(case, depth="FAST")
        cases.append({"dimension": "sample_size", "value": size, "entity_candidate_count": len(_entity_keys(context)),
                      "entity_cardinalities": [item.get("cardinality") for item in context.get("entities", [])],
                      "grain": list(_grain_fields(context)), "entity_confidence": [item["confidence"] for item in context.get("entities", [])]})
    for cardinality in (3, 10, 100, 1_000):
        rows = [{"device_id": f"D{entity:05d}", "period": f"2025-{period:02d}", "reading": entity + period}
                for entity in range(cardinality) for period in range(1, 4)]
        case = {"id": f"cardinality-{cardinality}", "columns": ["device_id", "period", "reading"], "rows": rows}
        context = _profile(case, depth="FAST")
        cases.append({"dimension": "entity_cardinality", "value": cardinality,
                      "entity_candidate_count": len(_entity_keys(context)),
                      "entity_cardinalities": [item.get("cardinality") for item in context.get("entities", [])],
                      "grain": list(_grain_fields(context)),
                      "entity_confidence": [item["confidence"] for item in context.get("entities", [])]})

    temporal = {
        "one_time": [{"device_id": f"D{i}", "period": "2025-01", "reading": i} for i in range(10)],
        "missing_periods": [{"device_id": f"D{i}", "period": f"2025-{period:02d}", "reading": i + period}
                            for i in range(10) for period in (1, 3)],
        "irregular": [{"device_id": f"D{i}", "period": f"2025-{period:02d}", "reading": i + period}
                      for i in range(10) for period in (1, 2, 5)],
        "long_lived": [{"device_id": f"D{i}", "period": f"2025-{period:02d}", "reading": i + period}
                       for i in range(10) for period in range(1, 13)],
    }
    for density, rows in temporal.items():
        case = {"id": f"temporal-{density}", "columns": ["device_id", "period", "reading"], "rows": rows}
        context = _profile(case, depth="FAST")
        cases.append({"dimension": "temporal_density", "value": density,
                      "entity_candidate_count": len(_entity_keys(context)),
                      "entity_cardinalities": [item.get("cardinality") for item in context.get("entities", [])],
                      "grain": list(_grain_fields(context)),
                      "entity_confidence": [item["confidence"] for item in context.get("entities", [])]})
    return {"observations": cases,
            "note": "Sensitivity points are descriptive checks; sample-derived confidence is not a population guarantee."}


def _mutation_checks(case_results: list[dict[str, Any]], base_contexts: dict[str, dict[str, Any]],
                     cases: list[dict[str, Any]], truths: dict[str, Any]) -> dict[str, Any]:
    original = _aggregate(case_results)
    operations = next(item for item in cases if item["id"] == "A-repeated-entity")
    event = next(item for item in cases if item["id"] == "B-event-identifier")
    aggregate = next(item for item in cases if item["id"] == "H-aggregated")
    mutants = {
        "promote_rows_as_entity": (operations["id"], {"entity_keys": [["row_count"]]}, ["row_count"]),
        "promote_event_key": (event["id"], {"entity_keys": [["event_id"]]}, ["event_id"]),
        "promote_dimension": (aggregate["id"], {"entity_keys": [["region"]]}, ["region"]),
        "promote_functionally_dependent_dimension": (
            next(item for item in cases if item["id"] == "R-stable-functional-dependency")["id"],
            {"entity_keys": [["customer_id", "region"]]}, ["customer_id", "period"]),
        "technical_timestamp_in_grain": (operations["id"], {"entity_keys": [["entity_id"]]}, ["entity_id", "period", "ingested_at"]),
        "miss_composite_grain": (next(item for item in cases if item["id"] == "C-composite-observation-grain")["id"],
                                  None, ["customer_id", "period"]),
        "abstain_all_entities": ("__all__", None, None),
        "suppress_all_confidence": ("__confidence__", None, None),
    }
    results = []
    baseline_by_id = {item["id"]: item for item in case_results}
    for name, (fixture_id, entity_override, grain_override) in mutants.items():
        if fixture_id == "__confidence__":
            replaced = json.loads(json.dumps(case_results))
            for item in replaced:
                for candidate in item["entities"]["confidence"]:
                    candidate["confidence"] = "UNKNOWN"
                for evidence in item["confidence_observations"]:
                    evidence["confidence"] = "UNKNOWN"
                    evidence["predicted_probability"] = CONFIDENCE_VALUE["UNKNOWN"]
                item["confidence_brier"] = (sum((evidence["predicted_probability"] - float(evidence["correct"])) ** 2
                                                 for evidence in item["confidence_observations"])
                                             / len(item["confidence_observations"])) if item["confidence_observations"] else None
            score = _aggregate(replaced)
            caught = score["confidence_calibration"]["brier_score"] > original["confidence_calibration"]["brier_score"]
            results.append({"mutation": name, "caught": caught,
                            "confidence_brier_before": original["confidence_calibration"]["brier_score"],
                            "confidence_brier_after": score["confidence_calibration"]["brier_score"]})
            continue
        if fixture_id == "__all__":
            replaced = json.loads(json.dumps(case_results))
            for item in replaced:
                item["entities"]["false_negative"] = item["entities"]["expected"]
                item["entities"]["true_positive"] = []
                item["entities"]["actual"] = []
                item["entities"]["false_positive"] = []
                item["entities"]["high_confidence_false_positive"] = []
                item["entities"]["confidence"] = []
                item["confidence_observations"] = [entry for entry in item["confidence_observations"]
                                                    if entry.get("missed_expected_candidate")]
                item["confidence_brier"] = 0.25 if item["confidence_observations"] else None
            score = _aggregate(replaced)
            caught = (score["entity_recall"] or 0) < (original["entity_recall"] or 0)
            results.append({"mutation": name, "caught": caught,
                            "entity_recall_before": original["entity_recall"],
                            "entity_recall_after": score["entity_recall"]})
            continue
        mutated = json.loads(json.dumps(baseline_by_id[fixture_id]))
        if entity_override is not None:
            fields = list(entity_override["entity_keys"][0])
            mutated["entities"]["actual"] = [fields]
            mutated["entities"]["confidence"] = [{"fields": fields, "confidence": "HIGH"}]
            mutated["entities"]["false_positive"] = [fields] if fields not in mutated["entities"]["expected"] else []
            mutated["entities"]["true_positive"] = [] if fields not in mutated["entities"]["expected"] else [fields]
            mutated["entities"]["false_negative"] = mutated["entities"]["expected"] if fields not in mutated["entities"]["expected"] else []
            mutated["entities"]["high_confidence_false_positive"] = mutated["entities"]["false_positive"]
        mutated["grain"]["actual"] = grain_override
        expected = tuple(mutated["grain"]["expected"])
        mutated["grain"]["classification"] = _grain_class(tuple(grain_override), expected,
                                                         next(item["rows"] for item in cases if item["id"] == fixture_id))
        replaced = [mutated if item["id"] == fixture_id else item for item in case_results]
        score = _aggregate(replaced)
        caught = (score["entity_precision"] or 0) < (original["entity_precision"] or 0) or \
                 score["entity_recall"] < original["entity_recall"] or \
                 score["grain_accuracy"] < original["grain_accuracy"] or \
                 score["composite_grain_accuracy"] < original["composite_grain_accuracy"]
        results.append({"mutation": name, "caught": bool(caught),
                        "entity_precision_before": original["entity_precision"], "entity_precision_after": score["entity_precision"],
                        "grain_accuracy_before": original["grain_accuracy"], "grain_accuracy_after": score["grain_accuracy"],
                        "composite_grain_accuracy_before": original["composite_grain_accuracy"],
                        "composite_grain_accuracy_after": score["composite_grain_accuracy"]})
    return {"checks": results, "passed": sum(item["caught"] for item in results), "total": len(results)}


def _ablation_results(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {case["id"]: case for case in cases}
    metadata_case = by_id["W-authoritative-metadata"]
    with_metadata = _profile(metadata_case)
    without_case = {key: value for key, value in metadata_case.items() if key != "semantic_metadata"}
    without_metadata = _profile(without_case)
    lexical_case = by_id["A-repeated-entity"]
    renamed = {name: f"field_{index}" for index, name in enumerate(lexical_case["columns"])}
    neutral_case = _case_with_rows(lexical_case,
                                   [{renamed[key]: value for key, value in row.items()} for row in lexical_case["rows"]],
                                   [renamed[name] for name in lexical_case["columns"]])
    neutral = _profile(neutral_case)
    misleading_case = by_id["X-misleading-name"]
    misleading = _profile(misleading_case)
    return {
        "lexical_ablation": {
            "descriptive": {"entities": [list(x) for x in _entity_keys(_profile(lexical_case))],
                            "grain": list(_grain_fields(_profile(lexical_case)))},
            "neutral": {"entities": [list(x) for x in _entity_keys(neutral)],
                        "grain": list(_grain_fields(neutral)),
                        "confidence": [item["confidence"] for item in neutral.get("entities", [])]},
            "misleading": {"entities": [list(x) for x in _entity_keys(misleading)],
                           "grain": list(_grain_fields(misleading)),
                           "forbidden_customer_entity_absent": ["customer_id"] not in _entity_keys(misleading)},
        },
        "metadata_ablation": {
            "with_metadata": {"entities": [list(x) for x in _entity_keys(with_metadata)],
                              "grain": list(_grain_fields(with_metadata)),
                              "entity_confidence": [item["confidence"] for item in with_metadata.get("entities", [])],
                              "metadata_used": with_metadata.get("metadata_evidence", {}).get("provided")},
            "without_metadata": {"entities": [list(x) for x in _entity_keys(without_metadata)],
                                 "grain": list(_grain_fields(without_metadata)),
                                 "entity_confidence": [item["confidence"] for item in without_metadata.get("entities", [])],
                                 "metadata_used": without_metadata.get("metadata_evidence", {}).get("provided")},
            "authoritative_metadata_changes_confidence_or_coverage": (
                _entity_keys(with_metadata) != _entity_keys(without_metadata)
                or [item["confidence"] for item in with_metadata.get("entities", [])]
                != [item["confidence"] for item in without_metadata.get("entities", [])]
                or _grain_fields(with_metadata) != _grain_fields(without_metadata)),
        },
    }


def _performance_results(repetitions: int) -> dict[str, Any]:
    from .performance import benchmark_current

    current = benchmark_current(repetitions=repetitions)
    baseline_path = ROOT / "evals" / "analytical" / "baselines" / "anvil-2.14.0-deterministic-v1.json"
    baseline = _json(baseline_path)
    old = baseline.get("performance", {}).get("depths", {})
    depths = {}
    for depth, item in current.get("depths", {}).items():
        before = old.get(depth, {}).get("total", {}).get("median_ms")
        after = item.get("total", {}).get("median_ms")
        depths[depth] = {"operations": item.get("operations"), "candidate_median_ms": after,
                         "candidate_profile_median_ms": item.get("profile", {}).get("median_ms"),
                         "baseline_2_14_median_ms": before,
                         "change_percent": round((after / before - 1) * 100, 2) if before and after else None,
                         "candidate_repetitions": repetitions}
    return {"workload": current.get("fixture"), "depths": depths,
            "profile_stage_attribution": current.get("profile_stage_attribution"),
            "fast_path_investigation": current.get("fast_path_investigation"),
            "baseline_id": baseline.get("baseline_id"),
            "baseline_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            "baseline_immutable": bool(baseline.get("immutable")),
            "model_calls": current.get("model_calls", 0), "tool_calls": current.get("tool_calls", 0),
            "tokens": current.get("tokens", {"input": 0, "output": 0})}


def run_certification(*, repetitions: int = 3) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    cases, truths = load_cases()
    contexts = {case["id"]: _profile(case) for case in cases}
    case_results = [_case_metrics(case, truths[case["id"]], contexts[case["id"]]) for case in cases]
    from .evaluator import evaluate_fixture

    known = {}
    for fixture_id in ("operations-v1", "services-v1"):
        result, _ = evaluate_fixture(fixture_id)
        known[fixture_id] = {"L1": result["levels"]["L1"], "L2": result["levels"]["L2"]}
    semantic_metrics = _aggregate(case_results)
    metamorphic = _metamorphic(cases, contexts)
    mutations = _mutation_checks(case_results, contexts, cases, truths)
    sensitivity = _sensitivity()
    duplicate_cases = [item for item in case_results if item["duplicate_risk_expected"]]
    metadata_cases = [item for item in case_results if item["metadata_expected"]]
    semantic_metrics["duplicate_risk_detection"] = _ratio(sum(item["duplicate_risk_actual"] for item in duplicate_cases), len(duplicate_cases))
    semantic_metrics["metadata_usage"] = _ratio(sum(item["metadata_used"] for item in metadata_cases), len(metadata_cases))
    event_failures = [item["id"] for item in case_results if item["event_keys"]["expected"] != item["event_keys"]["actual"]]
    role_failures = {item["id"]: [check for check in item["roles"]["checks"] if not check["correct"]]
                     for item in case_results if item["roles"]["accuracy"] is not None
                     and item["roles"]["accuracy"] != 1.0}
    grain_failures = {item["id"]: item["grain"] for item in case_results
                      if item["grain"]["classification"] not in {"EXACT", "SEMANTICALLY_EQUIVALENT"}
                      and not (item["grain"]["expected_unknown"] and not item["grain"]["actual"])}
    entity_failures = {item["id"]: item["entities"] for item in case_results
                       if item["entities"]["false_positive"] or item["entities"]["false_negative"]}
    composite_entity_failures = [item["id"] for item in case_results if not item["composite_entity_keys"]["correct"]]
    fd_failures = {item["id"]: [check for check in item["functional_dependency_checks"] if not check["correct"]]
                   for item in case_results if any(not check["correct"] for check in item["functional_dependency_checks"])}
    baseline_l1 = all(item["L1"]["correct"] == item["L1"]["total"] for item in known.values())
    known_l2 = all(item["L2"]["correct"] == item["L2"]["total"] for item in known.values())
    high_precision_gate = semantic_metrics["high_confidence_entity_counts"]["false_positive"] == 0
    entity_metric_gate = bool(semantic_metrics["entity_precision"] and semantic_metrics["entity_recall"])
    composite_gate = semantic_metrics["composite_grain_accuracy"] == 1.0
    metamorphic_gate = metamorphic["passed"] == metamorphic["total"]
    abstention_gate = semantic_metrics["abstention_accuracy"] == 1.0
    mutation_gate = mutations["passed"] == mutations["total"]
    role_gate = semantic_metrics["role_classification_accuracy"] == 1.0
    event_gate = not event_failures
    temporal_gate = semantic_metrics["technical_time_role_accuracy"] == 1.0
    composite_entity_gate = semantic_metrics["composite_entity_key_accuracy"] == 1.0
    fd_gate = semantic_metrics["functional_dependency_accuracy"] == 1.0
    gates = {"L1_100_percent": baseline_l1, "known_L2_100_percent": known_l2,
             "zero_high_confidence_entity_false_positives": high_precision_gate,
             "entity_precision_and_recall_are_nonzero": entity_metric_gate,
             "composite_grain_cases_100_percent": composite_gate,
             "composite_entity_keys_100_percent": composite_entity_gate,
             "functional_dependency_cases_100_percent": fd_gate,
             "metamorphic_invariants_100_percent": metamorphic_gate,
             "ambiguous_case_abstention_100_percent": abstention_gate,
             "known_role_classification_100_percent": role_gate,
             "technical_time_roles_100_percent": temporal_gate,
             "event_entity_separation": event_gate,
             "evaluator_mutations_caught": mutation_gate}
    ready = ("READY_FOR_MODEL_EVALUATION" if all(gates.values()) and not grain_failures
             and not composite_entity_failures and not fd_failures
             else "READY_WITH_SEMANTIC_LIMITATIONS" if baseline_l1 and known_l2 and high_precision_gate
             else "NOT_READY_FOR_MODEL_EVALUATION")
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                  capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True,
                                    capture_output=True, text=True, timeout=5).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        revision = None
        dirty = None
    ablations = _ablation_results(cases)
    performance = _performance_results(repetitions)
    baseline_path = ROOT / "evals" / "analytical" / "baselines" / "anvil-2.14.0-deterministic-v1.json"
    source_paths = [FIXTURE_PATH, TRUTH_PATH, baseline_path,
                    ROOT / "scripts/analysis/semantic.py", ROOT / "scripts/analysis/profiling.py",
                    ROOT / "scripts/analysis/investigation.py", ROOT / "scripts/analysis/primitives.py",
                    ROOT / "evals/analytical/semantic_certification.py", ROOT / "evals/analytical/evaluator.py",
                    ROOT / "evals/analytical/test_harness.py"]
    return {
        "schema_version": 1, "protocol": PROTOCOL, "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "git_revision": revision,
        "working_tree_dirty": dirty,
        "source_sha256": {str(path.relative_to(ROOT)): _sha256(path) for path in source_paths},
        "fixture_sha256": hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
        "ground_truth_sha256": hashlib.sha256(TRUTH_PATH.read_bytes()).hexdigest(),
        "baseline_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        "historical_baseline_2_14": {"path": "evals/analytical/baselines/anvil-2.14.0-deterministic-v1.json",
                                      "modified": False, "candidate_results_separate": True},
        "known_baseline": known,
        "metrics": semantic_metrics,
        "metamorphic": metamorphic,
        "sensitivity": sensitivity,
        "ablations": ablations,
        "mutation_tests": mutations,
        "performance": performance,
        "failures": {"entity": entity_failures, "grain": grain_failures,
                     "roles": role_failures, "event_keys": event_failures,
                     "composite_entity_keys": composite_entity_failures,
                     "functional_dependencies": fd_failures},
        "release_gates": gates,
        "l3_l5_readiness": ready,
        "readiness_reason": ("L1/L2 and all deterministic semantic gates passed; model-backed L3-L5 can now be evaluated separately."
                             if ready == "READY_FOR_MODEL_EVALUATION" else
                             "Deterministic results leave semantic limitations; inspect the failures and retain the current model-evaluation boundary."),
        "cases": case_results,
    }


def markdown_summary(report: dict[str, Any], run_id: str) -> str:
    metrics = report["metrics"]
    known_rows = []
    for fixture, value in report["known_baseline"].items():
        known_rows.append(f"| {fixture} | {value['L1']['correct']}/{value['L1']['total']} | {value['L2']['correct']}/{value['L2']['total']} |")
    lines = ["# Anvil Semantic Foundation Certification", "", f"Run: `{run_id}`",
             f"Protocol: `{report['protocol']}`", f"Candidate: `{report['candidate_version']}`",
             f"Git revision: `{report.get('git_revision') or 'unknown'}`; working tree dirty: `{report.get('working_tree_dirty')}`.", "",
             "## Preserved known fixtures", "", "| Fixture | L1 | L2 |", "|---|---:|---:|", *known_rows, "",
             "## Semantic metrics", "", "| Metric | Result |", "|---|---:|",
             f"| Entity precision | {metrics['entity_precision']:.1%} |" if metrics["entity_precision"] is not None else "| Entity precision | n/a |",
             f"| Entity recall | {metrics['entity_recall']:.1%} |" if metrics["entity_recall"] is not None else "| Entity recall | n/a |",
             f"| High-confidence entity precision | {metrics['high_confidence_entity_precision']:.1%} |" if metrics["high_confidence_entity_precision"] is not None else "| High-confidence entity precision | n/a |",
             f"| False entity candidate rate | {metrics['false_entity_candidate_rate']:.1%} |" if metrics["false_entity_candidate_rate"] is not None else "| False entity candidate rate | n/a |",
             f"| Grain accuracy | {metrics['grain_accuracy']:.1%} |",
             f"| Composite grain accuracy | {metrics['composite_grain_accuracy']:.1%} |",
             f"| Composite entity-key accuracy | {metrics['composite_entity_key_accuracy']:.1%} |",
             f"| Functional dependency accuracy | {metrics['functional_dependency_accuracy']:.1%} |",
             f"| Role classification | {metrics['role_classification_accuracy']:.1%} |",
             f"| Abstention accuracy | {metrics['abstention_accuracy']:.1%} |",
             f"| Event-key accuracy | {metrics['event_key_accuracy']:.1%} |",
             f"| Technical time-role accuracy | {metrics['technical_time_role_accuracy']:.1%} |",
             f"| Metamorphic stability | {report['metamorphic']['stability']:.1%} ({report['metamorphic']['passed']}/{report['metamorphic']['total']}) |",
             f"| Confidence Brier score | {metrics['confidence_calibration']['brier_score']:.3f} |",
             "", "## FAST/STANDARD/DEEP performance", "",
             f"Frozen baseline: `{report['performance']['baseline_id']}`; SHA-256 `{report['performance']['baseline_sha256']}`.", "",
             "| Depth | Operations | 2.14 median | Candidate median | Change |",
             "|---|---:|---:|---:|---:|"]
    for depth, item in report["performance"]["depths"].items():
        lines.append(f"| {depth} | {item['operations']} | {item['baseline_2_14_median_ms']} ms | {item['candidate_median_ms']} ms | {item['change_percent']:+.2f}% |")
    lines += ["", "## Ablations", "",
              f"Neutral-name inference: `{report['ablations']['lexical_ablation']['neutral']['entities']}`; "
              f"grain `{report['ablations']['lexical_ablation']['neutral']['grain']}`; confidence "
              f"`{report['ablations']['lexical_ablation']['neutral']['confidence']}`.",
              f"Metadata changes coverage/confidence: `{report['ablations']['metadata_ablation']['authoritative_metadata_changes_confidence_or_coverage']}`.",
              "", "## Confidence calibration", "",
              "| Confidence | Candidates/decisions | Observed accuracy | Mapped probability |",
              "|---|---:|---:|---:|"]
    for level, item in metrics["confidence_calibration"]["by_level"].items():
        accuracy = "n/a" if item["empirical_accuracy"] is None else f"{item['empirical_accuracy']:.1%}"
        probability = "n/a" if item["mean_predicted_probability"] is None else f"{item['mean_predicted_probability']:.0%}"
        lines.append(f"| {level} | {item['count']} | {accuracy} | {probability} |")
    lines += ["", "## Sensitivity", "", "| Dimension | Inputs evaluated |", "|---|---|"]
    sensitivities: dict[str, list[Any]] = defaultdict(list)
    for item in report["sensitivity"]["observations"]:
        sensitivities[item["dimension"]].append(item["value"])
    for dimension, values in sensitivities.items():
        lines.append(f"| {dimension.replace('_', ' ')} | {', '.join(map(str, values))} |")
    lines += ["", "## Gates", ""]
    lines.extend(f"- {'PASS' if passed else 'FAIL'} `{name}`" for name, passed in report["release_gates"].items())
    lines += ["", f"L3–L5 readiness: **{report['l3_l5_readiness']}**", "", report["readiness_reason"], "",
              "The 2.14 deterministic baseline remains an immutable historical reference. This report is a separate candidate artifact.", ""]
    for title, checks in (("Metamorphic checks", report["metamorphic"]["checks"]),
                          ("Evaluator mutations", report["mutation_tests"]["checks"])):
        lines += [f"## {title}", ""]
        lines.extend(f"- {'PASS' if item.get('passed', item.get('caught')) else 'FAIL'} `{item.get('id', item.get('mutation'))}`" for item in checks)
        lines.append("")
    if any(report["failures"].values()):
        lines += ["## Remaining semantic failures", "", "```json", json.dumps(report["failures"], ensure_ascii=False, indent=2, sort_keys=True), "```", ""]
    return "\n".join(lines)


def write_artifacts(report: dict[str, Any], output_dir: Path) -> Path:
    """Write each report into a new private run directory; never overwrite."""
    root = output_dir.expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = root / run_id
    directory.mkdir(mode=0o700)
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    for name, data in (("semantic-certification.json", payload),
                       ("summary.md", markdown_summary(report, run_id).encode("utf-8"))):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(directory / name, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    return directory
