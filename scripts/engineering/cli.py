"""A small explicit engineering-state interface for both OpenCode generations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import context, engine, specification, store
from .contracts import require
from .errors import EngineeringError
from .repository import no_symlinks


def read_json(path: Path) -> dict:
    no_symlinks(path)
    require(path.is_file() and path.stat().st_size <= 2 * 1024 * 1024, "Models/signals must be a named JSON file up to 2 MiB.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise EngineeringError("SPECIFICATION_INVALID", "Could not read the supplied JSON models.") from None
    require(isinstance(value, dict), "Expected a JSON object.")
    return value


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="action", required=True)
    assess = commands.add_parser("assess", help="Assess supplied scope signals without creating state")
    assess.add_argument("--request", type=Path, required=True)
    assess.add_argument("--signals", type=Path)
    analyze = commands.add_parser("analyze", help="Inventory one specification before semantic normalization")
    analyze.add_argument("--spec", type=Path, required=True)
    for action in ("init", "status", "resume", "start", "implement", "check", "review", "checkpoint", "revalidate", "reconcile", "replan", "complete", "archive", "recover", "list"):
        cmd = commands.add_parser(action)
        cmd.add_argument("--repository", type=Path, default=Path.cwd())
        if action != "list":
            cmd.add_argument("--id", required=True, help="Explicit project-scoped engineering task ID")
        if action not in {"init", "status", "resume", "list"}:
            cmd.add_argument("--revision", type=int, required=True, help="Expected revision; stale writes are rejected")
        if action in {"init", "replan"}:
            cmd.add_argument("--models", type=Path, required=True)
            cmd.add_argument("--spec", type=Path, required=True)
        if action == "replan":
            cmd.add_argument("--scope-authorization", default="", help="Reference to actual user authorization when reducing required scope")
        if action in {"start", "implement", "check", "reconcile", "resume"}:
            cmd.add_argument("--task", required=action != "resume")
        if action == "implement":
            cmd.add_argument("--files", nargs="+", required=True)
        if action == "check":
            cmd.add_argument("--check", required=True)
            cmd.add_argument("--hypothesis", default="")
        if action == "review":
            cmd.add_argument("--target", required=True, help="Declared semantic check or invariant ID")
            cmd.add_argument("--result", choices=("PASS", "FAIL", "UNKNOWN"), required=True)
            cmd.add_argument("--summary", required=True)
            cmd.add_argument("--observer", choices=("human", "model"), required=True)
        if action in {"revalidate", "reconcile", "replan", "archive"}:
            cmd.add_argument("--reason", required=True)
        if action == "reconcile":
            cmd.add_argument("--outcome", choices=("PENDING", "IMPLEMENTED", "BLOCKED"), required=True)
    for cmd in commands.choices.values():
        cmd.add_argument("--format", choices=("text", "json"), default="text")
    return root


def human(value: dict) -> str:
    if "objective" not in value:
        if "workflow" in value:
            return f"Workflow              {value['workflow']}\nSignals               {', '.join(value['signals']) or 'small/direct scope'}\nState created         NO\n{value['note']}"
        if "source" in value:
            return f"Specification         {value['source']['path']}\nLines                 {value['lines']}\nStatus                {value['status']}\nNext                  {value['next']}"
        return json.dumps(value, ensure_ascii=False, indent=2)
    lines = ["Anvil Engineering", "─────────────────", f"Task                  {value['id']}", f"Revision              {value['revision']}",
             f"Status                {value['status']}", f"Objective             {value['objective']}"]
    if value.get("current_task"):
        lines.append(f"Current unit          {value['current_task']['id']} — {value['current_task']['title']}")
    lines.append("Requirements          " + "; ".join(f"{k}={v}" for k, v in value["coverage"]["counts"].items() if v))
    lines.append("Architecture          " + ("; ".join(f"{k}={v}" for k, v in value["architecture_conformance"].items()) or "No explicit invariants"))
    for item in value.get("architecture_findings", []):
        lines.extend(f"  {item['id']} {item['result']}: {finding}" for finding in item["findings"])
    if value.get("last_check"):
        check = value["last_check"]
        lines.append(f"Verification          {check['result']} {check.get('check_id', '')}; exit={check.get('returncode', 'not applicable')}; {check.get('reason') or check.get('summary', 'check did not pass')}")
    if value["drift"]["stale"]:
        lines.extend(["Affected evidence     " + (", ".join(value["drift"]["changed_files"][:10]) or "repository/specification anchor"),
                      "Impact                Affected verification must be revalidated; stored work remains available."])
    lines.extend(f"Blocked               {reason}" for reason in value["completion"]["blockers"])
    lines.append("Next                  " + value["next_action"])
    if value.get("last_check"):
        lines.append("Verification next     Inspect the failed check; revise evidence/hypothesis before retrying.")
    return "\n".join(lines)


def execute(args: argparse.Namespace) -> tuple[dict, int]:
    action = args.action
    if action == "assess":
        specification.specification(args.request)
        return specification.assess(args.request.read_text(encoding="utf-8"), read_json(args.signals) if args.signals else None), 0
    if action == "analyze":
        return specification.analyze(args.spec), 0
    repository = args.repository.resolve(strict=True)
    if action == "list":
        from .repository import identity
        directory = store.state_root() / identity(repository)["id"]
        no_symlinks(directory)
        items = []
        if directory.is_dir():
            for path in sorted(directory.glob("*/state.json")):
                state = store.load(path)
                items.append({"id": state["id"], "status": state["status"], "revision": state["revision"]})
        return {"tasks": items, "state_created": False}, 0
    path = store.task_path(repository, args.id)
    if action == "init":
        state = engine.create(args.id, repository, args.spec, read_json(args.models))
        context.resume(state, repository)  # Reject an unusably large initial packet before publishing state.
        state = store.save(path, state, None)
    elif action == "recover":
        state = store.recover(path, args.revision)
        engine.refresh(state)
        packet = context.resume(state, repository)
        packet["recovery_note"] = "Previous generation restored explicitly; revalidate and inspect uncertain partial work."
        return packet, 0
    else:
        state = store.load(path)
        require(state["anchor"]["repository"]["root"] == str(repository), "Task belongs to a different repository.")
        if action in {"status", "resume"}:
            packet = context.resume(state, repository, getattr(args, "task", None))
            return packet, 2 if packet["drift"]["stale"] else 0
        require(state["revision"] == args.revision, "State revision changed; reload it before mutating.", "WORK_STATE_STALE")
        require(state["status"] != "ARCHIVED" or action == "recover", "Archived tasks are read-only.", "WORK_STATE_ARCHIVED")
        def mutate(current):
            require(current["status"] != "ARCHIVED", "Archived tasks are read-only.", "WORK_STATE_ARCHIVED")
            if action == "start":
                return engine.start(current, repository, args.task)
            if action == "implement":
                return engine.implement(current, repository, args.task, args.files)
            if action == "check":
                return engine.check(current, repository, args.task, args.check, args.hypothesis)
            if action == "review":
                return engine.review(current, repository, args.target, args.result, args.summary, args.observer)
            if action == "checkpoint":
                return engine.checkpoint(current, repository)
            if action == "revalidate":
                return engine.revalidate(current, repository, args.reason)
            if action == "reconcile":
                return engine.reconcile(current, repository, args.task, args.outcome, args.reason)
            if action == "replan":
                return engine.replan(current, repository, args.spec, read_json(args.models), args.reason, args.scope_authorization)
            if action == "complete":
                return engine.finish(current, repository)
            if action == "archive":
                current["status"] = "ARCHIVED"
                engine.event(current, "archived", reason=args.reason[:500])
            return None
        state, result = store.update(path, args.revision, mutate)
        packet = context.resume(state, repository)
        if action in {"check", "review"} and result and result.get("result") != "PASS":
            packet["last_check"] = result
            return packet, 1
        if action == "checkpoint" and result and any(v != "PASS" for v in result.values()):
            return packet, 1
        return packet, 0
    return context.resume(state, repository), 0


def main() -> int:
    args = parser().parse_args()
    try:
        result, status = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else human(result))
        return status
    except EngineeringError as exc:
        result = {"status": "BLOCKED", "code": exc.code, "message": str(exc), "next": exc.next_step}
        print(json.dumps(result, indent=2) if args.format == "json" else f"ERROR {exc.code}: {exc}\nNext: {exc.next_step}", file=sys.stderr)
        return 2
