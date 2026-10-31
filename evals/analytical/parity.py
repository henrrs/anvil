"""Communication-surface parity checks kept outside production renderers."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import SURFACES, validate_candidate


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _surface_contradictions(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    checked = validate_candidate(candidate)
    canonical = {fact["id"]: fact for fact in checked["facts"]}
    failures: list[dict[str, Any]] = []
    for surface in sorted(SURFACES):
        for index, item in enumerate(checked["surfaces"].get(surface, [])):
            fact_id = item["fact_id"]
            base = canonical.get(fact_id)
            if base is None:
                failures.append({"class": "COMMUNICATION", "id": f"parity-{surface}-{index}",
                                 "summary": f"{surface} references unknown canonical fact {fact_id!r}.",
                                 "evidence": {"surface": surface, "fact_id": fact_id}})
                continue
            left, right = _number(base.get("value")), _number(item.get("value"))
            values_match = (left == right) if left is not None and right is not None else base.get("value") == item.get("value")
            if not values_match or base.get("unit", "unknown") != item.get("unit", "unknown"):
                failures.append({"class": "COMMUNICATION", "id": f"parity-{surface}-{index}",
                                 "summary": f"{surface} changes the value or unit of canonical fact {fact_id!r}.",
                                 "evidence": {"surface": surface, "fact_id": fact_id,
                                              "canonical_value": base.get("value"), "surface_value": item.get("value"),
                                              "canonical_unit": base.get("unit"), "surface_unit": item.get("unit")}})
    return failures


def parity_failures(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return _surface_contradictions(candidate)


def obvious_claim_failures(candidate: dict[str, Any], *, period_count: int | None = None,
                           forbidden_claims: list[str] | None = None) -> list[dict[str, Any]]:
    """Catch known high-risk overclaims; this is a floor, not semantic judging."""
    checked = validate_candidate(candidate)
    failures: list[dict[str, Any]] = []
    forbidden = [item.casefold() for item in (forbidden_claims or [])]
    causal_forbidden = any("caus" in item for item in forbidden)
    for index, claim in enumerate(checked["claims"]):
        text = claim["text"].casefold()
        if causal_forbidden and re.search(r"\b(cause|causes|caused|causing|because of)\b", text):
            failures.append({"class": "CLAIM_CALIBRATION", "id": f"causal-claim-{index}",
                             "summary": "A causal claim is made where the fixture supplies association evidence only.",
                             "evidence": {"claim_index": index}})
        if any(re.search(r"\b(?:every|all)\s+(?:entities|entity|services|service|users|user)\b", text)
               and any(token in forbidden_text for token in ("every", "all")) for forbidden_text in forbidden):
            failures.append({"class": "CLAIM_CALIBRATION", "id": f"breadth-claim-{index}",
                             "summary": "A universal population claim conflicts with the fixture's population bounds.",
                             "evidence": {"claim_index": index}})
        if period_count is not None and period_count < 3 and re.search(r"\b(sustained trend|long-term trend|keeps? (?:rising|falling)|trend over time)\b", text):
            failures.append({"class": "CLAIM_CALIBRATION", "id": f"short-history-trend-{index}",
                             "summary": "A trend is asserted from fewer than three observed periods.",
                             "evidence": {"claim_index": index, "period_count": period_count}})
    known_fact_ids = {fact["id"] for fact in checked["facts"]}
    for index, claim in enumerate(checked["claims"]):
        missing = sorted(set(claim["evidence_fact_ids"]) - known_fact_ids)
        if missing:
            failures.append({"class": "CLAIM_SUPPORT", "id": f"claim-evidence-{index}",
                             "summary": "A claim references facts absent from the candidate's evidence list.",
                             "evidence": {"claim_index": index, "unknown_fact_ids": missing}})
    return failures
