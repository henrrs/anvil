"""Deterministic protocol replay for offline evals; never presented as model execution."""
from __future__ import annotations
import json
import pathlib
import shutil
import subprocess
import sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from engineering import context, engine, repository, store

def models(name="ingestion"):
    return json.loads((ROOT / "evals/engineering" / name / "models.json").read_text())


def prepare(base: pathlib.Path, name="ingestion"):
    fixture = ROOT / "evals/engineering" / name
    project = base / "project"
    shutil.copytree(fixture / "fixture", project)
    shutil.copy2(fixture / "specification.md", project / "specification.md")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "fixture baseline"], check=True)
    return project


def implement_unit(state, project, name, task_id, *, start=True):
    if start:
        engine.start(state, project, task_id)
    task = engine.tasks(state)[task_id]
    fixture = ROOT / "evals/engineering" / name
    for path in task["paths"]:
        if path != "acceptance.py":
            shutil.copy2(fixture / "solution" / path, project / path)
    engine.implement(state, project, task_id, task["paths"])
    for check in task["checks"]:
        result = engine.check(state, project, task_id, check["id"])
        if result["result"] != "PASS":
            raise AssertionError(f"{name}/{task_id} acceptance failed: {result}")
    milestone_tasks = [item for item in engine.tasks(state).values() if item["milestone"] == task["milestone"]]
    if milestone_tasks and all(item["status"] == "VERIFIED" for item in milestone_tasks):
        engine.checkpoint(state, project, milestone_id=task["milestone"])
    return state


def replay(base: pathlib.Path, name="ingestion", interrupt=True, observations=None):
    project = prepare(base, name)
    state = engine.create("eval", project, project / "specification.md", models(name))
    path = store.task_path(project, "eval")
    state = store.save(path, state, None)
    task_ids = list(engine.tasks(state))
    for number, task_id in enumerate(task_ids):
        if interrupt and number == 1:
            engine.start(state, project, task_id)
            task = engine.tasks(state)[task_id]
            first = next(p for p in task["paths"] if p != "acceptance.py")
            shutil.copy2(ROOT / "evals/engineering" / name / "solution" / first, project / first)
            state = store.save(path, state, state["revision"])
            # Discard all in-memory task/history objects: only structured state survives.
            del state
            state = store.load(path)
            snapshot = {p.name: repository.digest(p) for p in project.glob("*.py")}
            packet = context.resume(state, project)
            if observations is not None:
                observations.append({"resume_packet_bytes": len(json.dumps(packet).encode()),
                                     "current_milestone": packet["current_milestone"]["id"],
                                     "verified_tasks_preserved": len(packet["completed_tasks"]),
                                     "state_stale_detected": packet["drift"]["stale"]})
            assert packet["current_task"]["id"] == task_id and packet["completed_tasks"] == task_ids[:1]
            assert packet["status"] == "WORK_STATE_STALE" and not packet["completion"]["ready"]
            assert snapshot == {p.name: repository.digest(p) for p in project.glob("*.py")}
            engine.reconcile(state, project, task_id, "PENDING", "Inspected the partial source copy; no external effects occurred")
        state = implement_unit(state, project, name, task_id)
        state = store.save(path, state, state["revision"])
    for decision in state["models"]["architecture"]["decisions"]:
        if decision.get("needs_review"):
            engine.review(state, project, decision["id"], "PASS", "Observed module dependencies and acceptance behavior retain the decision after interruption", "model")
    engine.finish(state, project)
    state = store.save(path, state, state["revision"])
    return state, project, path
