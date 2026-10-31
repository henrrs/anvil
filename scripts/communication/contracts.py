"""Small versioned contracts shared by the reasoning and rendering layers."""

from __future__ import annotations

import re
import math
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import CommunicationError


EPISTEMIC_TYPES = {
    "FACT", "MEASUREMENT", "OBSERVATION", "OBSERVED", "DERIVED_VALUE", "CALCULATED", "INFERENCE", "INFERRED",
    "ESTIMATE", "ASSUMPTION", "SCENARIO", "PROJECTION", "PROPOSAL", "UNKNOWN", "DERIVED", "INTERPRETED", "HYPOTHESIS",
}
CONFIDENCE_LEVELS = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
AUDIENCES = {"executive", "financial", "technical_leadership", "engineering", "technical", "mixed"}
ARTIFACT_TYPES = {"report", "presentation", "summary"}
CONSTRAINT_STRENGTHS = {"hard", "soft"}
CONSTRAINT_ORIGINS = {"explicit", "policy", "inferred", "memory", "default"}
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
VISUAL_RELATIONSHIPS = {"magnitude", "trend", "comparison", "process", "causality", "architecture",
                        "hierarchy", "composition", "decision", "distribution", "textual", "unknown"}
VISUAL_FORMS = {"hero_metric", "bar_chart", "line_chart", "before_after", "waterfall", "flow", "containment",
                "dependency_graph", "tree", "stacked_bar", "treemap", "decision_matrix", "decision_tree",
                "histogram", "box_plot", "table", "cards", "text", "diagram", "custom", "unknown"}
VISUAL_PROMINENCE = {"dominant", "supporting", "context"}
COLOR_ROLES = {"neutral", "primary_accent", "secondary_accent", "risk", "positive", "negative",
               "observed", "scenario", "external", "proposed"}
MOTION_PURPOSES = {"sequence", "causality", "transformation", "state_change", "progressive_reveal",
                   "data_flow", "feedback_loop", "before_after"}


