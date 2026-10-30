"""Command-line boundary for local communication/artifact contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import inputs
from .diagrams import render_svg, write_svg
from .editorial import critique_plan
from .errors import CommunicationError
from .materialize import render_markdown, write_markdown
from .planning import extract_explicit_constraints, validate_plan
from .quantitative import analyze_payload, format_metric
from .review import review_diagram_file, review_file, review_markdown


def _json(path: Path) -> Any:
    if inputs._has_symlink_component(path.absolute()) or not path.is_file():
        raise CommunicationError("INPUT_UNREADABLE", "Contract input must be an explicitly named regular file.")
    if path.stat().st_size > 5 * 1024 * 1024:
        raise CommunicationError("INPUT_LIMIT_EXCEEDED", "Contract input exceeds the 5 MiB limit.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CommunicationError("INPUT_UNREADABLE", f"Could not read valid UTF-8 JSON from {path.name}.") from None


def _emit(value: Any, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(_human(value))


def _human(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)
    if "sources" in value:
        lines = ["Communication input inventory", "────────────────────────────", f"Sources                {len(value['sources'])}"]
        for item in value["sources"]:
            lines.extend([f"  {item['id']}  {item['type']}  {item['name']}", f"    {item['path']}",
                          f"    {item['size_bytes']} bytes; SHA-256 {item['sha256']}"])
        for item in value.get("ignored", []):
            lines.append(f"Ignored                 {item['path']} ({item['reason']})")
        lines.append("Content                 not read; use extract on relevant sources")
        return "\n".join(lines)
    if "content" in value and "source" in value:
        header = f"Source {value['source']['id']} — {value['source']['path']} (SHA-256 {value['source']['sha256']})"
        note = "\n".join(f"NOTE: {item}" for item in value["notes"])
        return "\n".join(part for part in (header, note, value["content"]) if part)
    if "quantitative_insights" in value:
        lines = ["Quantitative analysis", "────────────────────"]
        for item in value["quantitative_insights"]:
            lines.append(f"{item['id']}  {format_metric(item, audience='technical')}")
            for warning in item.get("warnings", []):
                lines.append(f"  WARN {warning}")
        for item in value.get("distributions", []):
            stats = item.get("statistics") or {}
            lines.append(f"{item['id']}  count={item['count']} median={stats.get('median', 'unknown')} {item['unit']} p95={stats.get('p95', 'unknown')} {item['unit']}")
            if item.get("outliers"):
                lines.append(f"  Outliers retained      {len(item['outliers'])} value(s), method={item['outlier_method']}")
        return "\n".join(lines)
    if "quality_gates" in value and "findings" in value:
        lines = [f"Review status           {value['status']}", "Quality gates"]
        lines.extend(f"  {key.replace('_', ' ').title():<24}{status}" for key, status in value["quality_gates"].items())
        for item in value["findings"]:
            place = f" [{item['location']}]" if item.get("location") else ""
            lines.append(f"{item['severity'].upper():<8}{item['code']}{place}: {item['message']}")
            if item.get("remediation"):
                lines.append(f"         Next: {item['remediation']}")
        if not value["findings"]:
            lines.append("No deterministic issues found.")
        critic = value.get("editorial_critic")
        if critic:
            lines.append(f"Editorial review        {critic['status']}")
            lines.extend(f"  Signal {item['code']} [{', '.join(item['locations'])}]: {item['message']}"
                         for item in critic["candidate_signals"])
        return "\n".join(lines)
    if "candidate_signals" in value and "dimensions" in value:
        lines = [f"Editorial critique      {value['status']}",
                 f"Audience                {value['audience_profile']['audience']}",
                 f"Visual intent coverage  {value['visual_intent_coverage']['modeled_pages']}/"
                 f"{value['visual_intent_coverage']['total_pages']} pages"]
        lines.extend(f"{key.replace('_', ' ').title():<24}{status}" for key, status in value["dimensions"].items())
        lines.extend(f"SIGNAL {item['code']} [{', '.join(item['locations'])}]: {item['message']}\n"
                     f"       Review: {item['remediation']}" for item in value["candidate_signals"])
        lines.append(value["limits"])
        return "\n".join(lines)
    if "communication_budget" in value:
        budget = value["communication_budget"]
        lines = ["Artifact plan validation", "──────────────────────", "Structure              PASS",
                 "Constraints            PASS", f"Audience               {budget['audience']}",
                 f"Primary messages       {budget['primary_message_count']}",
                 f"Words/message          {budget['recommended_words_per_primary_message']}"]
        lines.extend(f"WARN                   {warning}" for warning in value.get("constraint_warnings", []))
        lines.append("Human/model semantic review is still required before treating the plan as approved.")
        return "\n".join(lines)
    return json.dumps(value, ensure_ascii=False, indent=2)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Anvil Communication & Artifact Intelligence local core")
    actions = root.add_subparsers(dest="action", required=True)

    inventory = actions.add_parser("discover", help="Inventory explicitly named inputs without returning their content")
    inventory.add_argument("sources", nargs="+")
    inventory.add_argument("--recursive", action="store_true", help="Recursively inspect named directories; default is one directory level")
    inventory.add_argument("--max-files", type=int, default=inputs.MAX_FILES)
    inventory.add_argument("--format", choices=("text", "json"), default="text")

    extract = actions.add_parser("extract", help="Extract bounded text from one explicitly named source")
    extract.add_argument("source")
    extract.add_argument("--start-line", type=int)
    extract.add_argument("--end-line", type=int)
    extract.add_argument("--max-bytes", type=int, default=inputs.MAX_EXTRACTED_BYTES)
    extract.add_argument("--format", choices=("text", "json"), default="text")

    quantify = actions.add_parser("quantify", help="Compute deterministic deltas and distribution summaries from JSON")
    quantify.add_argument("input", type=Path)
    quantify.add_argument("--format", choices=("text", "json"), default="text")

    constraints = actions.add_parser("constraints", help="Validate a plan and return effective constraints/budget")
    constraints.add_argument("plan", type=Path)
    constraints.add_argument("--prompt", help="Optional original request; detects exact counts and measured-only wording")
    constraints.add_argument("--format", choices=("text", "json"), default="text")

    critique = actions.add_parser("critique", help="Surface bounded editorial and visual review signals for a plan")
    critique.add_argument("plan", type=Path)
    critique.add_argument("--format", choices=("text", "json"), default="text")

    materialize = actions.add_parser("materialize", help="Validate and write a human-readable Markdown report or slide outline")
    materialize.add_argument("plan", type=Path)
    materialize.add_argument("--output", required=True, type=Path)
    materialize.add_argument("--force", action="store_true")
    materialize.add_argument("--format", choices=("text", "json"), default="text")

    diagram = actions.add_parser("diagram", help="Validate an architecture model and render accessible SVG")
    diagram.add_argument("model", type=Path)
    diagram.add_argument("--output", required=True, type=Path)
    diagram.add_argument("--force", action="store_true")
    diagram.add_argument("--format", choices=("text", "json"), default="text")

    review = actions.add_parser("review", help="Run deterministic Markdown artifact checks")
    review.add_argument("artifact", type=Path)
    review.add_argument("--plan", type=Path)
    review.add_argument("--format", choices=("text", "json"), default="text")

    diagram_review = actions.add_parser("review-diagram", help="Validate rendered SVG and optionally compare its semantic model")
    diagram_review.add_argument("artifact", type=Path)
    diagram_review.add_argument("--model", type=Path)
    diagram_review.add_argument("--format", choices=("text", "json"), default="text")

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "discover":
            _emit(inputs.discover(args.sources, recursive=args.recursive, max_files=args.max_files), args.format)
            return 0
        if args.action == "extract":
            _emit(inputs.extract(args.source, start_line=args.start_line, end_line=args.end_line,
                                 max_bytes=args.max_bytes), args.format)
            return 0
        if args.action == "quantify":
            result = analyze_payload(_json(args.input))
            _emit(result, args.format)
            return 0
        if args.action == "constraints":
            plan = _json(args.plan)
            if args.prompt:
                existing = plan.get("request", {}).get("constraints", [])
                plan.setdefault("request", {})["constraints"] = [*existing, *extract_explicit_constraints(args.prompt)]
            result = validate_plan(plan)
            _emit(result, args.format)
            return 0
        if args.action == "critique":
            result = critique_plan(_json(args.plan))
            _emit(result, args.format)
            return 0
        if args.action == "materialize":
            if args.output.suffix.casefold() not in {".md", ".markdown"}:
                raise CommunicationError("RENDERER_UNAVAILABLE", f"No binary renderer is available for {args.output.suffix or 'this output type'}.",
                                         remediation="Materialize to Markdown; the request and plan remain reusable for a future renderer.")
            result = write_markdown(_json(args.plan), args.output, force=args.force)
            _emit(result, args.format)
            return 0
        if args.action == "diagram":
            if args.output.suffix.casefold() != ".svg":
                raise CommunicationError("RENDERER_UNAVAILABLE", "The semantic architecture renderer currently produces SVG.",
                                         remediation="Choose an .svg output path.")
            result = write_svg(_json(args.model), args.output, force=args.force)
            _emit(result, args.format)
            return 0
        if args.action == "review":
            result = review_file(args.artifact, plan_path=args.plan)
            _emit(result, args.format)
            return 1 if result["status"] == "FAIL" else 0
        if args.action == "review-diagram":
            model = _json(args.model) if args.model else None
            result = review_diagram_file(args.artifact, model)
            _emit(result, args.format)
            return 1 if result["status"] == "FAIL" else 0
    except CommunicationError as exc:
        print(f"BLOCKED {exc.code}: {exc}", file=sys.stderr)
        if exc.remediation:
            print(f"Next step: {exc.remediation}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"BLOCKED INPUT_UNREADABLE: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 2
