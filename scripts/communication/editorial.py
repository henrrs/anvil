"""Audience policy and bounded editorial signals for renderer-independent plans."""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

from .planning import validate_plan


AUDIENCE_PROFILES: dict[str, dict[str, Any]] = {
    "executive": {
        "focus": "impact, decision, risk, confidence, and next action",
        "detail": "material magnitude first; method and caveats only where they change the decision",
        "numeric_context": "compact comparison, period, and decision-relevant delta",
    },
    "financial": {
        "focus": "baseline, observed spend or savings, assumptions, and scenarios",
        "detail": "keep measured outcomes separate from annualized projections and capture scenarios",
        "numeric_context": "baseline-to-current, period, unit, annualization basis, and assumptions",
    },
    "technical_leadership": {
        "focus": "architecture, constraints, scale, reliability, and trade-offs",
        "detail": "show boundary and operational consequence before implementation detail",
        "numeric_context": "baseline, distribution, scale, and confidence",
    },
    "engineering": {
        "focus": "mechanism, method, runtime evidence, diagnostics, and interfaces",
        "detail": "retain implementation evidence, failure modes, and reproducible measurements",
        "numeric_context": "raw measurements, units, periods, sample, and normalization",
    },
    "technical": {
        "focus": "method, baseline, distribution, uncertainty, and operational detail",
        "detail": "retain method and measurements needed to inspect the conclusion",
        "numeric_context": "raw values, baseline, period, distribution, and confidence",
    },
    "mixed": {
        "focus": "impact followed by enough method and uncertainty to support it",
        "detail": "lead with the consequence, then progressively reveal technical evidence",
        "numeric_context": "compact impact with directly available methodological context",
    },
}


_GENERIC_TITLES = {
    "overview", "results", "conclusion", "next steps", "architecture", "benefits",
    "performance analysis", "cost analysis", "solution", "pilot results",
}
_CLAIM_WORDS = {
    "is", "are", "was", "were", "shows", "reduces", "increases", "increased", "falls", "fell",
    "decreases", "decreased", "declines", "declined", "grew", "keeps", "supports", "requires", "moves",
    "remains", "causes", "because", "while", "enables", "improved", "worsened", "dropped", "rose", "sank",
    "isolate", "isolates", "isolated",
    "é", "são", "foi", "reduz", "aumenta", "caiu", "cresceu", "mostra", "mantém", "permanece",
}
_NON_CARD_RELATIONSHIPS = {"magnitude", "trend", "process", "causality", "architecture", "hierarchy",
                           "composition", "distribution"}
_PROSE_CLICHES = (
    "in an increasingly dynamic landscape", "in today's rapidly evolving environment",
    "robust, scalable and efficient", "unlock the full potential", "seamlessly leverage",
    "é importante destacar", "robusto, escalável e eficiente",
)
_DIMENSIONS = (
    "message_clarity", "storyline", "evidence_discipline", "audience_fit", "visual_hierarchy",
    "semantic_visualization", "numerical_communication", "naturalness", "motion_semantics",
    "technical_integrity", "visual_qa",
)


def audience_profile(audience: str) -> dict[str, Any]:
    """Return audience priorities as guidance; this never rewrites evidence or prose."""
    if audience not in AUDIENCE_PROFILES:
        raise ValueError("unsupported communication audience")
    return {"audience": audience, **AUDIENCE_PROFILES[audience]}


def _signal(code: str, dimension: str, message: str, locations: list[str], remediation: str) -> dict[str, Any]:
    return {"code": code, "dimension": dimension, "severity": "review", "message": message,
            "locations": locations, "remediation": remediation}


