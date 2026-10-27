#!/usr/bin/env python3
"""Offline protocol replays or explicitly requested, isolated OpenCode model evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from unittest import mock

from harness import ROOT, models, prepare, replay
sys.path.insert(0, str(ROOT / "scripts"))
from engineering import engine, invariants

PROFILES = {
    "base": "Use the direct engineering workflow; do not create structured task models.",
    "work": "Maintain explicit work progress only; requirements/architecture continuity is an ablation.",
    "work-architecture": "Maintain work and architecture models; requirement tracking is an ablation.",
    "full": "Use the full progressive engineering workflow when complexity warrants it.",
    "full-no-system-design": "Use structured engineering state but do not load the system-design skill.",
    "full-no-deep-spark": "Use structured engineering state but do not load deep Spark references.",
}


def replay_run(name: str, repeats: int) -> dict:
    runs = []
    for number in range(repeats):
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix=f"anvil-eval-{name}-") as directory:
            base = pathlib.Path(directory)
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(base / "state"), "XDG_DATA_HOME": str(base / "data"),
                    "ANVIL_ENGINEERING": "auto", "PYTHONPATH": str(ROOT / "tests/fixtures/network-denied")}):
                observations = []
                state, project, _ = replay(base, name, observations=observations)
                regressions = {}
                for invariant in models(name)["architecture"]["invariants"]:
                    if invariant["kind"] == "forbidden_imports":
                        target = project / invariant["paths"][0]
                        original = target.read_text()
                        target.write_text(original + "\nimport " + invariant["forbidden"][0] + "\n")
                        regressions[invariant["id"]] = invariants.evaluate(project, invariant)["result"] == "FAIL"
                        target.write_text(original)
                runs.append({"run": number + 1, "task_success": state["status"] == "COMPLETE",
                             "requirements": engine.coverage(state), "architecture": engine.conformance(state),
                             "injected_boundary_violations_detected": regressions,
                             "interruption_and_compaction": "PASS", "duplicate_resume_execution": False,
                             "counters": state["counters"], "latency_seconds": round(time.monotonic() - started, 3),
                             "milestones_created": len(state["models"]["work"]["milestones"]),
                             "tasks_completed": sum(t["status"] == "VERIFIED" for t in state["models"]["work"]["tasks"]),
                             "replans": state["counters"].get("replanned", 0),
                             "verification_failures": len(state["failures"]),
                             "final_architecture_violations": sum(r != "PASS" for r in engine.conformance(state).values()),
                             "resume_observations": observations, "unnecessary_exploration": None,
                             "tool_calls": None, "model_tokens": None, "unsupported_claims": None,
                             "semantic_design_quality": "NOT_MEASURED"})
    return {"fixture": name, "method": "deterministic protocol replay using explicit reference implementations; not an LLM coding run", "runs": runs}


def stream_metrics(process, timeout: int) -> dict:
    """Parse bounded event bytes in memory; never retain a model transcript/reasoning log."""
    tool_calls = 0
    usage = []
    recognized = False
    digest = hashlib.sha256()
    buffer = b""
    total = 0
    started = time.monotonic()
    reason = None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    def consume(raw):
        nonlocal tool_calls, recognized
        try:
            event = json.loads(raw)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        if event.get("type") in {"tool_use", "tool-call"}:
            tool_calls += 1
            recognized = True
        part = event.get("part", {})
        if isinstance(part, dict) and isinstance(part.get("tokens"), dict):
            # Only numeric usage counters are observable telemetry.
            usage.append({k: v for k, v in part["tokens"].items() if isinstance(v, (int, float))})
    try:
        while selector.get_map():
            if time.monotonic() - started > timeout or total > 20 * 1024 * 1024:
                reason = "TIME_OR_OUTPUT_LIMIT"
                break
            for key, _ in selector.select(.1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    break
                total += len(chunk)
                digest.update(chunk)
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    consume(line)
                if len(buffer) > 1024 * 1024:
                    buffer = b""  # Ignore an overlong event, never persist it.
        if buffer:
            consume(buffer)
        if not reason:
            try:
                process.wait(timeout=max(.1, timeout - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                reason = "TIME_OR_OUTPUT_LIMIT"
    finally:
        selector.close()
        if process.poll() is None or reason:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                pass
        process.stdout.close()
    return {"tool_calls": tool_calls if recognized else None, "token_usage": usage or None,
            "event_stream_sha256": digest.hexdigest(), "private_reasoning_logged": False, "limit": reason}


def live_run(args, name: str, number: int) -> dict:
    """No auth state is copied; the caller supplies supported provider environment auth."""
    with tempfile.TemporaryDirectory(prefix="anvil-model-eval-") as directory:
        base = pathlib.Path(directory)
        project = prepare(base, name)
        env = {**os.environ, "HOME": str(base / "home"), "XDG_CONFIG_HOME": str(base / "config"),
               "XDG_DATA_HOME": str(base / "data"), "XDG_STATE_HOME": str(base / "state"),
               "ANVIL_ROOT": str(args.profile_root), "ANVIL_ENGINEERING": "off" if args.profile == "base" else "auto"}
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            pathlib.Path(env[key]).mkdir(parents=True)
        command = ["bash", "-c", 'source "$ANVIL_ROOT/scripts/lib/common.sh"; source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" "" no "$2"',
                   "_", str(base / "config/opencode"), str(args.major)]
        subprocess.run(command, env=env, check=True, capture_output=True, timeout=60)
        prompt = ("Implement specification.md in this clean fixture repository. Read only relevant source. "
                  "Use acceptance.py as an independent behavior check and do not alter it. " + PROFILES[args.profile] +
                  " Preserve ownership and report verification, coverage, unknowns and unfinished work. No external services or source-control publication.")
        argv = [str(args.opencode), "run", "--format", "json", "--agent", "anvil", "--model", args.model, prompt]
        started = time.monotonic()
        process = subprocess.Popen(argv, cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        metrics = stream_metrics(process, args.timeout)
        accepted = subprocess.run([sys.executable, "acceptance.py", "all"], cwd=project, capture_output=True, timeout=30)
        architecture = {i["id"]: invariants.evaluate(project, i)["result"] for i in models(name)["architecture"]["invariants"]}
        return {"run": number, "fixture": name, "profile": args.profile, "model": args.model,
                "runtime": str(args.opencode), "profile_commit": subprocess.check_output(["git", "-C", str(args.profile_root), "rev-parse", "HEAD"], text=True).strip(),
                "acceptance": "PASS" if accepted.returncode == 0 else "FAIL", "architecture": architecture,
                "exit_code": process.returncode, "latency_seconds": round(time.monotonic() - started, 3),
                **metrics, "semantic_review": "REQUIRED; mechanical checks do not prove requirement extraction/design/diagnosis quality"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("replay", "live"), default="replay")
    parser.add_argument("--fixture", choices=("ingestion", "scheduler", "all"), default="all")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="full")
    parser.add_argument("--profile-root", type=pathlib.Path, default=ROOT)
    parser.add_argument("--opencode", type=pathlib.Path)
    parser.add_argument("--model")
    parser.add_argument("--major", type=int, choices=(1, 2), default=1)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be 1–20")
    if args.mode == "live" and (not args.opencode or not args.model):
        parser.error("live evaluations require an explicitly selected --opencode and --model")
    fixtures = ["ingestion", "scheduler"] if args.fixture == "all" else [args.fixture]
    results = ([replay_run(name, args.repeats) for name in fixtures] if args.mode == "replay" else
               [live_run(args, name, n) for name in fixtures for n in range(1, args.repeats + 1)])
    report = {"schema_version": 1, "mode": args.mode, "results": results,
              "limitations": ["Replay measures deterministic continuity/conformance, not model reasoning or coding quality.",
                              "Tool/model token fields are null when unmeasured; no hidden reasoning is retained.",
                              "Live profile ablations are requested protocols; inspect observed skill use before attributing causality."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {args.mode} engineering evaluation: {args.output}")
    if args.mode == "replay":
        return 0 if all(run["task_success"] and all(run["injected_boundary_violations_detected"].values()) for item in results for run in item["runs"]) else 1
    return 0 if all(item["acceptance"] == "PASS" and set(item["architecture"].values()) == {"PASS"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
