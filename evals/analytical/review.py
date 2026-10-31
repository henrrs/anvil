"""Structured human review overlays for synthetic or local private cases."""

from __future__ import annotations

from typing import Any


class ReviewContractError(ValueError):
    pass


def _candidate_output(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = candidate.get("evaluation", {})
    output = metadata.get("candidate_output", {}) if isinstance(metadata, dict) else {}
    return output if isinstance(output, dict) else {}


def _list(value: Any, label: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ReviewContractError(f"{label} must be a list of at most {maximum} items")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ReviewContractError(f"{label} must be boolean")
    return value


def validate_review(review: Any, candidate: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(review, dict) or review.get("schema_version") != 1:
        raise ReviewContractError("review must be an object with schema_version 1")
    allowed = {"schema_version", "fixture_id", "run_id", "reviewer_id", "finding_annotations",
               "missed_finding_ids", "claim_annotations", "semantic_error_annotations",
               "communication_parity", "communication_issues", "investigation_sufficient"}
    if set(review) - allowed:
        raise ReviewContractError("review contains unsupported fields")
    if review.get("fixture_id") != ground_truth.get("fixture", {}).get("id"):
        raise ReviewContractError("review fixture_id does not match hidden ground truth")
    if review.get("run_id") != candidate.get("evaluation", {}).get("run_id"):
        raise ReviewContractError("review run_id does not match the selected model result")
    reviewer_id = review.get("reviewer_id", "anonymous")
    if not isinstance(reviewer_id, str) or len(reviewer_id) > 120:
        raise ReviewContractError("reviewer_id must be text of at most 120 characters")
    known_findings = {item["id"] for item in ground_truth.get("material_findings", [])}
    finding_annotations = _list(review.get("finding_annotations", []), "finding_annotations", 100)
    seen_finding_indexes: set[int] = set()
    for index, annotation in enumerate(finding_annotations):
        if not isinstance(annotation, dict) or set(annotation) - {"finding_index", "matched_ground_truth_ids", "supported", "materiality_correct", "notes"}:
            raise ReviewContractError(f"finding_annotations[{index}] has an invalid shape")
        candidate_index = annotation.get("finding_index")
        if not isinstance(candidate_index, int) or not 0 <= candidate_index < len(_candidate_output(candidate).get("findings", [])):
            raise ReviewContractError(f"finding_annotations[{index}] references an absent candidate finding")
        if candidate_index in seen_finding_indexes:
            raise ReviewContractError("candidate finding indexes must be annotated once")
        seen_finding_indexes.add(candidate_index)
        matches = _list(annotation.get("matched_ground_truth_ids", []), f"finding_annotations[{index}].matched_ground_truth_ids", 20)
        if any(item not in known_findings for item in matches):
            raise ReviewContractError(f"finding_annotations[{index}] references unknown ground-truth finding")
        _bool(annotation.get("supported"), f"finding_annotations[{index}].supported")
        _bool(annotation.get("materiality_correct"), f"finding_annotations[{index}].materiality_correct")
        notes = annotation.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ReviewContractError(f"finding_annotations[{index}].notes is too long")

    missed = _list(review.get("missed_finding_ids", []), "missed_finding_ids", 100)
    if any(item not in known_findings for item in missed):
        raise ReviewContractError("missed_finding_ids contains an unknown ground-truth finding")
    claim_annotations = _list(review.get("claim_annotations", []), "claim_annotations", 150)
    seen_claim_indexes: set[int] = set()
    for index, annotation in enumerate(claim_annotations):
        if not isinstance(annotation, dict) or set(annotation) - {"claim_index", "supported", "calibrated", "notes"}:
            raise ReviewContractError(f"claim_annotations[{index}] has an invalid shape")
        candidate_index = annotation.get("claim_index")
        if not isinstance(candidate_index, int) or not 0 <= candidate_index < len(_candidate_output(candidate).get("claims", [])):
            raise ReviewContractError(f"claim_annotations[{index}] references an absent candidate claim")
        if candidate_index in seen_claim_indexes:
            raise ReviewContractError("candidate claim indexes must be annotated once")
        seen_claim_indexes.add(candidate_index)
        _bool(annotation.get("supported"), f"claim_annotations[{index}].supported")
        _bool(annotation.get("calibrated"), f"claim_annotations[{index}].calibrated")
        if not isinstance(annotation.get("notes", ""), str) or len(annotation.get("notes", "")) > 2000:
            raise ReviewContractError(f"claim_annotations[{index}].notes is too long")

    semantic_annotations = _list(review.get("semantic_error_annotations", []), "semantic_error_annotations", 100)
    for index, annotation in enumerate(semantic_annotations):
        if not isinstance(annotation, dict) or set(annotation) - {"class", "summary", "evidence"}:
            raise ReviewContractError(f"semantic_error_annotations[{index}] has an invalid shape")
        if annotation.get("class") not in {"GRAIN", "ENTITY_RESOLUTION", "SEMANTIC", "POPULATION", "COHORT", "COMPOSITION", "DISTRIBUTION"}:
            raise ReviewContractError(f"semantic_error_annotations[{index}].class is unsupported")
        if not isinstance(annotation.get("summary"), str) or not annotation["summary"].strip():
            raise ReviewContractError(f"semantic_error_annotations[{index}].summary is required")

    parity = _list(review.get("communication_parity", []), "communication_parity", 300)
    for index, item in enumerate(parity):
        if not isinstance(item, dict) or set(item) - {"surface", "fact_id", "consistent", "notes"}:
            raise ReviewContractError(f"communication_parity[{index}] has an invalid shape")
        if item.get("surface") not in {"direct", "report", "presentation"}:
            raise ReviewContractError(f"communication_parity[{index}].surface is unsupported")
        _bool(item.get("consistent"), f"communication_parity[{index}].consistent")
    issues = _list(review.get("communication_issues", []), "communication_issues", 100)
    if any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in issues):
        raise ReviewContractError("communication_issues entries must be short non-empty text")
    sufficient = review.get("investigation_sufficient")
    if sufficient is not None:
        _bool(sufficient, "investigation_sufficient")
    normalized = dict(review)
    normalized["reviewer_id"] = reviewer_id
    return normalized


def human_metrics(review: dict[str, Any], candidate: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    output = _candidate_output(candidate)
    findings = output.get("findings", [])
    annotations = review.get("finding_annotations", [])
    material_indexes = {index for index, finding in enumerate(findings)
                        if finding.get("materiality") in {"HIGH", "MEDIUM"}}
    complete_findings = material_indexes <= {item["finding_index"] for item in annotations}
    matched_ids = {truth_id for item in annotations if item.get("supported")
                   for truth_id in item.get("matched_ground_truth_ids", [])}
    total_truth = len(ground_truth.get("material_findings", []))
    known_truth_ids = {item["id"] for item in ground_truth.get("material_findings", [])}
    recall_coverage_complete = (matched_ids | set(review.get("missed_finding_ids", []))) >= known_truth_ids
    true_positive_candidates = sum(item["finding_index"] in material_indexes and item["supported"]
                                   and bool(item["matched_ground_truth_ids"]) for item in annotations)
    precision = true_positive_candidates / len(material_indexes) if complete_findings and material_indexes else None
    recall = len(matched_ids) / total_truth if total_truth and recall_coverage_complete else None

    claims = output.get("claims", [])
    material_claims = {index for index, claim in enumerate(claims) if claim.get("material", True)}
    claim_annotations = review.get("claim_annotations", [])
    complete_claims = material_claims <= {item["claim_index"] for item in claim_annotations}
    judged_material = [item for item in claim_annotations if item["claim_index"] in material_claims]
    unsupported = sum(not item["supported"] for item in judged_material)
    unsupported_rate = unsupported / len(judged_material) if complete_claims and judged_material else (0.0 if complete_claims else None)
    calibration = (sum(item["calibrated"] for item in judged_material) / len(judged_material)
                   if complete_claims and judged_material else (1.0 if complete_claims else None))
    materiality_annotations = [item for item in annotations if item["finding_index"] in material_indexes]
    materiality = (sum(item["materiality_correct"] for item in materiality_annotations) / len(materiality_annotations)
                   if complete_findings and materiality_annotations else (1.0 if complete_findings else None))
    parity = review.get("communication_parity", [])
    communication = (sum(item["consistent"] for item in parity) / len(parity) if parity else None)
    return {"reviewer_id": review.get("reviewer_id", "anonymous"),
            "material_insight_recall": recall, "material_insight_precision": precision,
            "unsupported_claim_rate": unsupported_rate, "claim_calibration": calibration,
            "materiality": materiality,
            "communication_fidelity": communication,
            "investigation_sufficient": review.get("investigation_sufficient"),
            "semantic_error_annotations": review.get("semantic_error_annotations", []),
            "communication_issues": review.get("communication_issues", []),
            "status": "COMPLETE" if recall is not None and precision is not None else "PARTIAL"}
