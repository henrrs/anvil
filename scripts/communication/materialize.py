"""Human-oriented Markdown renderers over validated semantic plans."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import CommunicationError
from .planning import validate_plan
from .quantitative import format_metric


def _finding_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in plan["findings"]}


def _insight_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in plan["quantitative_insights"]}


def _insight_evidence_refs(insight: dict[str, Any]) -> list[str]:
    refs = [ref for field in ("baseline", "current") for ref in (insight.get(field) or {}).get("evidence_ids", [])]
    normalization = insight.get("normalization") or {}
    refs.extend(normalization.get("baseline_denominator_evidence_ids", []))
    refs.extend(normalization.get("current_denominator_evidence_ids", []))
    return list(dict.fromkeys(refs))


def _epistemic_note(epistemic: str, confidence: str) -> str:
    return f"{epistemic.replace('_', ' ').title()}; confidence {confidence.lower()}"


def _visual_note(intent: dict[str, Any]) -> list[str]:
    lines = [f"\n**Visual intent:** {intent['relationship']} → {intent['form']} ({intent['prominence']}).",
             f"**Primary message:** {intent['primary_message']}"]
    if intent["primary_evidence_ids"]:
        lines.append("**Evidence focus:** " + ", ".join(intent["primary_evidence_ids"]))
    if intent["secondary_evidence_ids"]:
        lines.append("**Supporting evidence:** " + ", ".join(intent["secondary_evidence_ids"]))
    if intent["color_roles"] != ["neutral"]:
        lines.append("**Semantic color roles:** " + ", ".join(intent["color_roles"]))
    motion = intent["motion"]
    if motion["mode"] == "animated":
        lines.append(f"**Motion storyboard ({motion['purpose']}; static renderer fallback):**")
        for state in motion["states"]:
            refs = "; evidence " + ", ".join(state["evidence_ids"]) if state["evidence_ids"] else ""
            lines.append(f"- **{state['label']}** — {state['change']} New information: {state['new_information']}{refs}")
    return lines


def render_markdown(raw: Any) -> tuple[str, dict[str, Any]]:
    plan = validate_plan(raw)
    request = plan["request"]
    findings = _finding_by_id(plan)
    insights = _insight_by_id(plan)
    evidence = {item["id"]: item for item in plan["evidence"]}
    editorial = plan["editorial"]
    appendix_findings = set(editorial["appendix_finding_ids"])
    appendix_insights = set(editorial["appendix_insight_ids"])
    appendix_evidence = set(editorial["appendix_evidence_ids"])
    editorial_active = bool(editorial["decision"] or editorial["materiality_note"] or appendix_findings
                            or appendix_insights or appendix_evidence)
    used_findings: set[str] = set()
    artifact_id = plan["metadata"].get("artifact_id")
    if artifact_id is None:
        canonical = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        artifact_id = "artifact-" + hashlib.sha256(canonical).hexdigest()[:12]
    lines = [f"<!-- Anvil artifact plan v1 | {artifact_id} -->",
             f"# {plan['title']}", "",
             f"**Audience:** {request['audience'].title()}  ",
             f"**Purpose:** {request['purpose']}  ",
             f"**Tone:** {request['tone']}  ",
             f"**Language:** {request['language']}", "",
             "## Thesis", "", plan["thesis"], ""]
    if editorial["decision"]:
        lines.extend(["## Decision context", "", editorial["decision"], ""])
    if editorial["materiality_note"]:
        lines.extend(["## Materiality", "", editorial["materiality_note"], ""])
    metadata = plan["metadata"]
    visible_metadata = [(label, metadata[key]) for key, label in (
        ("artifact_id", "Artifact ID"), ("created_at", "Created"), ("plan_version", "Plan version"),
        ("renderer", "Renderer"), ("theme", "Theme")) if metadata.get(key) is not None]
    if visible_metadata:
        lines.extend(["## Artifact metadata", "", *[f"- **{label}:** {value}" for label, value in visible_metadata], ""])
    if plan["storyline"]:
        lines.extend(["## Storyline", ""])
        for index, step in enumerate(plan["storyline"], 1):
            refs = ", ".join(step["finding_ids"])
            lines.append(f"{index}. **{step['title']}**" + (f" — {refs}" if refs else ""))
            if step.get("rationale"):
                lines.append(f"   - Rationale: {step['rationale']}")
        lines.append("")
    used_insights: set[str] = set()
    if request["artifact"] == "presentation":
        for index, slide in enumerate(plan["slides"], 1):
            lines.extend([f"## Slide {index} — {slide['title']}", "", f"**Role:** {slide['role'].title()}", "", slide["body"]])
            for finding_id in slide["finding_ids"]:
                used_findings.add(finding_id)
                finding = findings[finding_id]
                lines.append(f"\n**Finding {finding_id} — {_epistemic_note(finding['epistemic'], finding['confidence'])}:** {finding['claim']}")
                if finding["implications"]:
                    lines.append("\n**Implication:** " + " ".join(finding["implications"]))
                if finding["limitations"]:
                    lines.append("\n**Qualification:** " + " ".join(finding["limitations"]))
                if finding["materiality"] != "unknown":
                    lines.append("\n**Materiality:** " + finding["materiality"].title())
                if finding["counter_evidence_ids"]:
                    lines.append("\n**Counter-evidence:** " + ", ".join(
                        f"[{ref}](#{ref.casefold()})" for ref in finding["counter_evidence_ids"]))
                if finding["alternative_explanations"]:
                    lines.append("\n**Alternative explanations:** " + " ".join(finding["alternative_explanations"]))
            for insight_id in slide["insight_ids"]:
                insight = insights[insight_id]
                used_insights.add(insight_id)
                lines.append(f"\n**Quantitative evidence {insight_id}:** {format_metric(insight, audience=request['audience'], locale=request['language'])}")
            refs = list(dict.fromkeys([
                *slide["evidence_ids"],
                *(ref for fid in slide["finding_ids"] for ref in [*findings[fid]["evidence_ids"], *findings[fid]["counter_evidence_ids"]]),
                *(ref for iid in slide["insight_ids"] for ref in _insight_evidence_refs(insights[iid])),
            ]))
            if refs:
                lines.append("\n**Evidence:** " + ", ".join(f"[{ref}](#{ref.casefold()})" for ref in refs))
            if slide.get("visual_intent"):
                lines.extend(_visual_note(slide["visual_intent"]))
            lines.append("")
    else:
        for section in plan["sections"]:
            lines.extend([f"## {section['title']}", "", section["body"]])
            for finding_id in section["finding_ids"]:
                used_findings.add(finding_id)
                finding = findings[finding_id]
                lines.append(f"\n**Finding {finding_id} — {_epistemic_note(finding['epistemic'], finding['confidence'])}:** {finding['claim']}")
                if finding["implications"]:
                    lines.append("\n**Implication:** " + " ".join(finding["implications"]))
                if finding["limitations"]:
                    lines.append("\n**Qualification:** " + " ".join(finding["limitations"]))
                if finding["materiality"] != "unknown":
                    lines.append("\n**Materiality:** " + finding["materiality"].title())
                if finding["counter_evidence_ids"]:
                    lines.append("\n**Counter-evidence:** " + ", ".join(
                        f"[{ref}](#{ref.casefold()})" for ref in finding["counter_evidence_ids"]))
                if finding["alternative_explanations"]:
                    lines.append("\n**Alternative explanations:** " + " ".join(finding["alternative_explanations"]))
            for insight_id in section["insight_ids"]:
                insight = insights[insight_id]
                used_insights.add(insight_id)
                lines.append(f"\n**Quantitative evidence {insight_id}:** {format_metric(insight, audience=request['audience'], locale=request['language'])}")
            refs = list(dict.fromkeys([
                *section["evidence_ids"],
                *(ref for fid in section["finding_ids"] for ref in [*findings[fid]["evidence_ids"], *findings[fid]["counter_evidence_ids"]]),
                *(ref for iid in section["insight_ids"] for ref in _insight_evidence_refs(insights[iid])),
            ]))
            if refs:
                lines.append("\n**Evidence:** " + ", ".join(f"[{ref}](#{ref.casefold()})" for ref in refs))
            if section.get("visual_intent"):
                lines.extend(_visual_note(section["visual_intent"]))
            lines.append("")
    main_insight_ids = used_insights if editorial_active else set(insights)
    appendix_findings.update(set(findings) - used_findings if editorial_active else set())
    appendix_insights.update(set(insights) - main_insight_ids if editorial_active else set())
    appendix_findings.difference_update(used_findings)
    appendix_insights.difference_update(main_insight_ids)
    highlight_insight_ids = main_insight_ids - used_insights if editorial_active else main_insight_ids
    if highlight_insight_ids:
        lines.extend(["## Quantitative highlights", ""])
        for insight in plan["quantitative_insights"]:
            if insight["id"] not in highlight_insight_ids:
                continue
            used_insights.add(insight["id"])
            refs = _insight_evidence_refs(insight)
            citations = " — Evidence: " + ", ".join(f"[{ref}](#{ref.casefold()})" for ref in refs) if refs else ""
            lines.append(f"- **{insight['id']}:** {format_metric(insight, audience=request['audience'], locale=request['language'])}{citations}")
            for warning in insight.get("warnings", []):
                lines.append(f"  - Qualification: {warning}")
        lines.append("")
    if appendix_findings or appendix_insights:
        lines.extend(["## Appendix — Supporting analysis", ""])
        for finding_id in sorted(appendix_findings):
            finding = findings[finding_id]
            lines.append(f"### {finding['claim']}")
            lines.append(f"\n**Finding {finding_id} — {_epistemic_note(finding['epistemic'], finding['confidence'])}.**")
            if finding["implications"]:
                lines.append("\n**Implication:** " + " ".join(finding["implications"]))
            if finding["limitations"]:
                lines.append("\n**Qualification:** " + " ".join(finding["limitations"]))
            if finding["materiality"] != "unknown":
                lines.append("\n**Materiality:** " + finding["materiality"].title())
            refs = list(dict.fromkeys([*finding["evidence_ids"], *finding["counter_evidence_ids"]]))
            if refs:
                lines.append("\n**Evidence:** " + ", ".join(f"[{ref}](#{ref.casefold()})" for ref in refs))
            if finding["alternative_explanations"]:
                lines.append("\n**Alternative explanations:** " + " ".join(finding["alternative_explanations"]))
            lines.append("")
        for insight_id in sorted(appendix_insights):
            insight = insights[insight_id]
            used_insights.add(insight_id)
            refs = _insight_evidence_refs(insight)
            citations = " — Evidence: " + ", ".join(f"[{ref}](#{ref.casefold()})" for ref in refs) if refs else ""
            lines.append(f"- **{insight_id}:** {format_metric(insight, audience=request['audience'], locale=request['language'])}{citations}")
        lines.append("")
    if appendix_evidence:
        lines.extend(["## Appendix evidence selection", "", "Supporting evidence retained for technical follow-up: "
                      + ", ".join(sorted(appendix_evidence)) + ".", ""])
    if plan["selection_rationale"] or plan["exclusions"]:
        lines.extend(["## Selection notes", ""])
        for item in plan["selection_rationale"]:
            lines.append(f"- Included: {item}")
        for item in plan["exclusions"]:
            lines.append(f"- Excluded: {item}")
        lines.append("")
    lines.extend(["## Evidence and provenance", ""])
    for evidence in plan["evidence"]:
        source = evidence["source"]
        locator = source.get("locator") or "source not specified"
        digest = source.get("sha256")
        digest_note = f"; SHA-256 `{digest}`" if digest else ""
        disposition = "Appendix evidence" if evidence["id"] in appendix_evidence else "Evidence"
        lines.append(f"<a id=\"{evidence['id'].casefold()}\"></a>")
        safe_locator = locator.replace("`", "\\`")
        lines.append(f"- **{disposition} {evidence['id']} — {_epistemic_note(evidence['epistemic'], evidence['confidence'])}:** "
                     f"{evidence['claim']} — `{safe_locator}`{digest_note}")
        if evidence.get("period"):
            lines.append(f"  - Applies to: {evidence['period']}")
        for assumption in evidence.get("assumptions", []):
            lines.append(f"  - Assumption: {assumption}")
    lines.append("")
    if any(insight.get("projection") for insight in plan["quantitative_insights"]):
        lines.extend(["## Projection qualifications", ""])
        for insight in plan["quantitative_insights"]:
            projection = insight.get("projection")
            if projection:
                lines.append(f"- **{insight['id']}** is a projection based on {projection['basis_period_days']} observed days. "
                             f"Assumption: {projection['assumption']}")
        lines.append("")
    if plan.get("constraint_warnings"):
        lines.extend(["## Planning warnings", "", *[f"- {item}" for item in plan["constraint_warnings"]], ""])
    result = "\n".join(lines).rstrip() + "\n"
    from .editorial import critique_plan
    critic = critique_plan(raw)
    quality = {"structure": "PASS", "constraints": "PASS", "evidence_traceability": "PASS",
               "quantitative_integrity": "PASS", "provenance": "PASS",
               "semantic_claim_review": "PENDING_MODEL", "editorial_review": "PENDING_MODEL",
               "visual_intent": "PASS" if any(page.get("visual_intent") for page in [*plan["slides"], *plan["sections"]]) else "NOT_PROVIDED",
               "output_validity": "PASS"}
    fallbacks = (["Semantic animation storyboard retained as text; no dynamic renderer is installed."]
                 if any(page.get("visual_intent", {}).get("motion", {}).get("mode") == "animated"
                        for page in [*plan["slides"], *plan["sections"]]) else [])
    return result, {"format": "markdown", "artifact": request["artifact"],
                    "slides": len(plan["slides"]) if request["artifact"] == "presentation" else None,
                    "evidence": len(plan["evidence"]), "findings": len(plan["findings"]),
                    "insights": len(plan["quantitative_insights"]), "quality_gates": quality,
                    "warnings": [*plan["constraint_warnings"], *fallbacks], "fallbacks": fallbacks,
                    "editorial_critic": critic}


def write_markdown(raw: Any, destination: Path, *, force: bool = False) -> dict[str, Any]:
    content, result = render_markdown(raw)
    if destination.exists() and not force:
        raise CommunicationError("MATERIALIZATION_FAILED", f"Output already exists: {destination}.",
                                 remediation="Choose a new path or pass --force to replace this file.")
    if destination.is_symlink():
        raise CommunicationError("MATERIALIZATION_FAILED", "Refusing to write an artifact through a symbolic link.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return {**result, "path": str(destination), "bytes": len(content.encode("utf-8")),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
