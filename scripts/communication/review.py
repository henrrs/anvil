"""Deterministic artifact checks. Semantic review remains the agent's job."""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .errors import CommunicationError
from .planning import validate_plan
from .quantitative import format_number


GENERIC_TITLES = {
    "current architecture", "cost analysis", "benefits", "next steps", "overview",
    "performance analysis", "solution", "results", "conclusion", "architecture",
}
GENERIC_FILLER = (
    "in an increasingly dynamic scenario", "digital transformation has become",
    "it is important to highlight", "in this context", "robust, scalable and efficient",
)
CLAIM_VERBS = {"is", "are", "drives", "reduces", "increases", "requires", "accounts", "shows",
               "remains", "moves", "causes", "represents", "falls", "grew", "improved", "declined",
               "é", "são", "reduz", "aumenta", "exige", "representa", "concentra", "caiu", "cresceu",
               "melhorou", "piorou", "permanece", "depende", "impulsiona"}


def _finding(severity: str, code: str, message: str, location: str | None = None,
             remediation: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if location:
        result["location"] = location
    if remediation:
        result["remediation"] = remediation
    return result


def _assertion_title(title: str) -> bool:
    words = set(re.findall(r"(?u)[\w'-]+", title.casefold()))
    return bool(words & CLAIM_VERBS) or any(token in title for token in ("→", ":", "—", "because", "while"))


def review_markdown(text: str, *, plan_raw: Any | None = None,
                    artifact_path: str | None = None) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    plan = None
    if plan_raw is not None:
        try:
            plan = validate_plan(plan_raw)
        except CommunicationError as exc:
            findings.append(_finding("error", exc.code, str(exc), "artifact plan", exc.remediation))
    if not text.strip():
        findings.append(_finding("error", "OUTPUT_INVALID", "Artifact is empty.", artifact_path,
                                 "Add the approved thesis and materialized sections."))
    if len(text.encode("utf-8")) > 5 * 1024 * 1024:
        findings.append(_finding("error", "OUTPUT_LIMIT_EXCEEDED", "Artifact exceeds the 5 MiB review limit.", artifact_path))
        return {"schema_version": 1, "status": "FAIL", "quality_gates": {"structure": "FAIL"}, "findings": findings}
    if re.search(r"(?m)^\s*```(?:json)?\s*$", text) and '"schema_version"' in text:
        findings.append(_finding("error", "INTERNAL_SCHEMA_DUMP", "Artifact contains an internal JSON schema dump.", artifact_path,
                                 "Render the semantic content for people instead of embedding the plan contract."))
    for marker in ("TODO", "TBD", "[INSERT", "<PLACEHOLDER>"):
        if marker.casefold() in text.casefold():
            findings.append(_finding("warning", "PLACEHOLDER", f"Artifact still contains {marker}.", artifact_path))
    for phrase in GENERIC_FILLER:
        if phrase in text.casefold():
            findings.append(_finding("warning", "GENERIC_FILLER", f"Generic low-information phrase found: {phrase}.", artifact_path,
                                     "Replace it with a concrete evidence-backed claim or remove it."))
    headings = re.findall(r"(?m)^## Slide\s+(\d+)\s+[—-]\s+(.+?)\s*$", text)
    if headings:
        numbers = [int(item[0]) for item in headings]
        if numbers != list(range(1, len(numbers) + 1)):
            findings.append(_finding("error", "SLIDE_SEQUENCE_INVALID", "Slide headings must be numbered sequentially from one.", artifact_path))
        for number, title in headings:
            if title.strip().casefold() in GENERIC_TITLES:
                findings.append(_finding("warning", "GENERIC_TITLE", f"Slide {number} uses a label instead of an argument title: {title.strip()}.",
                                         f"slide {number}", "Rewrite the title as the message the audience should remember."))
            elif not _assertion_title(title):
                findings.append(_finding("warning", "TITLE_NOT_ASSERTION", f"Slide {number} title may label a topic rather than advance the argument.",
                                         f"slide {number}", "Check whether reading only the titles communicates the storyline."))
        exact = None
        if plan is not None:
            exact_constraint = next((item for item in plan["request"]["constraints"] if item["kind"] == "exact_slides"), None)
            exact = exact_constraint.get("value") if exact_constraint else None
        if exact is not None and len(headings) != exact:
            findings.append(_finding("error", "EXACT_SLIDE_COUNT", f"Artifact has {len(headings)} slides; hard constraint requires {exact}.",
                                     artifact_path, "Rematerialize from the validated plan without adding or removing slides."))
        lines = text.splitlines()
        for index, (number, _) in enumerate(headings):
            start = next((position for position, line in enumerate(lines) if re.match(rf"## Slide\s+{number}\s+[—-]", line)), 0)
            end = next((position for position in range(start + 1, len(lines)) if lines[position].startswith("## Slide ")), len(lines))
            word_count = len(" ".join(lines[start + 1:end]).split())
            if word_count > 120:
                findings.append(_finding("warning", "SLIDE_DENSITY", f"Slide {number} has about {word_count} words.",
                                         f"slide {number}", "Move supporting detail to notes, appendix, or a linked technical document."))

    if plan is not None:
            evidence_ids = {item["id"] for item in plan["evidence"]}
            finding_ids = {item["id"] for item in plan["findings"]}
            for item in plan["findings"]:
                if item["epistemic"] not in {"PROPOSAL", "UNKNOWN"} and not set(item["evidence_ids"]) <= evidence_ids:
                    findings.append(_finding("error", "EVIDENCE_REFERENCE_INVALID", f"Finding {item['id']} has unresolved evidence.", item["id"]))
            for reference in re.findall(r"\[([A-Z][A-Z0-9_.:-]{0,63})\]\(#([a-z][a-z0-9_.:-]{0,63})\)", text):
                evidence_id, anchor = reference
                if evidence_id not in evidence_ids or anchor != evidence_id.casefold():
                    findings.append(_finding("error", "PROVENANCE_LINK_INVALID", f"Evidence link {evidence_id} has no matching source anchor.", artifact_path))
            for evidence in plan["evidence"]:
                if evidence["id"].casefold() not in text.casefold():
                    findings.append(_finding("warning", "PROVENANCE_NOT_RENDERED", f"Evidence {evidence['id']} is in the plan but not visible in the artifact.", artifact_path))
            used_projection = False
            for insight in plan["quantitative_insights"]:
                pp = insight.get("percentage_point_change")
                if pp is not None:
                    numbers = {format_number(pp, locale=plan["request"]["language"], decimals=precision)
                               for precision in (0, 1, 2)}
                    for number in numbers:
                        pattern = re.compile(re.escape(number) + r"\s*%", re.IGNORECASE)
                        for match in pattern.finditer(text):
                            context = text[max(0, match.start() - 80):match.end() + 80].casefold()
                            correctly_labeled = ("percentage point" in context or re.search(r"\bpp\b", context)
                                                 or "relative" in context or "relativo" in context)
                            if not correctly_labeled:
                                findings.append(_finding("error", "PERCENTAGE_POINT_MISLABELLED",
                                    f"Rate delta {number} is presented with a percent sign but not identified as percentage points.",
                                    artifact_path, "Label this delta in percentage points; keep relative percent change separate."))
                projection = insight.get("projection")
                if projection:
                    projection_worded = bool(re.search(r"\b(?:projection|projected|annualized|annualised|projection|projeção|projetado|anualizado)\b", text, re.IGNORECASE))
                    assumption_present = projection["assumption"].casefold() in text.casefold()
                    if not projection_worded or not assumption_present:
                        findings.append(_finding("error", "PROJECTION_UNQUALIFIED", f"Projection {insight['id']} lacks a visible projection label or persistence assumption.",
                                                 artifact_path, "Qualify the value as a projection and preserve the explicit assumption."))
                    used_projection = True
            if plan["request"]["artifact"] == "presentation" and len(headings) != len(plan["slides"]):
                findings.append(_finding("error", "SLIDE_COUNT_MISMATCH", f"Rendered artifact contains {len(headings)} slide headings but plan contains {len(plan['slides'])}.", artifact_path))
            if used_projection and "projection qualifications" not in text.casefold() and "annualized projection" not in text.casefold() and "annualised projection" not in text.casefold():
                findings.append(_finding("warning", "PROJECTION_NOTE_MISSING", "Artifact has no dedicated projection qualification note.", artifact_path))

    findings.append(_finding("warning", "SEMANTIC_REVIEW_PENDING",
                             "Deterministic checks do not establish factual truth, source relevance, or argument quality.",
                             artifact_path, "Read the artifact and source evidence for semantic accuracy and audience fit."))

    errors = sum(item["severity"] == "error" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    status = "FAIL" if errors else "PASS_WITH_WARNINGS" if warnings else "PASS"
    gates = {"structure": "FAIL" if errors else "PASS",
             "constraints": "FAIL" if any(item["code"] in {"EXACT_SLIDE_COUNT", "SLIDE_COUNT_MISMATCH"} for item in findings) else "PASS",
             "evidence": "FAIL" if any(item["code"] in {"EVIDENCE_REFERENCE_INVALID", "PROVENANCE_LINK_INVALID"} for item in findings) else "PASS",
             "quantitative_integrity": "FAIL" if any(item["code"] in {"PERCENTAGE_POINT_MISLABELLED", "PROJECTION_UNQUALIFIED"} for item in findings) else "PASS",
             "layout": "NOT_APPLICABLE", "accessibility": "NOT_APPLICABLE",
             "narrative": "WARN" if any(item["code"] in {"GENERIC_TITLE", "TITLE_NOT_ASSERTION", "GENERIC_FILLER", "SLIDE_DENSITY"} for item in findings) else "PASS",
             "semantic_claim_review": "PENDING_MODEL",
             "output_validity": "PASS" if status != "FAIL" else "FAIL"}
    return {"schema_version": 1, "status": status, "quality_gates": gates,
            "counts": {"errors": errors, "warnings": warnings}, "findings": findings}


def review_diagram_file(path: Path, model: Any | None = None) -> dict[str, Any]:
    from .inputs import _has_symlink_component
    if _has_symlink_component(path.absolute()) or not path.is_file():
        raise CommunicationError("INPUT_UNREADABLE", "Diagram review requires an explicitly named regular file.")
    if path.stat().st_size > 5 * 1024 * 1024:
        raise CommunicationError("INPUT_LIMIT_EXCEEDED", "Diagram exceeds the 5 MiB review limit.")
    try:
        raw = path.read_bytes()
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise CommunicationError("OUTPUT_VALIDATION_FAILED", "SVG document types and custom entities are not accepted.")
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise CommunicationError("OUTPUT_VALIDATION_FAILED", "SVG is not valid XML.") from None
    if not root.tag.endswith("svg") or not root.get("viewBox"):
        raise CommunicationError("OUTPUT_VALIDATION_FAILED", "SVG root or viewBox is missing.")
    try:
        viewbox = [float(item) for item in re.split(r"[\s,]+", root.get("viewBox", "").strip())]
    except ValueError:
        viewbox = []
    if len(viewbox) != 4 or any(not math.isfinite(value) for value in viewbox) or viewbox[2] <= 0 or viewbox[3] <= 0:
        raise CommunicationError("OUTPUT_VALIDATION_FAILED", "SVG viewBox must contain four finite values with positive width and height.")
    if root.get("role") != "img" or not any(item.tag.endswith("title") for item in root) or not any(item.tag.endswith("desc") for item in root):
        raise CommunicationError("OUTPUT_VALIDATION_FAILED", "SVG needs an accessible image role, title, and description.")
    for item in root.iter():
        if not isinstance(item.tag, str):
            continue
        tag = item.tag.rsplit("}", 1)[-1].casefold()
        if tag in {"script", "foreignobject", "iframe", "object", "embed"}:
            raise CommunicationError("OUTPUT_VALIDATION_FAILED", f"SVG contains active or embedded content: {tag}.")
        for name, value in item.attrib.items():
            local = name.rsplit("}", 1)[-1].casefold()
            if local.startswith("on") or (local in {"href", "src"} and re.match(r"\s*(?:https?:|file:|javascript:|data:)", value, re.IGNORECASE)):
                raise CommunicationError("OUTPUT_VALIDATION_FAILED", "SVG contains an active event or external resource reference.")
        if tag in {"animate", "animatetransform", "animatemotion", "set"}:
            raise CommunicationError("OUTPUT_VALIDATION_FAILED", "Dynamic SVG animation is outside the supported static renderer.")
        if tag == "style" and re.search(r"@import|url\s*\(\s*(?!#)", item.text or "", re.IGNORECASE):
            raise CommunicationError("OUTPUT_VALIDATION_FAILED", "SVG stylesheet contains a remote or external resource reference.")
    if model is not None:
        from .diagrams import render_svg
        _, validation = render_svg(model)
        node_groups = {item.get("id", "").removeprefix("node-"): item for item in root.iter()
                       if item.tag.endswith("g") and item.get("id", "").startswith("node-")}
        svg_nodes = set(node_groups)
        expected = {item["id"] for item in validation["nodes"]}
        if svg_nodes != expected:
            raise CommunicationError("OUTPUT_VALIDATION_FAILED", "Rendered SVG node identities do not match the semantic diagram model.")
        for node in validation["nodes"]:
            group = node_groups[node["id"]]
            text = "".join(group.itertext())
            if node["label"] not in text or not group.get("aria-label", "").startswith(node["label"] + ","):
                raise CommunicationError("OUTPUT_VALIDATION_FAILED", f"Rendered SVG node {node['id']} label or accessible description differs from its model.")
        svg_edges = {item.get("id", "").removeprefix("edge-"): item for item in root.iter()
                     if item.tag.endswith("polyline") and item.get("id", "").startswith("edge-")}
        if set(svg_edges) != {item["id"] for item in validation["edges"]}:
            raise CommunicationError("OUTPUT_VALIDATION_FAILED", "Rendered SVG relationships do not match the semantic diagram model.")
        for edge in validation["edges"]:
            if svg_edges[edge["id"]].get("aria-label") != edge["relation"]:
                raise CommunicationError("OUTPUT_VALIDATION_FAILED", f"Rendered SVG relationship {edge['id']} label differs from its model.")
        svg_boundaries = {item.get("id", "").removeprefix("boundary-") for item in root.iter()
                          if item.tag.endswith("rect") and item.get("id", "").startswith("boundary-")}
        if svg_boundaries != {item["id"] for item in validation["boundaries"]}:
            raise CommunicationError("OUTPUT_VALIDATION_FAILED", "Rendered SVG boundaries do not match the semantic diagram model.")
        findings = [_finding("warning", "SEMANTIC_REVIEW_PENDING",
                             "Diagram evidence and layout contracts validate, but architectural truth needs semantic review.",
                             str(path))]
        findings.extend(_finding("warning", "LAYOUT_WARNING", warning, str(path)) for warning in validation["warnings"])
        status = "PASS_WITH_WARNINGS" if findings else "PASS"
        return {"schema_version": 1, "status": status, "quality_gates": {
                    **validation["quality_gates"], "semantic_claim_review": "PENDING_MODEL"},
                "findings": findings, "nodes": len(svg_nodes), "viewBox": root.get("viewBox")}
    return {"schema_version": 1, "status": "PASS_WITH_WARNINGS", "quality_gates": {"output_validity": "PASS",
            "layout": "NOT_VERIFIED_WITHOUT_MODEL", "accessibility": "NOT_VERIFIED_WITHOUT_MODEL",
            "semantic_claim_review": "PENDING_MODEL"},
            "findings": [_finding("warning", "SEMANTIC_MODEL_NOT_PROVIDED", "SVG parses, but layout and semantic color checks need its architecture model.", str(path))],
            "viewBox": root.get("viewBox")}


def review_file(path: Path, *, plan_path: Path | None = None) -> dict[str, Any]:
    from .inputs import _has_symlink_component
    if _has_symlink_component(path.absolute()) or not path.is_file():
        raise CommunicationError("INPUT_UNREADABLE", "Review requires an explicitly named regular file.")
    if path.stat().st_size > 5 * 1024 * 1024:
        raise CommunicationError("INPUT_LIMIT_EXCEEDED", "Artifact exceeds the 5 MiB review limit.")
    if path.suffix.casefold() == ".svg":
        return review_diagram_file(path)
    if path.suffix.casefold() not in {".md", ".markdown", ".txt"}:
        raise CommunicationError("INPUT_FORMAT_UNSUPPORTED", f"No deterministic reviewer is available for {path.suffix or 'this file type'}.",
                                 remediation="Review Markdown artifacts or add a validated format adapter; semantic review can still use the communication skill.")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise CommunicationError("INPUT_UNREADABLE", f"Could not read artifact {path.name} as UTF-8 text.") from None
    plan = None
    if plan_path:
        if _has_symlink_component(plan_path.absolute()) or not plan_path.is_file():
            raise CommunicationError("INPUT_UNREADABLE", "Review plan must be an explicitly named regular file.")
        if plan_path.stat().st_size > 5 * 1024 * 1024:
            raise CommunicationError("INPUT_LIMIT_EXCEEDED", "Review plan exceeds the 5 MiB limit.")
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise CommunicationError("INPUT_UNREADABLE", "Review plan must be valid UTF-8 JSON.") from None
    return review_markdown(text, plan_raw=plan, artifact_path=str(path))
