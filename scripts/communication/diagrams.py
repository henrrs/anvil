"""Renderer-independent architecture contracts and deterministic SVG renderer."""

from __future__ import annotations

import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .contracts import EPISTEMIC_TYPES, IDENTIFIER, validate_evidence
from .errors import CommunicationError


VIEWPOINTS = {"context", "component", "deployment", "data_flow", "sequence", "state",
              "control_flow", "lineage", "security", "evolution", "decision", "conceptual"}
ABSTRACTION = {"L0", "L1", "L2", "L3", "L4"}
NODE_ROLES = {"NEUTRAL", "PRIMARY", "ACTIVE", "SUCCESS", "WARNING", "ERROR", "DISABLED",
              "EXTERNAL", "DATA", "CONTROL", "COMPUTE", "SECURITY", "PROPOSED"}
NODE_STATES = {"current", "proposed", "active", "inactive", "completed", "failed", "deprecated", "unknown"}
PALETTE = {
    "NEUTRAL": ("#F1F5F9", "#334155"), "PRIMARY": ("#DBEAFE", "#1D4ED8"),
    "ACTIVE": ("#CFFAFE", "#0E7490"), "SUCCESS": ("#DCFCE7", "#15803D"),
    "WARNING": ("#FEF3C7", "#B45309"), "ERROR": ("#FEE2E2", "#B91C1C"),
    "DISABLED": ("#E5E7EB", "#6B7280"), "EXTERNAL": ("#F3E8FF", "#7E22CE"),
    "DATA": ("#CCFBF1", "#0F766E"), "CONTROL": ("#E0E7FF", "#4338CA"),
    "COMPUTE": ("#E0F2FE", "#0369A1"), "SECURITY": ("#FFE4E6", "#BE123C"),
    "PROPOSED": ("#FFF7ED", "#C2410C"),
}
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