def validate_visual_intent(item: Any, field: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CommunicationError("CONTRACT_INVALID", f"{field} must be an object.")
    allowed = {"relationship", "form", "primary_message", "primary_evidence_ids", "secondary_evidence_ids",
               "prominence", "color_roles", "motion"}
    if set(item) - allowed:
        raise CommunicationError("CONTRACT_INVALID", f"{field} contains unsupported fields.")
    relationship, form = item.get("relationship"), item.get("form")
    if (not isinstance(relationship, str) or relationship not in VISUAL_RELATIONSHIPS
            or not isinstance(form, str) or form not in VISUAL_FORMS):
        raise CommunicationError("CONTRACT_INVALID", f"{field} needs a supported semantic relationship and visual form.")
    prominence = item.get("prominence", "supporting")
    if not isinstance(prominence, str) or prominence not in VISUAL_PROMINENCE:
        raise CommunicationError("CONTRACT_INVALID", f"{field}.prominence must be dominant, supporting, or context.")
    roles = item.get("color_roles", ["neutral"])
    if (not isinstance(roles, list) or not roles or len(roles) > len(COLOR_ROLES)
            or any(not isinstance(role, str) or role not in COLOR_ROLES for role in roles)):
        raise CommunicationError("CONTRACT_INVALID", f"{field}.color_roles must use semantic palette roles, not raw colors.")
    if len(roles) != len(set(roles)):
        raise CommunicationError("CONTRACT_INVALID", f"{field}.color_roles cannot contain duplicates.")
    motion_raw = item.get("motion", {"mode": "static"})
    if not isinstance(motion_raw, dict) or set(motion_raw) - {"mode", "purpose", "states"}:
        raise CommunicationError("CONTRACT_INVALID", f"{field}.motion must be a bounded static/animated storyboard.")
    mode = motion_raw.get("mode", "static")
    if not isinstance(mode, str) or mode not in {"static", "animated"}:
        raise CommunicationError("CONTRACT_INVALID", f"{field}.motion.mode must be static or animated.")
    states_raw = motion_raw.get("states", [])
    if not isinstance(states_raw, list) or len(states_raw) > 20:
        raise CommunicationError("CONTRACT_INVALID", f"{field}.motion.states must be a bounded list.")
    states = []
    state_ids: set[str] = set()
    for index, state in enumerate(states_raw):
        if not isinstance(state, dict) or set(state) - {"id", "label", "change", "new_information", "evidence_ids"}:
            raise CommunicationError("CONTRACT_INVALID", f"{field}.motion.states[{index}] has an unsupported shape.")
        state_id = state.get("id")
        if not isinstance(state_id, str) or not IDENTIFIER.fullmatch(state_id) or state_id in state_ids:
            raise CommunicationError("CONTRACT_INVALID", f"{field}.motion state IDs must be valid and unique.")
        state_ids.add(state_id)
        states.append({"id": state_id,
                       "label": _string(state.get("label"), f"{field}.motion.states[{index}].label", maximum=160),
                       "change": _string(state.get("change"), f"{field}.motion.states[{index}].change", maximum=500),
                       "new_information": _string(state.get("new_information"), f"{field}.motion.states[{index}].new_information", maximum=500),
                       "evidence_ids": _ids(state.get("evidence_ids", []), f"{field}.motion.states[{index}].evidence_ids")})
    purpose = motion_raw.get("purpose")
    if mode == "animated":
        unique_information = {state["new_information"].casefold() for state in states}
        if (not isinstance(purpose, str) or purpose not in MOTION_PURPOSES or len(states) < 2
                or len(unique_information) < 2):
            raise CommunicationError("MOTION_NOT_SEMANTIC", f"{field} animation needs a meaningful information purpose and at least two changing states.",
                                     remediation="Use a static representation unless time itself explains sequence, causality, transformation, or state.")
    elif purpose is not None or states:
        raise CommunicationError("CONTRACT_INVALID", f"{field} static motion cannot contain an animation purpose or storyboard states.")
    return {"relationship": relationship, "form": form,
            "primary_message": _string(item.get("primary_message"), f"{field}.primary_message", maximum=500),
            "primary_evidence_ids": _ids(item.get("primary_evidence_ids", []), f"{field}.primary_evidence_ids"),
            "secondary_evidence_ids": _ids(item.get("secondary_evidence_ids", []), f"{field}.secondary_evidence_ids"),
            "prominence": prominence, "color_roles": roles,
            "motion": {"mode": mode, "purpose": purpose, "states": states}}


def decimal_value(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID", f"{field} must be a finite decimal value.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID", f"{field} must be a finite decimal value.") from None
    if not parsed.is_finite():
        raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID", f"{field} must be a finite decimal value.")
    if len(parsed.as_tuple().digits) > 1000 or abs(parsed.adjusted()) > 1000:
        raise CommunicationError("QUANTITATIVE_ANALYSIS_INVALID", f"{field} exceeds the supported numeric magnitude or precision.")
    return parsed


def _string(value: Any, field: str, *, maximum: int = 4000, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum:
        raise CommunicationError("CONTRACT_INVALID", f"{field} must be text with at most {maximum} characters.")
    return value.strip()


def _ids(value: Any, field: str, *, maximum: int = 200) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise CommunicationError("CONTRACT_INVALID", f"{field} must be a list with at most {maximum} IDs.")
    result = []
    for item in value:
        if not isinstance(item, str) or not IDENTIFIER.fullmatch(item):
            raise CommunicationError("CONTRACT_INVALID", f"{field} contains an invalid ID.")
        result.append(item)
    if len(result) != len(set(result)):
        raise CommunicationError("CONTRACT_INVALID", f"{field} contains duplicate IDs.")
    return result


def _insight_evidence_ids(insight: dict[str, Any]) -> set[str]:
    refs = {ref for field in ("baseline", "current")
            for ref in (insight.get(field) or {}).get("evidence_ids", [])}
    normalization = insight.get("normalization") or {}
    refs.update(normalization.get("baseline_denominator_evidence_ids", []))
    refs.update(normalization.get("current_denominator_evidence_ids", []))
    return refs


def _visual_intent_evidence_ids(intent: dict[str, Any]) -> set[str]:
    refs = set(intent["primary_evidence_ids"]) | set(intent["secondary_evidence_ids"])
    refs.update(ref for state in intent["motion"]["states"] for ref in state["evidence_ids"])
    return refs


def validate_evidence(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CommunicationError("CONTRACT_INVALID", "Each evidence record must be an object.")
    identifier = item.get("id")
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise CommunicationError("CONTRACT_INVALID", "Evidence ID is missing or invalid.")
    epistemic = item.get("epistemic", "OBSERVATION")
    confidence = item.get("confidence", "UNKNOWN")
    if not isinstance(epistemic, str) or epistemic not in EPISTEMIC_TYPES:
        raise CommunicationError("CONTRACT_INVALID", f"Evidence {identifier} has an unsupported epistemic type.")
    if not isinstance(confidence, str) or confidence not in CONFIDENCE_LEVELS:
        raise CommunicationError("CONTRACT_INVALID", f"Evidence {identifier} has an unsupported confidence level.")
    source = item.get("source")
    if not isinstance(source, dict):
        raise CommunicationError("CONTRACT_INVALID", f"Evidence {identifier} must preserve its source provenance.")
    source_type = _string(source.get("type"), f"evidence.{identifier}.source.type", maximum=80)
    locator = _string(source.get("locator"), f"evidence.{identifier}.source.locator", maximum=2000)
    digest = source.get("sha256")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)):
        raise CommunicationError("CONTRACT_INVALID", f"Evidence {identifier} has an invalid source hash.")
    claim = _string(item.get("claim"), f"evidence.{identifier}.claim")
    normalized: dict[str, Any] = {
        "id": identifier, "claim": claim, "epistemic": epistemic,
        "confidence": confidence,
        "source": {"type": source_type, "locator": locator, "sha256": digest},
    }
    if "value" in item and item["value"] is not None:
        normalized["value"] = str(decimal_value(item["value"], field=f"evidence.{identifier}.value"))
    elif "value" in item:
        normalized["value"] = None
    unit = item.get("unit")
    if unit is not None:
        normalized["unit"] = _string(unit, f"evidence.{identifier}.unit", maximum=80)
    if item.get("period") is not None:
        normalized["period"] = _string(item["period"], f"evidence.{identifier}.period", maximum=240)
    if item.get("assumptions") is not None:
        if not isinstance(item["assumptions"], list) or len(item["assumptions"]) > 30:
            raise CommunicationError("CONTRACT_INVALID", f"Evidence {identifier} assumptions must be a bounded list.")
        normalized["assumptions"] = [_string(value, "evidence assumption", maximum=500) for value in item["assumptions"]]
    for field in ("method", "calculation"):
        if item.get(field) is not None:
            normalized[field] = _string(item[field], f"evidence.{identifier}.{field}", maximum=2000)
    if "data" in item:
        try:
            encoded_data = json.dumps(item["data"], ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            raise CommunicationError("CONTRACT_INVALID", f"Evidence {identifier} data must be JSON-compatible.") from None
        if len(encoded_data.encode("utf-8")) > 100_000:
            raise CommunicationError("CONTRACT_INVALID", f"Evidence {identifier} data exceeds the 100 KiB limit.")
        normalized["data"] = item["data"]
    return normalized


def validate_finding(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CommunicationError("CONTRACT_INVALID", "Each finding must be an object.")
    identifier = item.get("id")
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise CommunicationError("CONTRACT_INVALID", "Finding ID is missing or invalid.")
    allowed = {"id", "claim", "epistemic", "confidence", "evidence_ids", "counter_evidence_ids",
               "alternative_explanations", "materiality", "implications", "limitations", "relevance",
               "impact", "quantitative_insight_ids"}
    if set(item) - allowed:
        raise CommunicationError("CONTRACT_INVALID", f"Finding {identifier} contains unsupported fields.")
    epistemic = item.get("epistemic", "INFERENCE")
    confidence = item.get("confidence", "UNKNOWN")
    if not isinstance(epistemic, str) or epistemic not in EPISTEMIC_TYPES or not isinstance(confidence, str) or confidence not in CONFIDENCE_LEVELS:
        raise CommunicationError("CONTRACT_INVALID", f"Finding {identifier} has invalid epistemic/confidence values.")
    evidence_ids = _ids(item.get("evidence_ids", []), f"finding.{identifier}.evidence_ids")
    if epistemic not in {"PROPOSAL", "UNKNOWN"} and not evidence_ids:
        raise CommunicationError("EVIDENCE_INSUFFICIENT", f"Finding {identifier} has no supporting evidence.")
    result = {
        "id": identifier,
        "claim": _string(item.get("claim"), f"finding.{identifier}.claim"),
        "epistemic": epistemic, "confidence": confidence, "evidence_ids": evidence_ids,
        "counter_evidence_ids": _ids(item.get("counter_evidence_ids", []), f"finding.{identifier}.counter_evidence_ids"),
        "materiality": item.get("materiality", "unknown"),
    }
    if not isinstance(result["materiality"], str) or result["materiality"] not in {"high", "medium", "low", "unknown"}:
        raise CommunicationError("CONTRACT_INVALID", f"Finding {identifier} materiality must be high, medium, low, or unknown.")
    alternatives = item.get("alternative_explanations", [])
    if not isinstance(alternatives, list) or len(alternatives) > 20:
        raise CommunicationError("CONTRACT_INVALID", f"Finding {identifier} alternative_explanations must be a bounded list.")
    result["alternative_explanations"] = [_string(value, f"finding.{identifier}.alternative_explanations", maximum=1000) for value in alternatives]
    for field in ("implications", "limitations"):
        values = item.get(field, [])
        if not isinstance(values, list) or len(values) > 30:
            raise CommunicationError("CONTRACT_INVALID", f"Finding {identifier} {field} must be a bounded list.")
        result[field] = [_string(value, f"finding.{identifier}.{field}", maximum=1000) for value in values]
    relevance = item.get("relevance", {})
    if (not isinstance(relevance, dict)
            or any(key not in AUDIENCES or not isinstance(value, str) or value not in {"high", "medium", "low"}
                   for key, value in relevance.items())):
        raise CommunicationError("CONTRACT_INVALID", f"Finding {identifier} relevance must use audience-specific low/medium/high values.")
    result["relevance"] = relevance
    impact = item.get("impact")
    if impact is not None:
        result["impact"] = str(decimal_value(impact, field=f"finding.{identifier}.impact"))
    result["quantitative_insight_ids"] = _ids(item.get("quantitative_insight_ids", []), f"finding.{identifier}.quantitative_insight_ids")
    return result


def validate_constraint(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CommunicationError("CONTRACT_INVALID", "Each artifact constraint must be an object.")
    kind = item.get("kind")
    strength = item.get("strength", "soft")
    origin = item.get("origin", "default")
    if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", kind):
        raise CommunicationError("CONTRACT_INVALID", "Constraint kind is missing or invalid.")
    if not isinstance(strength, str) or strength not in CONSTRAINT_STRENGTHS or not isinstance(origin, str) or origin not in CONSTRAINT_ORIGINS:
        raise CommunicationError("CONTRACT_INVALID", f"Constraint {kind} has invalid strength or origin.")
    value = item.get("value")
    if isinstance(value, (dict, list)) or (value is not None and not isinstance(value, (str, int, float, bool))):
        raise CommunicationError("CONTRACT_INVALID", f"Constraint {kind} value must be a JSON scalar.")
    if isinstance(value, float) and not Decimal(str(value)).is_finite():
        raise CommunicationError("CONTRACT_INVALID", f"Constraint {kind} value must be finite.")
    if kind in {"exact_slides", "min_slides", "max_slides", "cover_count", "content_count", "architecture_count", "appendix_count"}:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise CommunicationError("CONTRACT_INVALID", f"Constraint {kind} must use a non-negative integer.")
    if kind in {"architecture_required", "architecture_if_relevant", "appendix_forbidden", "no_estimates", "measured_only"} and not isinstance(value, bool):
        raise CommunicationError("CONTRACT_INVALID", f"Constraint {kind} must use a boolean value.")
    return {"kind": kind, "value": value, "strength": strength, "origin": origin,
            "rationale": _string(item.get("rationale"), f"constraint.{kind}.rationale", maximum=1000, required=False)}


def validate_artifact(raw: Any) -> dict[str, Any]:
    """Validate a complete model-produced artifact plan before rendering."""
    if not isinstance(raw, dict):
        raise CommunicationError("CONTRACT_INVALID", "Artifact plan must be a JSON object.")
    if raw.get("schema_version") != 1:
        raise CommunicationError("CONTRACT_INVALID", "Artifact plan schema_version must be 1.")
    allowed_root = {"schema_version", "request", "title", "thesis", "evidence", "findings",
                    "quantitative_insights", "storyline", "selection_rationale", "exclusions",
                    "sections", "slides", "architecture_relevant", "editorial", "metadata"}
    if set(raw) - allowed_root:
        raise CommunicationError("CONTRACT_INVALID", "Artifact plan contains unsupported top-level fields: " +
                                 ", ".join(sorted(set(raw) - allowed_root)) + ".")
    request = raw.get("request")
    if not isinstance(request, dict):
        raise CommunicationError("CONTRACT_INVALID", "Artifact request is missing.")
    allowed_request = {"artifact", "audience", "purpose", "tone", "language", "title", "minutes",
                       "architecture_relevant", "constraints"}
    if set(request) - allowed_request:
        raise CommunicationError("CONTRACT_INVALID", "Artifact request contains unsupported fields: " +
                                 ", ".join(sorted(set(request) - allowed_request)) + ".")
    artifact_type = request.get("artifact")
    audience = request.get("audience")
    if not isinstance(artifact_type, str) or artifact_type not in ARTIFACT_TYPES or not isinstance(audience, str) or audience not in AUDIENCES:
        raise CommunicationError("CONTRACT_INVALID", "Artifact and audience must use supported values.")
    request_result = {
        "artifact": artifact_type,
        "audience": audience,
        "purpose": _string(request.get("purpose"), "request.purpose"),
        "tone": _string(request.get("tone", "neutral"), "request.tone", maximum=100),
        "language": _string(request.get("language", "en"), "request.language", maximum=40),
    }
    if "title" in request:
        request_result["title"] = _string(request["title"], "request.title", maximum=240)
    if "minutes" in request:
        minutes = decimal_value(request["minutes"], field="request.minutes")
        if minutes <= 0:
            raise CommunicationError("CONTRACT_INVALID", "request.minutes must be greater than zero.")
        numeric_minutes = float(minutes)
        if not math.isfinite(numeric_minutes):
            raise CommunicationError("CONTRACT_INVALID", "request.minutes exceeds the supported range.")
        request_result["minutes"] = int(minutes) if minutes == minutes.to_integral_value() else numeric_minutes
    if "architecture_relevant" in request:
        if not isinstance(request["architecture_relevant"], bool):
            raise CommunicationError("CONTRACT_INVALID", "request.architecture_relevant must be boolean.")
        request_result["architecture_relevant"] = request["architecture_relevant"]
    constraints = request.get("constraints", [])
    if not isinstance(constraints, list) or len(constraints) > 100:
        raise CommunicationError("CONTRACT_INVALID", "Request constraints must be a bounded list.")
    request_result["constraints"] = [validate_constraint(item) for item in constraints]

    evidence_raw = raw.get("evidence", [])
    findings_raw = raw.get("findings", [])
    if not isinstance(evidence_raw, list) or len(evidence_raw) > 2000:
        raise CommunicationError("CONTRACT_INVALID", "Artifact evidence must be a bounded list.")
    if not isinstance(findings_raw, list) or len(findings_raw) > 1000:
        raise CommunicationError("CONTRACT_INVALID", "Artifact findings must be a bounded list.")
    evidence = [validate_evidence(item) for item in evidence_raw]
    findings = [validate_finding(item) for item in findings_raw]
    evidence_ids = {item["id"] for item in evidence}
    if len(evidence_ids) != len(evidence):
        raise CommunicationError("CONTRACT_INVALID", "Evidence IDs must be unique.")
    finding_ids = {item["id"] for item in findings}
    if len(finding_ids) != len(findings):
        raise CommunicationError("CONTRACT_INVALID", "Finding IDs must be unique.")
    for finding in findings:
        missing = (set(finding["evidence_ids"]) | set(finding["counter_evidence_ids"])) - evidence_ids
        if missing:
            raise CommunicationError("CONTRACT_INVALID", f"Finding {finding['id']} references unknown evidence IDs: {', '.join(sorted(missing))}.")

    insights_raw = raw.get("quantitative_insights", [])
    if not isinstance(insights_raw, list) or len(insights_raw) > 500:
        raise CommunicationError("CONTRACT_INVALID", "Quantitative insights must be a bounded list.")
    insights = []
    insight_ids: set[str] = set()
    for item in insights_raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not IDENTIFIER.fullmatch(item["id"]):
            raise CommunicationError("CONTRACT_INVALID", "Each quantitative insight must have a valid ID.")
        if item["id"] in insight_ids:
            raise CommunicationError("CONTRACT_INVALID", "Quantitative insight IDs must be unique.")
        insight_ids.add(item["id"])
        base = item.get("baseline")
        current = item.get("current")
        if not isinstance(item.get("metric"), str) or not item["metric"].strip() or len(item["metric"]) > 240 or not isinstance(item.get("unit"), str) or not item["unit"].strip() or len(item["unit"]) > 80:
            raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} needs metric and unit labels.")
        if base is not None and not isinstance(base, dict) or current is not None and not isinstance(current, dict):
            raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} baseline/current must be objects or null.")
        for label, observation in (("baseline", base), ("current", current)):
            if observation is not None:
                if set(observation) - {"value", "unit", "period", "evidence_ids", "epistemic"}:
                    raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} {label} contains unsupported fields.")
                if observation.get("unit", item["unit"]) != item["unit"]:
                    raise CommunicationError("UNIT_MISMATCH", f"Quantitative insight {item['id']} uses inconsistent units.")
                if observation.get("value") is not None:
                    decimal_value(observation["value"], field=f"{item['id']}.{label}.value")
                observation_refs = _ids(observation.get("evidence_ids", []), f"{item['id']}.{label}.evidence_ids")
                observation_epistemic = observation.get("epistemic", "MEASUREMENT")
                if not isinstance(observation_epistemic, str):
                    raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} {label} has an invalid epistemic type.")
                if observation.get("value") is not None and observation_epistemic not in {"UNKNOWN", "PROPOSAL"} and not observation_refs:
                    raise CommunicationError("EVIDENCE_INSUFFICIENT", f"Quantitative observation {item['id']}.{label} needs a supporting evidence ID.")
        normalization = item.get("normalization")
        if normalization is not None:
            if not isinstance(normalization, dict):
                raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} normalization must be an object.")
            norm_fields = {"name", "unit", "numerator_unit", "denominator_unit", "baseline_denominator",
                           "current_denominator", "baseline_denominator_evidence_ids", "current_denominator_evidence_ids",
                           "baseline", "current", "absolute_change", "relative_change", "epistemic"}
            if set(normalization) - norm_fields:
                raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} normalization contains unsupported fields.")
            for label in ("baseline", "current"):
                refs = _ids(normalization.get(f"{label}_denominator_evidence_ids", []),
                            f"{item['id']}.normalization.{label}_denominator_evidence_ids")
                if normalization.get(f"{label}_denominator") is not None and not refs:
                    raise CommunicationError("EVIDENCE_INSUFFICIENT", f"Quantitative insight {item['id']} {label} denominator needs evidence.")
                missing_refs = set(refs) - evidence_ids
                if missing_refs:
                    raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} normalization references unknown evidence IDs: {', '.join(sorted(missing_refs))}.")
        if not isinstance(item.get("epistemic"), str) or item.get("epistemic") not in EPISTEMIC_TYPES:
            raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} has an invalid epistemic type.")
        for label, observation in (("baseline", base), ("current", current)):
            if observation is not None:
                missing = set(observation.get("evidence_ids", [])) - evidence_ids
                if missing:
                    raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} {label} references unknown evidence IDs: {', '.join(sorted(missing))}.")
        for label in ("absolute_change", "relative_change", "percentage_point_change"):
            if item.get(label) is not None:
                decimal_value(item[label], field=f"{item['id']}.{label}")
        if item.get("projection") is not None:
            projection = item["projection"]
            if not isinstance(projection, dict) or projection.get("epistemic") != "PROJECTION":
                raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} projection must remain classified as PROJECTION.")
            if set(projection) - {"value", "unit", "period", "epistemic", "basis_period_days", "assumption"}:
                raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} projection contains unsupported fields.")
            decimal_value(projection.get("value"), field=f"{item['id']}.projection.value")
            _string(projection.get("assumption"), f"{item['id']}.projection.assumption", maximum=1000)
        from .quantitative import verify_insight
        allowed_insight = {"id", "metric", "kind", "unit", "semantics", "baseline", "current",
                           "absolute_change", "relative_change", "percentage_point_change", "direction",
                           "interpretation", "epistemic", "confidence", "baseline_semantics", "warnings",
                           "projection", "normalization"}
        if set(item) - allowed_insight:
            raise CommunicationError("CONTRACT_INVALID", f"Quantitative insight {item['id']} contains unsupported fields.")
        insights.append(verify_insight(item))
    for finding in findings:
        missing = set(finding["quantitative_insight_ids"]) - insight_ids
        if missing:
            raise CommunicationError("CONTRACT_INVALID", f"Finding {finding['id']} references unknown quantitative insights: {', '.join(sorted(missing))}.")

    editorial_raw = raw.get("editorial", {})
    if not isinstance(editorial_raw, dict) or set(editorial_raw) - {
            "decision", "materiality_note", "appendix_finding_ids", "appendix_insight_ids", "appendix_evidence_ids"}:
        raise CommunicationError("CONTRACT_INVALID", "Editorial strategy contains unsupported fields.")
    editorial = {
        "decision": _string(editorial_raw.get("decision"), "editorial.decision", maximum=1000, required=False),
        "materiality_note": _string(editorial_raw.get("materiality_note"), "editorial.materiality_note", maximum=1000, required=False),
        "appendix_finding_ids": _ids(editorial_raw.get("appendix_finding_ids", []), "editorial.appendix_finding_ids"),
        "appendix_insight_ids": _ids(editorial_raw.get("appendix_insight_ids", []), "editorial.appendix_insight_ids"),
        "appendix_evidence_ids": _ids(editorial_raw.get("appendix_evidence_ids", []), "editorial.appendix_evidence_ids"),
    }
    for field, known in (("appendix_finding_ids", finding_ids), ("appendix_insight_ids", insight_ids),
                         ("appendix_evidence_ids", evidence_ids)):
        missing = set(editorial[field]) - known
        if missing:
            raise CommunicationError("CONTRACT_INVALID", f"editorial.{field} references unknown IDs: {', '.join(sorted(missing))}.")

    thesis = _string(raw.get("thesis"), "thesis", maximum=2000)
    storyline_raw = raw.get("storyline", [])
    if not isinstance(storyline_raw, list) or len(storyline_raw) > 100:
        raise CommunicationError("CONTRACT_INVALID", "Storyline must be a bounded list.")
    storyline = []
    for index, item in enumerate(storyline_raw):
        if not isinstance(item, dict):
            raise CommunicationError("CONTRACT_INVALID", "Storyline entries must be objects.")
        item_findings = _ids(item.get("finding_ids", []), f"storyline[{index}].finding_ids")
        if set(item_findings) - finding_ids:
            raise CommunicationError("CONTRACT_INVALID", f"Storyline step {index + 1} references an unknown finding.")
        storyline.append({"title": _string(item.get("title"), f"storyline[{index}].title", maximum=240),
                          "finding_ids": item_findings,
                          "rationale": _string(item.get("rationale"), f"storyline[{index}].rationale", maximum=1000, required=False)})

    sections = raw.get("sections", [])
    if not isinstance(sections, list) or len(sections) > 100:
        raise CommunicationError("CONTRACT_INVALID", "Artifact sections must be a bounded list.")
    normalized_sections = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise CommunicationError("CONTRACT_INVALID", "Artifact sections must be objects.")
        if set(section) - {"title", "body", "finding_ids", "evidence_ids", "insight_ids", "visual_intent"}:
            raise CommunicationError("CONTRACT_INVALID", f"Section {index + 1} contains unsupported fields.")
        refs = _ids(section.get("finding_ids", []), f"sections[{index}].finding_ids")
        if set(refs) - finding_ids:
            raise CommunicationError("CONTRACT_INVALID", f"Section {index + 1} references an unknown finding.")
        evidence_refs = _ids(section.get("evidence_ids", []), f"sections[{index}].evidence_ids")
        if set(evidence_refs) - evidence_ids:
            raise CommunicationError("CONTRACT_INVALID", f"Section {index + 1} references unknown evidence.")
        insight_refs = _ids(section.get("insight_ids", []), f"sections[{index}].insight_ids")
        if set(insight_refs) - insight_ids:
            raise CommunicationError("CONTRACT_INVALID", f"Section {index + 1} references an unknown quantitative insight.")
        normalized = {"title": _string(section.get("title"), f"sections[{index}].title", maximum=240),
                      "body": _string(section.get("body", ""), f"sections[{index}].body", maximum=20000),
                      "finding_ids": refs, "evidence_ids": evidence_refs, "insight_ids": insight_refs}
        if "visual_intent" in section:
            intent = validate_visual_intent(section["visual_intent"], f"sections[{index}].visual_intent")
            supported = set(evidence_refs)
            for finding_id in refs:
                finding = next(item for item in findings if item["id"] == finding_id)
                supported.update(finding["evidence_ids"])
                supported.update(finding["counter_evidence_ids"])
            for insight_id in insight_refs:
                insight = next(item for item in insights if item["id"] == insight_id)
                supported.update(_insight_evidence_ids(insight))
            intent_refs = _visual_intent_evidence_ids(intent)
            if intent_refs - supported:
                raise CommunicationError("CONTRACT_INVALID", f"sections[{index}].visual_intent references evidence not selected for the section.")
            normalized["visual_intent"] = intent
        normalized_sections.append(normalized)

    slides = raw.get("slides", [])
    if not isinstance(slides, list) or len(slides) > 200:
        raise CommunicationError("CONTRACT_INVALID", "Presentation slides must be a bounded list.")
    normalized_slides = []
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise CommunicationError("CONTRACT_INVALID", "Presentation slides must be objects.")
        if set(slide) - {"role", "title", "body", "finding_ids", "evidence_ids", "insight_ids", "visual_intent"}:
            raise CommunicationError("CONTRACT_INVALID", f"Slide {index + 1} contains unsupported fields.")
        role = slide.get("role", "content")
        if not isinstance(role, str) or role not in {"cover", "content", "architecture", "appendix"}:
            raise CommunicationError("CONTRACT_INVALID", f"Slide {index + 1} has an unsupported role.")
        finding_refs = _ids(slide.get("finding_ids", []), f"slides[{index}].finding_ids")
        evidence_refs = _ids(slide.get("evidence_ids", []), f"slides[{index}].evidence_ids")
        insight_refs = _ids(slide.get("insight_ids", []), f"slides[{index}].insight_ids")
        if set(finding_refs) - finding_ids or set(evidence_refs) - evidence_ids or set(insight_refs) - insight_ids:
            raise CommunicationError("CONTRACT_INVALID", f"Slide {index + 1} contains an unresolved evidence, finding, or insight reference.")
        normalized = {"role": role, "title": _string(slide.get("title"), f"slides[{index}].title", maximum=240),
                      "body": _string(slide.get("body", ""), f"slides[{index}].body", maximum=10000),
                      "finding_ids": finding_refs, "evidence_ids": evidence_refs, "insight_ids": insight_refs}
        if "visual_intent" in slide:
            intent = validate_visual_intent(slide["visual_intent"], f"slides[{index}].visual_intent")
            supported = set(evidence_refs)
            for finding_id in finding_refs:
                finding = next(item for item in findings if item["id"] == finding_id)
                supported.update(finding["evidence_ids"])
                supported.update(finding["counter_evidence_ids"])
            for insight_id in insight_refs:
                insight = next(item for item in insights if item["id"] == insight_id)
                supported.update(_insight_evidence_ids(insight))
            intent_refs = _visual_intent_evidence_ids(intent)
            if intent_refs - supported:
                raise CommunicationError("CONTRACT_INVALID", f"slides[{index}].visual_intent references evidence not selected for the slide.")
            normalized["visual_intent"] = intent
        normalized_slides.append(normalized)

    if artifact_type == "presentation" and not normalized_slides:
        raise CommunicationError("CONTRACT_INVALID", "Presentation plans require at least one slide.")
    if artifact_type != "presentation" and not normalized_sections:
        raise CommunicationError("CONTRACT_INVALID", "Report and summary plans require at least one section.")

    architecture_relevant = raw.get("architecture_relevant", request.get("architecture_relevant", False))
    if "architecture_relevant" in raw and "architecture_relevant" in request and raw["architecture_relevant"] != request["architecture_relevant"]:
        raise CommunicationError("CONTRACT_INVALID", "Top-level and request architecture_relevant values conflict.")
    result = {
        "schema_version": 1, "request": request_result,
        "title": _string(raw.get("title", request.get("title", "Communication artifact")), "title", maximum=240),
        "thesis": thesis, "evidence": evidence, "findings": findings,
        "quantitative_insights": insights, "storyline": storyline,
        "selection_rationale": _bounded_text_list(raw.get("selection_rationale", []), "selection_rationale"),
        "exclusions": _bounded_text_list(raw.get("exclusions", []), "exclusions"),
        "sections": normalized_sections, "slides": normalized_slides,
        "architecture_relevant": architecture_relevant, "editorial": editorial,
        "metadata": _validate_metadata(raw.get("metadata", {})),
    }
    if not isinstance(result["architecture_relevant"], bool):
        raise CommunicationError("CONTRACT_INVALID", "architecture_relevant must be boolean.")
    return result


