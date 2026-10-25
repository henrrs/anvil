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


def render_markdown(raw: Any) -> tuple[str, dict[str, Any]]:
    plan = validate_plan(raw)
    request = plan["request"]
    findings = _finding_by_id(plan)
    insights = _insight_by_id(plan)
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
                finding = findings[finding_id]
                lines.append(f"\n**Finding {finding_id} — {_epistemic_note(finding['epistemic'], finding['confidence'])}:** {finding['claim']}")
            for insight_id in slide["insight_ids"]:
                insight = insights[insight_id]
                used_insights.add(insight_id)
                lines.append(f"\n**Quantitative evidence {insight_id}:** {format_metric(insight, audience=request['audience'], locale=request['language'])}")
            refs = list(dict.fromkeys([
                *slide["evidence_ids"],
                *(ref for fid in slide["finding_ids"] for ref in findings[fid]["evidence_ids"]),
                *(ref for iid in slide["insight_ids"] for ref in _insight_evidence_refs(insights[iid])),
            ]))
            if refs:
                lines.append("\n**Evidence:** " + ", ".join(f"[{ref}](#{ref.casefold()})" for ref in refs))
            lines.append("")
    else:
        for section in plan["sections"]:
            lines.extend([f"## {section['title']}", "", section["body"]])
            for finding_id in section["finding_ids"]:
                finding = findings[finding_id]
                lines.append(f"\n**Finding {finding_id} — {_epistemic_note(finding['epistemic'], finding['confidence'])}:** {finding['claim']}")
            for insight_id in section["insight_ids"]:
                insight = insights[insight_id]
                used_insights.add(insight_id)
                lines.append(f"\n**Quantitative evidence {insight_id}:** {format_metric(insight, audience=request['audience'], locale=request['language'])}")
            refs = list(dict.fromkeys([
                *section["evidence_ids"],
                *(ref for fid in section["finding_ids"] for ref in findings[fid]["evidence_ids"]),
                *(ref for iid in section["insight_ids"] for ref in _insight_evidence_refs(insights[iid])),
            ]))
            if refs:
                lines.append("\n**Evidence:** " + ", ".join(f"[{ref}](#{ref.casefold()})" for ref in refs))
            lines.append("")
    if plan["quantitative_insights"]:
        lines.extend(["## Quantitative highlights", ""])
        for insight in plan["quantitative_insights"]:
            used_insights.add(insight["id"])
            refs = _insight_evidence_refs(insight)
            citations = " — Evidence: " + ", ".join(f"[{ref}](#{ref.casefold()})" for ref in refs) if refs else ""
            lines.append(f"- **{insight['id']}:** {format_metric(insight, audience=request['audience'], locale=request['language'])}{citations}")
            for warning in insight.get("warnings", []):
                lines.append(f"  - Qualification: {warning}")
        lines.append("")
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
        lines.append(f"<a id=\"{evidence['id'].casefold()}\"></a>")
        safe_locator = locator.replace("`", "\\`")
        lines.append(f"- **{evidence['id']} — {_epistemic_note(evidence['epistemic'], evidence['confidence'])}:** "
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
    quality = {"structure": "PASS", "constraints": "PASS", "evidence_traceability": "PASS",
               "quantitative_integrity": "PASS", "provenance": "PASS",
               "semantic_claim_review": "PENDING_MODEL", "output_validity": "PASS"}
    return result, {"format": "markdown", "artifact": request["artifact"],
                    "slides": len(plan["slides"]) if request["artifact"] == "presentation" else None,
                    "evidence": len(plan["evidence"]), "findings": len(plan["findings"]),
                    "insights": len(plan["quantitative_insights"]), "quality_gates": quality,
                    "warnings": plan["constraint_warnings"]}


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
