"""Deterministic constraint, budget, and audience policy helpers."""

from __future__ import annotations

import math
import re
from typing import Any

from .contracts import validate_artifact
from .errors import CommunicationError
from .quantitative import decimal_value


_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "um": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3,
                 "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10}
_PRIORITY = {
    ("explicit", "hard"): 500,
    ("explicit", "soft"): 400,
    ("policy", "hard"): 350,
    ("policy", "soft"): 300,
    ("inferred", "hard"): 275,
    ("inferred", "soft"): 250,
    ("memory", "hard"): 225,
    ("memory", "soft"): 200,
    ("default", "hard"): 150,
    ("default", "soft"): 100,
}


def extract_explicit_constraints(text: str) -> list[dict[str, Any]]:
    """Catch a few unambiguous hard constraints as a backstop to model parsing."""
    result: list[dict[str, Any]] = []
    words = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
    match = re.search(rf"\b(?:exactly|precisely|exatamente|precisamente)\s+(\d+|{words})\s+(?:slides?|slides?|p[aá]ginas?)\b", text, re.IGNORECASE)
    if match:
        token = match.group(1).casefold()
        count = int(token) if token.isdigit() else _NUMBER_WORDS[token]
        result.append({"kind": "exact_slides", "value": count, "strength": "hard", "origin": "explicit",
                       "rationale": "Explicit exact slide-count request detected in the natural-language prompt."})
    if re.search(r"\b(?:no estimates|measured values only|sem estimativas|somente valores medidos)\b", text, re.IGNORECASE):
        result.append({"kind": "no_estimates", "value": True, "strength": "hard", "origin": "explicit",
                       "rationale": "The user explicitly restricted the epistemic status of included evidence."})
    return result