def critique_plan(raw: Any) -> dict[str, Any]:
    """Surface objective editorial risk signals without pretending to judge taste or truth."""
    plan = validate_plan(raw)
    request = plan["request"]
    pages = plan["slides"] if request["artifact"] == "presentation" else plan["sections"]
    signals: list[dict[str, Any]] = []
    intents = [(f"slide {index + 1}" if request["artifact"] == "presentation" else f"section {index + 1}",
                page.get("visual_intent")) for index, page in enumerate(pages)]
    modeled = [(where, intent) for where, intent in intents if intent is not None]

    for (where, _), page in zip(intents, pages):
        title = page["title"].strip()
        words = set(title.casefold().replace("—", " ").replace("→", " ").split())
        if title.casefold() in _GENERIC_TITLES:
            signals.append(_signal("GENERIC_ASSERTION", "message_clarity",
                                   "The heading names a topic but does not state the page's conclusion.", [where],
                                   "Rewrite it as the evidence-backed message the audience should remember."))
        elif not words & _CLAIM_WORDS and not any(mark in title for mark in ("→", ":", "—")):
            signals.append(_signal("TITLE_MAY_BE_A_LABEL", "message_clarity",
                                   "The heading may be a topic label rather than an assertion.", [where],
                                   "Check whether the title alone advances the argument."))

    if modeled:
        forms = Counter(intent["form"] for _, intent in modeled)
        card_pages = [where for where, intent in modeled if intent["form"] == "cards"]
        if len(card_pages) >= 3 and len(card_pages) / len(modeled) >= 0.6:
            signals.append(_signal("CARD_HEAVY_COMPOSITION", "naturalness",
                                   "Cards dominate the declared visual language across the artifact.", card_pages,
                                   "Check whether each page expresses independent comparable units; use flow, containment, hierarchy, magnitude, or another semantic form where it better matches the relationship."))
        if len(modeled) >= 4 and len(forms) == 1:
            only_form = next(iter(forms))
            signals.append(_signal("REPEATED_VISUAL_FORM", "naturalness",
                                   f"Every modeled page uses the same visual form ({only_form}).", [where for where, _ in modeled],
                                   "Vary composition only where the evidence relationship calls for it; do not add variation for decoration."))
        prominence = Counter(intent["prominence"] for _, intent in modeled)
        if len(modeled) >= 3 and len(prominence) == 1:
            signals.append(_signal("UNDIFFERENTIATED_PROMINENCE", "visual_hierarchy",
                                   "All modeled pages assign the same prominence level.", [where for where, _ in modeled],
                                   "Check whether the argument has a primary message and supporting/context pages with different visual weight."))
        for where, intent in modeled:
            if intent["form"] == "cards" and intent["relationship"] in _NON_CARD_RELATIONSHIPS:
                signals.append(_signal("FORM_RELATIONSHIP_MISMATCH", "semantic_visualization",
                                       f"Cards may obscure the declared {intent['relationship']} relationship.", [where],
                                       "Select a form whose geometry makes that relationship easier to perceive."))
            if len(intent["color_roles"]) >= 5:
                signals.append(_signal("COLOR_COMPETITION", "visual_hierarchy",
                                       "This page declares five or more semantic color roles.", [where],
                                       "Keep color focused on audience attention, state, evidence type, or a meaningful exception."))
            if intent["motion"]["mode"] == "animated":
                signals.append(_signal("STATIC_RENDERER_FALLBACK", "motion_semantics",
                                       "The storyboard is semantic, but this release has no dynamic animation renderer.", [where],
                                       "Materialize a static process/sequence diagram unless an animation renderer is explicitly available."))
                transitions = [state["change"].casefold() for state in intent["motion"]["states"]]
                if len(set(transitions)) < len(transitions):
                    signals.append(_signal("DECORATIVE_MOTION", "motion_semantics",
                                           "Storyboard states repeat the same information change.", [where],
                                           "Keep motion only when each transition explains a distinct sequence, cause, or state change."))

    prose = " ".join([plan["title"], plan["thesis"], *(page["title"] + " " + page["body"] for page in pages)]).casefold()
    cliches = [phrase for phrase in _PROSE_CLICHES if phrase in prose]
    if cliches:
        signals.append(_signal("AI_PROSE_PATTERN", "naturalness",
                               "A generic corporate phrase may be adding words without evidence or decision value.",
                               [phrase for phrase in cliches], "Replace it with a specific evidence-backed consequence or remove it."))
    decimal_theater = []
    for index, page in enumerate(pages, 1):
        if re.search(r"\b\d+\.\d{4,}\b", page["title"] + " " + page["body"]):
            decimal_theater.append(f"slide {index}" if request["artifact"] == "presentation" else f"section {index}")
    if decimal_theater:
        signals.append(_signal("PRECISION_THEATER", "numerical_communication",
                               "Visible copy contains values with four or more decimal places.", decimal_theater,
                               "Check whether the decision needs this precision; retain the exact source value in the underlying evidence."))
    if len(plan["evidence"]) >= 40 and len(pages) <= 3:
        signals.append(_signal("EXHAUSTIVE_CONTENT", "storyline",
                               "A small artifact plan retains a large evidence inventory; check for decision-irrelevant material.",
                               ["artifact"], "Promote material evidence, demote supporting detail, and retain the rest only if it has a clear audit purpose."))

    important = []
    for finding in plan["findings"]:
        relevant = finding["relevance"].get(request["audience"], "medium") == "high"
        material = finding["materiality"] == "high"
        if (relevant or material) and not finding["implications"]:
            important.append(finding["id"])
    if important:
        signals.append(_signal("IMPLICATION_NOT_STATED", "storyline",
                               "Important findings have no explicit implication or decision consequence.", important,
                               "Add a qualified implication only when the evidence supports one; otherwise state the remaining unknown."))

    dimensions = {name: "PENDING_MODEL" for name in _DIMENSIONS}
    dimensions["evidence_discipline"] = "PASS_STRUCTURAL_REFERENCES"
    dimensions["technical_integrity"] = "PASS_CONTRACT_VALIDATION"
    dimensions["numerical_communication"] = "PASS_CALCULATION_CONTRACT" if plan["quantitative_insights"] else "NOT_APPLICABLE"
    dimensions["visual_qa"] = "NOT_APPLICABLE_TO_PLAN"  # geometry is reviewed after materialization
    dimensions["motion_semantics"] = ("PENDING_MODEL" if any(intent and intent["motion"]["mode"] == "animated"
                                                             for _, intent in intents)
                                      else "NOT_APPLICABLE")
    return {
        "schema_version": 1,
        "status": "PENDING_MODEL_REVIEW",
        "audience_profile": audience_profile(request["audience"]),
        "dimensions": dimensions,
        "candidate_signals": signals,
        "visual_intent_coverage": {"modeled_pages": len(modeled), "total_pages": len(pages)},
        "limits": "Signals identify review targets; they do not prove semantic quality, truth, or aesthetic failure. Human/model judgment owns materiality, storyline, audience fit, naturalness, and final representation.",
    }