def _bounded_text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 100:
        raise CommunicationError("CONTRACT_INVALID", f"{field} must be a bounded list of text.")
    return [_string(item, field, maximum=1000) for item in value]


def _validate_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"artifact_id", "created_at", "plan_version", "renderer", "theme", "sources"}:
        raise CommunicationError("CONTRACT_INVALID", "Artifact metadata contains unsupported fields.")
    result = dict(value)
    if "artifact_id" in result and (not isinstance(result["artifact_id"], str) or not IDENTIFIER.fullmatch(result["artifact_id"])):
        raise CommunicationError("CONTRACT_INVALID", "Artifact metadata artifact_id must be a stable identifier.")
    for field in ("created_at", "plan_version", "renderer", "theme"):
        if field in result:
            result[field] = _string(result[field], f"metadata.{field}", maximum=240)
    if "sources" in result:
        sources = result["sources"]
        if not isinstance(sources, list) or len(sources) > 2000:
            raise CommunicationError("CONTRACT_INVALID", "Artifact metadata sources must be a bounded list.")
        normalized_sources = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict) or set(source) - {"id", "type", "locator", "sha256"}:
                raise CommunicationError("CONTRACT_INVALID", f"metadata.sources[{index}] must be a provenance descriptor.")
            identifier = source.get("id")
            digest = source.get("sha256")
            if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
                raise CommunicationError("CONTRACT_INVALID", f"metadata.sources[{index}] has an invalid ID.")
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)):
                raise CommunicationError("CONTRACT_INVALID", f"metadata.sources[{index}] has an invalid SHA-256 hash.")
            normalized_sources.append({"id": identifier,
                                       "type": _string(source.get("type"), f"metadata.sources[{index}].type", maximum=80),
                                       "locator": _string(source.get("locator"), f"metadata.sources[{index}].locator", maximum=2000),
                                       "sha256": digest})
        if len({item["id"] for item in normalized_sources}) != len(normalized_sources):
            raise CommunicationError("CONTRACT_INVALID", "Artifact metadata source IDs must be unique.")
        result["sources"] = normalized_sources
    return result