def effective_constraints(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(constraints, key=lambda item: (-_PRIORITY[(item["origin"], item["strength"])], item["kind"]))
    winners: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []
    for item in ordered:
        previous = winners.get(item["kind"])
        if previous is None:
            winners[item["kind"]] = item
            continue
        if previous["value"] != item["value"]:
            if previous["strength"] == item["strength"] == "hard" and previous["origin"] == item["origin"] == "explicit":
                conflicts.append(item["kind"])
    if conflicts:
        raise CommunicationError("CONSTRAINT_CONFLICT", "Conflicting explicit hard constraints: " + ", ".join(sorted(set(conflicts))) + ".",
                                 remediation="Ask which requirement should take precedence before materializing the artifact.")
    return list(winners.values())


def communication_budget(plan: dict[str, Any]) -> dict[str, Any]:
    request = plan["request"]
    audience = request["audience"]
    slides = plan.get("slides", [])
    content_slides = [slide for slide in slides if slide["role"] not in {"cover", "appendix"}]
    minutes = request.get("minutes")
    if isinstance(minutes, (int, float)) and minutes > 0:
        time_messages = max(1, math.ceil(minutes / 2))
    else:
        time_messages = len(content_slides) if content_slides else max(1, len(plan.get("storyline", [])))
    primary_messages = min(len(content_slides), time_messages) if content_slides else time_messages
    words_per_message = {"executive": 55, "technical": 95, "mixed": 75}[audience]
    return {
        "audience": audience,
        "minutes": minutes,
        "artifact_capacity": len(content_slides) or len(plan.get("sections", [])),
        "primary_message_count": primary_messages,
        "recommended_words_per_primary_message": words_per_message,
        "one_primary_message_per_slide": request["artifact"] == "presentation",
        "rationale": "Budget follows the explicit audience, slide/page capacity, and available speaking time.",
    }


def validate_constraints(plan: dict[str, Any]) -> dict[str, Any]:
    constraints = effective_constraints(plan["request"].get("constraints", []))
    request = plan["request"]
    slides = plan.get("slides", [])
    indexed = {item["kind"]: item["value"] for item in constraints}
    errors: list[str] = []
    warnings: list[str] = []
    slide_constraint_kinds = {"exact_slides", "min_slides", "max_slides", "cover_count", "content_count",
                              "architecture_count", "appendix_count", "architecture_required",
                              "architecture_if_relevant", "appendix_forbidden"}
    if request["artifact"] != "presentation" and any(item["kind"] in slide_constraint_kinds for item in constraints):
        errors.append("Slide-specific constraints cannot be applied to a report or summary artifact.")
    if request["artifact"] == "presentation":
        if not slides:
            errors.append("Presentation plan has no slides.")
        count = len(slides)
        exact = indexed.get("exact_slides")
        if exact is not None:
            if not isinstance(exact, int) or isinstance(exact, bool) or exact < 1:
                errors.append("exact_slides must be a positive integer.")
            elif count != exact:
                errors.append(f"Hard slide-count constraint requires {exact} slides; plan contains {count}.")
        minimum = indexed.get("min_slides")
        maximum = indexed.get("max_slides")
        if minimum is not None and maximum is not None and minimum > maximum:
            errors.append("Minimum slide count exceeds maximum slide count.")
        if minimum is not None and count < minimum:
            errors.append(f"Plan has {count} slides; minimum is {minimum}.")
        if maximum is not None and count > maximum:
            errors.append(f"Plan has {count} slides; maximum is {maximum}.")
        required = {role: indexed.get(f"{role}_count") for role in ("cover", "content", "architecture", "appendix")}
        actual = {role: sum(slide["role"] == role for slide in slides) for role in required}
        for role, expected in required.items():
            if expected is not None and actual[role] != expected:
                errors.append(f"Hard {role} count requires {expected}; plan contains {actual[role]}.")
        if indexed.get("architecture_required") is True and actual["architecture"] < 1:
            errors.append("A required architecture slide is missing.")
        if indexed.get("architecture_if_relevant") is True:
            relevant = plan.get("architecture_relevant", False)
            if relevant and actual["architecture"] < 1:
                errors.append("Architecture is relevant but the conditional architecture slide is missing.")
        if indexed.get("appendix_forbidden") is True and actual["appendix"]:
            errors.append("Appendix slides are forbidden by a hard constraint.")
        if any(slide["role"] == "cover" for slide in slides[1:]):
            errors.append("A cover slide must be first.")
        if slides and sum(slide["role"] == "cover" for slide in slides) > 1:
            errors.append("A presentation may contain at most one cover slide.")
        if request.get("minutes") and count > math.ceil(request["minutes"] / 1.25):
            warnings.append("Slide count is dense for the requested presentation time.")
        if request["audience"] == "executive":
            dense = [index + 1 for index, slide in enumerate(slides) if len(slide["body"].split()) > 100]
            if dense:
                warnings.append("Executive slide copy is dense on slides " + ", ".join(map(str, dense)) + ".")
    else:
        if not plan.get("sections"):
            errors.append("Document plan has no sections.")

    disallow_estimates = indexed.get("no_estimates") is True or indexed.get("measured_only") is True
    if disallow_estimates:
        evidence_by_id = {item["id"]: item for item in plan["evidence"]}
        used_ids = set()
        used_insight_ids = set()
        for slide in slides:
            used_ids.update(slide["evidence_ids"])
            for finding_id in slide["finding_ids"]:
                finding = next((item for item in plan["findings"] if item["id"] == finding_id), None)
                if finding:
                    used_ids.update(finding["evidence_ids"])
            for insight_id in slide["insight_ids"]:
                used_insight_ids.add(insight_id)
                insight = next((item for item in plan["quantitative_insights"] if item["id"] == insight_id), None)
                if insight:
                    for observation in (insight.get("baseline"), insight.get("current")):
                        if observation:
                            used_ids.update(observation["evidence_ids"])
        for section in plan.get("sections", []):
            used_ids.update(section["evidence_ids"])
            for finding_id in section["finding_ids"]:
                finding = next((item for item in plan["findings"] if item["id"] == finding_id), None)
                if finding:
                    used_ids.update(finding["evidence_ids"])
            for insight_id in section["insight_ids"]:
                used_insight_ids.add(insight_id)
                insight = next((item for item in plan["quantitative_insights"] if item["id"] == insight_id), None)
                if insight:
                    for observation in (insight.get("baseline"), insight.get("current")):
                        if observation:
                            used_ids.update(observation["evidence_ids"])
        prohibited = {"ESTIMATE", "PROJECTION", "ASSUMPTION"}
        if any(evidence_by_id[item]["epistemic"] in prohibited for item in used_ids):
            errors.append("A no-estimates/measured-only constraint includes estimated, projected, or assumed evidence.")
        prohibited_quantitative = {"ESTIMATE", "PROJECTION", "ASSUMPTION", "PROPOSAL"}
        if any(insight.get("epistemic") in prohibited_quantitative or insight.get("projection")
               or (insight.get("normalization") and insight["normalization"].get("epistemic") in prohibited_quantitative)
               for insight in plan["quantitative_insights"] if insight["id"] in used_insight_ids):
            errors.append("A no-estimates/measured-only constraint includes an estimated, projected, assumed, or proposed quantitative value.")

    if errors:
        raise CommunicationError("CONSTRAINT_CONFLICT", " ".join(errors),
                                 remediation="Revise the plan or ask the user to resolve conflicting hard constraints.")
    return {"constraints": constraints, "budget": communication_budget(plan), "warnings": warnings, "status": "PASS"}


def audience_emphasis(audience: str, insight: dict[str, Any]) -> dict[str, str]:
    if audience == "executive":
        focus = "absolute_financial_or_operational_impact"
        detail = "Emphasize decision relevance, material magnitude, direction, and confidence."
    elif audience == "technical":
        focus = "method_baseline_distribution_and_confidence"
        detail = "Preserve baseline, raw values, normalized measures, sample size, and methodology."
    elif audience == "mixed":
        focus = "impact_then_supporting_method"
        detail = "Lead with impact and reveal enough method and uncertainty for technical readers."
    else:
        raise CommunicationError("CONTRACT_INVALID", "Audience must be executive, technical, or mixed.")
    return {"focus": focus, "rationale": detail,
            "values_preserved": ";".join(str(insight.get(key)) for key in ("absolute_change", "relative_change", "percentage_point_change"))}


def select_findings(findings: list[dict[str, Any]], *, audience: str, limit: int) -> dict[str, list[dict[str, Any]]]:
    if audience not in {"executive", "technical", "mixed"} or limit < 1:
        raise CommunicationError("CONTRACT_INVALID", "Finding selection needs a supported audience and a positive limit.")
    rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
    relevance_rank = {"high": 3, "medium": 2, "low": 1}
    def score(finding: dict[str, Any]) -> tuple[int, int, Decimal, str]:
        confidence = rank.get(finding.get("confidence", "UNKNOWN"), 0)
        relevance = relevance_rank.get(finding.get("relevance", {}).get(audience, "medium"), 2)
        impact = abs(decimal_value(finding.get("impact", 0), field="finding.impact"))
        return confidence, relevance, impact, finding.get("id", "")
    ordered = sorted(findings, key=lambda item: (-score(item)[0], -score(item)[1], -score(item)[2], score(item)[3]))
    selected = ordered[:limit]
    selected_ids = {item["id"] for item in selected}
    return {
        "selected": [{**item, "selection_rationale": f"Ranked for {audience} audience by confidence, audience relevance, and decision impact."}
                     for item in selected],
        "excluded": [{"id": item["id"], "claim": item["claim"],
                      "rationale": "Below the communication budget after confidence, audience relevance, and impact ranking."}
                     for item in ordered if item["id"] not in selected_ids],
    }


def select_quant_visual(question: str, *, metric_kind: str, normalized: bool = False) -> dict[str, str]:
    text = question.casefold()
    rules = [
        (("correlat", "relationship between", "correlação", "relacionamento entre"), "correlation"),
        (("distribution", "percentile", "p95", "p99", "variability", "distribuição", "percentil"), "distribution"),
        (("over time", "trend", "daily", "weekly", "ao longo do tempo", "tendência"), "trend"),
        (("waterfall", "where did", "contribution to", "decompos", "composição da redução"), "waterfall"),
        (("share", "composition", "portion", "participação", "composição"), "composition"),
        (("target", "budget", "slo", "meta", "orçamento"), "target_vs_actual"),
        (("which", "rank", "most", "largest", "ranking", "maior", "qual workload"), "ranking"),
        (("before", "after", "pre/post", "antes", "depois"), "before_after"),
    ]
    visual = next((kind for terms, kind in rules if any(term in text for term in terms)), None)
    if visual is None:
        visual = "kpi_delta" if metric_kind in {"amount", "rate", "count"} else "table"
    return {"visual": visual, "rationale": f"Selected {visual} from the stated question and {metric_kind} relationship; normalized={str(normalized).lower()}."}


def validate_plan(raw: Any) -> dict[str, Any]:
    plan = validate_artifact(raw)
    validation = validate_constraints(plan)
    plan["communication_budget"] = validation["budget"]
    plan["constraint_warnings"] = validation["warnings"]
    plan["quality_gates"] = {"structure": "PASS", "constraints": "PASS", "evidence_traceability": "PASS",
                             "quantitative_integrity": "PASS", "provenance": "PASS",
                             "semantic_claim_review": "PENDING_MODEL", "output_validity": "PENDING_RENDER"}
    return plan