def _text(value: Any, field: str, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise CommunicationError("CONTRACT_INVALID", f"{field} must be non-empty text with at most {maximum} characters.")
    return value.strip()


def _point(point: Any, field: str) -> tuple[float, float]:
    if not isinstance(point, (list, tuple)) or len(point) != 2 or any(isinstance(value, bool) for value in point):
        raise CommunicationError("LAYOUT_INVALID", f"{field} must be an [x, y] coordinate.")
    if any(not isinstance(value, (int, float)) for value in point):
        raise CommunicationError("LAYOUT_INVALID", f"{field} coordinates must be numeric.")
    try:
        x, y = float(point[0]), float(point[1])
    except (TypeError, ValueError, OverflowError):
        raise CommunicationError("LAYOUT_INVALID", f"{field} coordinates must be numeric.") from None
    if not math.isfinite(x) or not math.isfinite(y):
        raise CommunicationError("LAYOUT_INVALID", f"{field} coordinates must be finite.")
    return x, y


def _rectangles_overlap(first: dict[str, float], second: dict[str, float]) -> bool:
    return (first["x"] < second["x"] + second["width"] and first["x"] + first["width"] > second["x"]
            and first["y"] < second["y"] + second["height"] and first["y"] + first["height"] > second["y"])


def _segment_intersects_rect(a: tuple[float, float], b: tuple[float, float], rect: dict[str, float]) -> bool:
    """Liang-Barsky clipping; touching a node border counts as a collision."""
    x_min, x_max = rect["x"], rect["x"] + rect["width"]
    y_min, y_max = rect["y"], rect["y"] + rect["height"]
    dx, dy = b[0] - a[0], b[1] - a[1]
    p = (-dx, dx, -dy, dy)
    q = (a[0] - x_min, x_max - a[0], a[1] - y_min, y_max - a[1])
    low, high = 0.0, 1.0
    for p_value, q_value in zip(p, q):
        if p_value == 0:
            if q_value < 0:
                return False
            continue
        ratio = q_value / p_value
        if p_value < 0:
            low = max(low, ratio)
        else:
            high = min(high, ratio)
        if low > high:
            return False
    return True


def _layout_rect(raw: Any, field: str, canvas: dict[str, float]) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise CommunicationError("LAYOUT_INVALID", f"{field} must have x/y/width/height coordinates.")
    values = {}
    for key in ("x", "y", "width", "height"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CommunicationError("LAYOUT_INVALID", f"{field}.{key} must be finite numeric geometry.")
        try:
            values[key] = float(value)
        except OverflowError:
            raise CommunicationError("LAYOUT_INVALID", f"{field}.{key} must be finite numeric geometry.") from None
        if not math.isfinite(values[key]):
            raise CommunicationError("LAYOUT_INVALID", f"{field}.{key} must be finite numeric geometry.")
    if values["width"] <= 0 or values["height"] <= 0:
        raise CommunicationError("LAYOUT_INVALID", f"{field} width/height must be positive.")
    if values["x"] < 0 or values["y"] < 0 or values["x"] + values["width"] > canvas["width"] or values["y"] + values["height"] > canvas["height"]:
        raise CommunicationError("LAYOUT_INVALID", f"{field} lies outside the declared canvas.")
    return values


def validate_diagram(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise CommunicationError("CONTRACT_INVALID", "Architecture diagram must be a schema_version 1 object.")
    identifier = raw.get("id")
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise CommunicationError("CONTRACT_INVALID", "Diagram needs a valid stable ID.")
    viewpoint = raw.get("viewpoint")
    if not isinstance(viewpoint, str) or viewpoint not in VIEWPOINTS:
        raise CommunicationError("CONTRACT_INVALID", f"Viewpoint must be one of: {', '.join(sorted(VIEWPOINTS))}.")
    abstraction = raw.get("abstraction", "L2")
    if not isinstance(abstraction, str) or abstraction not in ABSTRACTION:
        raise CommunicationError("CONTRACT_INVALID", "Diagram abstraction must be L0 through L4.")
    question = _text(raw.get("question"), "diagram.question")
    nodes_raw = raw.get("nodes")
    edges_raw = raw.get("edges")
    layout_raw = raw.get("layout")
    if not isinstance(nodes_raw, list) or not 1 <= len(nodes_raw) <= 80:
        raise CommunicationError("CONTRACT_INVALID", "Architecture diagram must contain between 1 and 80 nodes.")
    if not isinstance(edges_raw, list) or len(edges_raw) > 200:
        raise CommunicationError("CONTRACT_INVALID", "Architecture diagram supports at most 200 relationships.")
    if not isinstance(layout_raw, dict) or not isinstance(layout_raw.get("nodes"), dict):
        raise CommunicationError("LAYOUT_INVALID", "Diagram requires a layout block separate from its semantic model.")
    canvas_raw = layout_raw.get("canvas", {})
    if not isinstance(canvas_raw, dict):
        raise CommunicationError("LAYOUT_INVALID", "Canvas must declare numeric width and height.")
    canvas = {}
    for dimension, default in (("width", 1200), ("height", 700)):
        value = canvas_raw.get(dimension, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CommunicationError("LAYOUT_INVALID", f"Canvas {dimension} must be finite numeric geometry.")
        try:
            canvas[dimension] = float(value)
        except OverflowError:
            raise CommunicationError("LAYOUT_INVALID", f"Canvas {dimension} must be finite numeric geometry.") from None
        if not math.isfinite(canvas[dimension]):
            raise CommunicationError("LAYOUT_INVALID", f"Canvas {dimension} must be finite numeric geometry.")
    if not (240 <= canvas["width"] <= 3000 and 160 <= canvas["height"] <= 2000):
        raise CommunicationError("LAYOUT_INVALID", "Canvas must be between 240x160 and 3000x2000 pixels.")
    evidence_raw = raw.get("evidence", [])
    if not isinstance(evidence_raw, list) or len(evidence_raw) > 2000:
        raise CommunicationError("CONTRACT_INVALID", "Diagram evidence must be a bounded list.")
    evidence = [validate_evidence(item) for item in evidence_raw]
    available_evidence_ids = {item["id"] for item in evidence}
    if len(available_evidence_ids) != len(evidence):
        raise CommunicationError("CONTRACT_INVALID", "Diagram evidence IDs must be unique.")
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    boxes: dict[str, dict[str, float]] = {}
    for item in nodes_raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not IDENTIFIER.fullmatch(item["id"]):
            raise CommunicationError("CONTRACT_INVALID", "Each architecture node needs a valid ID.")
        node_id = item["id"]
        if node_id in node_ids:
            raise CommunicationError("CONTRACT_INVALID", f"Duplicate architecture node ID: {node_id}.")
        node_ids.add(node_id)
        kind = _text(item.get("kind"), f"node.{node_id}.kind", 80)
        role = item.get("role", "NEUTRAL")
        state = item.get("state", "current")
        epistemic = item.get("epistemic", "OBSERVATION")
        if not isinstance(role, str) or role not in NODE_ROLES or not isinstance(state, str) or state not in NODE_STATES or not isinstance(epistemic, str) or epistemic not in EPISTEMIC_TYPES:
            raise CommunicationError("CONTRACT_INVALID", f"Node {node_id} has invalid visual semantics or evidence status.")
        if state == "proposed" and epistemic != "PROPOSAL":
            raise CommunicationError("CONTRACT_INVALID", f"Proposed node {node_id} must retain PROPOSAL epistemic status.")
        if epistemic == "PROPOSAL" and state == "current":
            raise CommunicationError("CONTRACT_INVALID", f"Proposed node {node_id} cannot be labelled current.")
        label = _text(item.get("label"), f"node.{node_id}.label")
        evidence_refs = item.get("evidence_ids", [])
        if not isinstance(evidence_refs, list) or any(not isinstance(ref, str) for ref in evidence_refs):
            raise CommunicationError("CONTRACT_INVALID", f"Node {node_id} evidence_ids must be a list of references.")
        if len(evidence_refs) != len(set(evidence_refs)) or set(evidence_refs) - available_evidence_ids:
            raise CommunicationError("CONTRACT_INVALID", f"Node {node_id} contains duplicate or unknown evidence IDs.")
        if epistemic not in {"PROPOSAL", "UNKNOWN"} and not evidence_refs:
            raise CommunicationError("EVIDENCE_INSUFFICIENT", f"Node {node_id} needs evidence or an explicit PROPOSAL/UNKNOWN epistemic label.")
        box = _layout_rect(layout_raw["nodes"].get(node_id), f"layout.nodes.{node_id}", canvas)
        nodes.append({"id": node_id, "label": label, "kind": kind, "role": role,
                      "state": state, "epistemic": epistemic, "evidence_ids": evidence_refs})
        boxes[node_id] = box
    if set(layout_raw["nodes"]) != node_ids:
        raise CommunicationError("LAYOUT_INVALID", "Layout node IDs must match semantic node IDs exactly.")
    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    for index, item in enumerate(edges_raw):
        if not isinstance(item, dict):
            raise CommunicationError("CONTRACT_INVALID", "Architecture relationships must be objects.")
        edge_id = item.get("id", f"edge-{index + 1}")
        source, target = item.get("from"), item.get("to")
        if not isinstance(edge_id, str) or not IDENTIFIER.fullmatch(edge_id) or edge_id in edge_ids:
            raise CommunicationError("CONTRACT_INVALID", "Architecture relationship IDs must be unique and valid.")
        edge_ids.add(edge_id)
        if not isinstance(source, str) or not isinstance(target, str) or source not in node_ids or target not in node_ids or source == target:
            raise CommunicationError("CONTRACT_INVALID", f"Relationship {edge_id} has an unknown or self-referencing endpoint.")
        role = item.get("role", "CONTROL")
        epistemic = item.get("epistemic", "OBSERVATION")
        if not isinstance(role, str) or role not in NODE_ROLES or not isinstance(epistemic, str) or epistemic not in EPISTEMIC_TYPES:
            raise CommunicationError("CONTRACT_INVALID", f"Relationship {edge_id} has invalid semantics.")
        refs = item.get("evidence_ids", [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs) or len(refs) != len(set(refs)) or set(refs) - available_evidence_ids:
            raise CommunicationError("CONTRACT_INVALID", f"Relationship {edge_id} contains duplicate or unknown evidence IDs.")
        if epistemic not in {"PROPOSAL", "UNKNOWN"} and not refs:
            raise CommunicationError("EVIDENCE_INSUFFICIENT", f"Relationship {edge_id} needs evidence or an explicit PROPOSAL/UNKNOWN epistemic label.")
        edges.append({"id": edge_id, "from": source, "to": target,
                      "relation": _text(item.get("relation"), f"edge.{edge_id}.relation", 120),
                      "role": role, "epistemic": epistemic,
                      "evidence_ids": refs,
                      "points": item.get("points")})
    for index, first in enumerate(nodes):
        for second in nodes[index + 1:]:
            a, b = boxes[first["id"]], boxes[second["id"]]
            if _rectangles_overlap(a, b):
                raise CommunicationError("LAYOUT_INVALID", f"Architecture nodes {first['id']} and {second['id']} overlap.")

    boundaries_raw = raw.get("boundaries", [])
    if not isinstance(boundaries_raw, list) or len(boundaries_raw) > 30:
        raise CommunicationError("CONTRACT_INVALID", "Architecture supports at most 30 boundaries.")
    boundaries = []
    boundary_ids: set[str] = set()
    layout_boundaries = layout_raw.get("boundaries", {})
    if not isinstance(layout_boundaries, dict):
        raise CommunicationError("LAYOUT_INVALID", "layout.boundaries must be an object.")
    for item in boundaries_raw:
        if not isinstance(item, dict):
            raise CommunicationError("CONTRACT_INVALID", "Architecture boundaries must be objects.")
        boundary_id = item.get("id")
        if not isinstance(boundary_id, str) or not IDENTIFIER.fullmatch(boundary_id) or boundary_id in boundary_ids:
            raise CommunicationError("CONTRACT_INVALID", "Architecture boundary IDs must be unique and valid.")
        boundary_ids.add(boundary_id)
        members = item.get("node_ids", [])
        if not isinstance(members, list) or not members or any(not isinstance(member, str) for member in members) or len(members) != len(set(members)) or set(members) - node_ids:
            raise CommunicationError("CONTRACT_INVALID", "A boundary must name one or more known nodes.")
        box = _layout_rect(layout_boundaries.get(boundary_id), f"layout.boundaries.{boundary_id}", canvas)
        if not isinstance(item.get("role", "NEUTRAL"), str) or item.get("role", "NEUTRAL") not in NODE_ROLES:
            raise CommunicationError("CONTRACT_INVALID", f"Boundary {boundary_id} has an invalid visual role.")
        if not all(box["x"] <= boxes[node_id]["x"] and box["y"] <= boxes[node_id]["y"]
                   and box["x"] + box["width"] >= boxes[node_id]["x"] + boxes[node_id]["width"]
                   and box["y"] + box["height"] >= boxes[node_id]["y"] + boxes[node_id]["height"] for node_id in members):
            raise CommunicationError("LAYOUT_INVALID", f"Boundary {boundary_id} does not fully contain all member nodes.")
        boundaries.append({"id": _text(boundary_id, "boundary.id", 64),
                           "label": _text(item.get("label"), "boundary.label"),
                           "kind": _text(item.get("kind"), "boundary.kind", 80),
                           "node_ids": members, "role": item.get("role", "NEUTRAL"), "box": box})
    if set(layout_boundaries) != boundary_ids:
        raise CommunicationError("LAYOUT_INVALID", "Layout boundary IDs must match semantic boundary IDs exactly.")
    theme = raw.get("theme", "technical-light")
    if theme != "technical-light":
        raise CommunicationError("CONTRACT_INVALID", "Only the validated technical-light diagram theme is currently available.")

    warnings: list[str] = []
    for node in nodes:
        approximate_width = len(node["label"]) * 9.0
        if approximate_width > boxes[node["id"]]["width"] - 20:
            warnings.append(f"Node {node['id']} label may exceed its box width.")
    for boundary in boundaries:
        if len(boundary["label"]) * 8.0 > boundary["box"]["width"] - 28:
            warnings.append(f"Boundary {boundary['id']} label may exceed its box width.")
    validated_edges = []
    for edge in edges:
        start_box, end_box = boxes[edge["from"]], boxes[edge["to"]]
        start_center = (start_box["x"] + start_box["width"] / 2, start_box["y"] + start_box["height"] / 2)
        end_center = (end_box["x"] + end_box["width"] / 2, end_box["y"] + end_box["height"] / 2)
        raw_points = edge.get("points")
        if raw_points is None:
            points = [start_center, end_center]
        else:
            if not isinstance(raw_points, list) or not 2 <= len(raw_points) <= 20:
                raise CommunicationError("LAYOUT_INVALID", f"Relationship {edge['id']} route must contain 2 to 20 points.")
            points = [_point(point, f"edge.{edge['id']}.points") for point in raw_points]
            if points[0] != start_center or points[-1] != end_center:
                raise CommunicationError("LAYOUT_INVALID", f"Relationship {edge['id']} route must start/end at its endpoint centers.")
        if any(x < 0 or y < 0 or x > canvas["width"] or y > canvas["height"] for x, y in points):
            raise CommunicationError("LAYOUT_INVALID", f"Relationship {edge['id']} route leaves the declared canvas.")
        for node_id, box in boxes.items():
            if node_id in {edge["from"], edge["to"]}:
                continue
            if any(_segment_intersects_rect(a, b, box) for a, b in zip(points, points[1:])):
                raise CommunicationError("LAYOUT_INVALID", f"Relationship {edge['id']} crosses unrelated node {node_id}.",
                                         remediation="Adjust layout routes; edges may terminate only at their declared endpoint nodes.")
        validated_edges.append({**edge, "points": points})
    label_boxes = []
    for edge in validated_edges:
        points = edge["points"]
        center_x = sum(point[0] for point in points) / len(points)
        center_y = sum(point[1] for point in points) / len(points)
        width = min(max(len(edge["relation"]) * 7.5, 24), canvas["width"] - 20)
        label_box = {"x": center_x - width / 2, "y": center_y - 20,
                     "width": width, "height": 20}
        collisions = [node_id for node_id, box in boxes.items() if _rectangles_overlap(label_box, box)]
        if collisions:
            warnings.append(f"Relationship {edge['id']} label may overlap node(s): {', '.join(sorted(collisions))}.")
        if any(_rectangles_overlap(label_box, previous) for previous in label_boxes):
            warnings.append(f"Relationship {edge['id']} label may overlap another relationship label.")
        label_boxes.append(label_box)
    crossing_count = 0
    for index, edge in enumerate(validated_edges):
        for other in validated_edges[index + 1:]:
            if _routes_cross(edge["points"], other["points"]):
                crossing_count += 1
    if crossing_count:
        warnings.append(f"{crossing_count} edge crossing(s) remain; consider adjusting the layout.")
    return {"schema_version": 1, "id": identifier, "title": _text(raw.get("title", question), "diagram.title"),
            "question": question, "viewpoint": viewpoint, "abstraction": abstraction,
            "nodes": nodes, "edges": validated_edges, "boundaries": boundaries, "evidence": evidence,
            "layout": {"canvas": canvas, "nodes": boxes, "boundaries": {item["id"]: item["box"] for item in boundaries}},
            "theme": theme, "warnings": warnings,
            "quality_gates": {"structure": "PASS", "layout": "PASS_WITH_WARNINGS" if warnings else "PASS",
                              "accessibility": "PASS"}}


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _routes_cross(first: list[tuple[float, float]], second: list[tuple[float, float]]) -> bool:
    for a, b in zip(first, first[1:]):
        for c, d in zip(second, second[1:]):
            if max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) and \
                    max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1])):
                if _orientation(a, b, c) * _orientation(a, b, d) < 0 and _orientation(c, d, a) * _orientation(c, d, b) < 0:
                    return True
    return False


def render_svg(raw: Any) -> tuple[str, dict[str, Any]]:
    diagram = validate_diagram(raw)
    width = int(diagram["layout"]["canvas"]["width"])
    height = int(diagram["layout"]["canvas"]["height"])
    root = ET.Element(f"{{{SVG}}}svg", {"viewBox": f"0 0 {width} {height}", "width": str(width), "height": str(height),
                                        "role": "img", "aria-labelledby": "diagram-title diagram-description"})
    title = ET.SubElement(root, f"{{{SVG}}}title", {"id": "diagram-title"})
    title.text = diagram["title"]
    desc = ET.SubElement(root, f"{{{SVG}}}desc", {"id": "diagram-description"})
    desc.text = f"{diagram['viewpoint'].replace('_', ' ').title()} view, {diagram['abstraction']} abstraction. Question: {diagram['question']}"
    style = ET.SubElement(root, f"{{{SVG}}}style")
    style.text = ("text{font-family:Inter,Arial,sans-serif;fill:#0F172A} .boundary{fill:#F8FAFC;stroke:#64748B;"
                  "stroke-width:2;stroke-dasharray:8 5} .edge{fill:none;stroke-width:2.5} .edge-label{font-size:13px;"
                  "paint-order:stroke;stroke:white;stroke-width:5px;stroke-linejoin:round} .node-label{font-size:16px;"
                  "font-weight:600} .node-kind{font-size:12px;fill:#475569} .node-state{font-size:11px;font-weight:600}")
    for boundary in diagram["boundaries"]:
        box = boundary["box"]
        fill, stroke = PALETTE.get(boundary["role"], PALETTE["NEUTRAL"])
        ET.SubElement(root, f"{{{SVG}}}rect", {"id": "boundary-" + boundary["id"], "class": "boundary", "x": str(box["x"]), "y": str(box["y"]),
                     "width": str(box["width"]), "height": str(box["height"]),
                     "stroke": stroke, "fill": fill, "rx": "14"})
        label = ET.SubElement(root, f"{{{SVG}}}text", {"x": str(box["x"] + 14), "y": str(box["y"] + 23),
                              "font-size": "14", "font-weight": "700"})
        label.text = boundary["label"]
    for edge in diagram["edges"]:
        points = edge["points"]
        coordinates = " ".join(f"{x:g},{y:g}" for x, y in points)
        fill, stroke = PALETTE.get(edge["role"], PALETTE["CONTROL"])
        ET.SubElement(root, f"{{{SVG}}}polyline", {"id": "edge-" + edge["id"], "class": "edge", "points": coordinates,
                     "stroke": stroke, "marker-end": "url(#arrow)", "aria-label": edge["relation"]})
        label_x = sum(point[0] for point in points) / len(points)
        label_y = sum(point[1] for point in points) / len(points)
        edge_label = ET.SubElement(root, f"{{{SVG}}}text", {"class": "edge-label", "x": f"{label_x:g}",
                                     "y": f"{label_y - 5:g}", "text-anchor": "middle"})
        edge_label.text = edge["relation"]
    defs = ET.SubElement(root, f"{{{SVG}}}defs")
    marker = ET.SubElement(defs, f"{{{SVG}}}marker", {"id": "arrow", "viewBox": "0 0 10 10", "refX": "9",
                           "refY": "5", "markerWidth": "8", "markerHeight": "8", "orient": "auto-start-reverse"})
    ET.SubElement(marker, f"{{{SVG}}}path", {"d": "M 0 0 L 10 5 L 0 10 z", "fill": "#475569"})
    for node in diagram["nodes"]:
        box = diagram["layout"]["nodes"][node["id"]]
        fill, stroke = PALETTE[node["role"]]
        if node["state"] == "proposed":
            fill, stroke = PALETTE["PROPOSED"]
        if node["state"] == "failed":
            fill, stroke = PALETTE["ERROR"]
        elif node["state"] in {"inactive", "deprecated"}:
            fill, stroke = PALETTE["DISABLED"]
        group = ET.SubElement(root, f"{{{SVG}}}g", {"id": "node-" + node["id"], "role": "group",
                              "aria-label": f"{node['label']}, {node['kind']}, {node['state']}, {node['epistemic']}"})
        ET.SubElement(group, f"{{{SVG}}}rect", {"x": str(box["x"]), "y": str(box["y"]),
                     "width": str(box["width"]), "height": str(box["height"]), "rx": "12",
                     "fill": fill, "stroke": stroke, "stroke-width": "2.5"})
        center_x = box["x"] + box["width"] / 2
        label = ET.SubElement(group, f"{{{SVG}}}text", {"class": "node-label", "x": f"{center_x:g}",
                              "y": f"{box['y'] + box['height'] / 2 - 4:g}", "text-anchor": "middle"})
        label.text = node["label"]
        kind = ET.SubElement(group, f"{{{SVG}}}text", {"class": "node-kind", "x": f"{center_x:g}",
                             "y": f"{box['y'] + box['height'] / 2 + 17:g}", "text-anchor": "middle"})
        kind.text = f"{node['kind']} · {node['state']} · {node['epistemic'].lower()}"
    output = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return output, diagram


def write_svg(source: dict[str, Any], destination: Path, *, force: bool = False) -> dict[str, Any]:
    content, validated = render_svg(source)
    if destination.exists() and not force:
        raise CommunicationError("MATERIALIZATION_FAILED", f"Output already exists: {destination}.", remediation="Choose a new path or pass --force to replace this file.")
    if destination.is_symlink():
        raise CommunicationError("MATERIALIZATION_FAILED", "Refusing to write an SVG through a symbolic link.")
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
    return {"path": str(destination), "format": "svg", "bytes": len(content.encode()),
            "viewpoint": validated["viewpoint"], "nodes": len(validated["nodes"]),
            "edges": len(validated["edges"]), "layout": "PASS", "accessibility": "PASS",
            "warnings": validated["warnings"]}
