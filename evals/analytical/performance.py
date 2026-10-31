"""Reproducible local cost measurements for bounded analytical paths."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from analysis import profiling  # noqa: E402
from analysis.primitives import execute_plan  # noqa: E402


def _write_benchmark(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write("segment,value\n")
        for index in range(10_000):
            stream.write(f"segment-{index % 10},{index % 97}\n")


def _summary(samples: list[float]) -> dict[str, Any]:
    values = sorted(samples)
    return {"median_ms": round(statistics.median(values), 3), "min_ms": round(values[0], 3),
            "max_ms": round(values[-1], 3), "p95_ms": round(values[min(len(values)-1, int((len(values)-1)*0.95))], 3),
            "samples_ms": [round(value, 3) for value in values]}


def _plan(profile: dict[str, Any], depth: str, count: int) -> dict[str, Any]:
    return {"schema_version": 1, "source_sha256": profile["source"]["sha256"], "depth": depth,
            "primary_question": "How do observed values compare?", "questions": [],
            "operations": [{"id": f"sum-{index+1}", "operation": "sum", "column": "value"}
                           for index in range(count)],
            "budgets": {"max_rows": 10_000, "max_groups": 20}}


def benchmark_current(*, repetitions: int = 5) -> dict[str, Any]:
    if not 1 <= repetitions <= 20:
        raise ValueError("repetitions must be between 1 and 20")
    profiles = {depth: [] for depth in ("FAST", "STANDARD", "DEEP")}
    executions = {depth: [] for depth in profiles}
    totals = {depth: [] for depth in profiles}
    profile_cpu = {depth: [] for depth in profiles}
    execution_cpu = {depth: [] for depth in profiles}
    total_cpu = {depth: [] for depth in profiles}
    semantic_samples = {depth: [] for depth in profiles}
    active_depth = "FAST"
    original = profiling.infer_semantic_context

    def timed_inference(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            semantic_samples[active_depth].append((time.perf_counter() - started) * 1000)

    profiling.infer_semantic_context = timed_inference
    try:
        with tempfile.TemporaryDirectory(prefix="anvil-analysis-benchmark-") as temporary:
            source = Path(temporary) / "ten-thousand-rows.csv"
            _write_benchmark(source)
            for depth, count in (("FAST", 4), ("STANDARD", 12), ("DEEP", 20)):
                active_depth = depth
                for _ in range(repetitions):
                    started = time.perf_counter()
                    cpu_started = time.process_time()
                    profile_started = time.perf_counter()
                    profile_cpu_started = time.process_time()
                    profile = profiling.profile_file(source, semantic_depth=depth,
                                                     semantic_focus="numeric" if depth == "FAST" else "general")
                    profile_ms = (time.perf_counter() - profile_started) * 1000
                    profile_cpu_ms = (time.process_time() - profile_cpu_started) * 1000
                    execution_started = time.perf_counter()
                    execution_cpu_started = time.process_time()
                    result = execute_plan(str(source), _plan(profile, depth, count), profile=profile)
                    execution_ms = (time.perf_counter() - execution_started) * 1000
                    execution_cpu_ms = (time.process_time() - execution_cpu_started) * 1000
                    total_ms = (time.perf_counter() - started) * 1000
                    total_cpu_ms = (time.process_time() - cpu_started) * 1000
                    if result["profile"]["analyzed_rows"] != 10_000 or len(result["operations"]) != count:
                        raise RuntimeError(f"{depth} benchmark did not process the expected bounded work")
                    profiles[depth].append(profile_ms)
                    executions[depth].append(execution_ms)
                    totals[depth].append(total_ms)
                    profile_cpu[depth].append(profile_cpu_ms)
                    execution_cpu[depth].append(execution_cpu_ms)
                    total_cpu[depth].append(total_cpu_ms)
    finally:
        profiling.infer_semantic_context = original
    return {"fixture": {"rows": 10_000, "columns": 2, "generator": "segment,value; i%10 and i%97"},
            "repetitions": repetitions, "model_calls": 0, "tool_calls": 0,
            "tokens": {"input": 0, "output": 0},
            "depths": {depth: {"operations": count, "profile": _summary(profiles[depth]),
                              "execute_plan_including_second_scan": _summary(executions[depth]),
                              "total": _summary(totals[depth]),
                              "cpu_ms": {"profile_median": round(statistics.median(profile_cpu[depth]), 3),
                                         "execution_median": round(statistics.median(execution_cpu[depth]), 3),
                                         "total_median": round(statistics.median(total_cpu[depth]), 3)}}
                       for depth, count in (("FAST", 4), ("STANDARD", 12), ("DEEP", 20))},
            "profile_stage_attribution": {"semantic_inference_median_ms": round(statistics.median(semantic_samples["FAST"]), 3),
                "semantic_inference_median_ms_by_depth": {depth: round(statistics.median(samples), 3)
                                                           for depth, samples in semantic_samples.items()},
                "semantic_inference_share_of_FAST_profile": round(statistics.median(semantic_samples["FAST"]) / max(statistics.median(profiles["FAST"]), 0.001), 4),
                "note": "Attribution is measured inside profiling; it is not an ablation or proof all measured work is necessary."},
            "fast_path_investigation": {"classification": "UNKNOWN",
                "evidence": "Profile and execution stages are timed separately and semantic inference is attributed within profiling. No semantic safeguard was disabled.",
                "action": "Retain safeguards; use the stage evidence for a controlled optimization experiment."}}


_LEGACY_RUNNER = '''
import json, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from analysis.profiling import profile_file
from analysis.primitives import execute_plan
source=Path(sys.argv[2]); repetitions=int(sys.argv[3]); output={}
for depth,count in (("FAST",4),("STANDARD",12),("DEEP",20)):
    ps=[]; es=[]; ts=[]
    for _ in range(repetitions):
        started=time.perf_counter(); pstarted=time.perf_counter(); profile=profile_file(source)
        ps.append((time.perf_counter()-pstarted)*1000)
        plan={"schema_version":1,"source_sha256":profile["source"]["sha256"],"depth":depth,
              "primary_question":"How do observed values compare?","questions":[],
              "operations":[{"id":f"sum-{i+1}","operation":"sum","column":"value"} for i in range(count)],
              "budgets":{"max_rows":10000,"max_groups":20}}
        estarted=time.perf_counter()
        try: result=execute_plan(str(source),plan,profile=profile)
        except TypeError: result=execute_plan(str(source),plan)
        es.append((time.perf_counter()-estarted)*1000); ts.append((time.perf_counter()-started)*1000)
        if len(result.get("operations",[])) != count: raise RuntimeError("operation count mismatch")
    output[depth]={"operations":count,"profile_median_ms":round(statistics.median(ps),3),
                   "execution_median_ms":round(statistics.median(es),3),"total_median_ms":round(statistics.median(ts),3),
                   "samples_ms":[round(x,3) for x in ts]}
print(json.dumps(output))
'''


def benchmark_historical_2_13(*, repetitions: int = 5) -> dict[str, Any]:
    """Run committed HEAD in a temporary archive; no worktree or index is changed."""
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                  capture_output=True, text=True, timeout=5).stdout.strip()
        version = subprocess.run(["git", "show", "HEAD:VERSION"], cwd=ROOT, check=True,
                                 capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"status": "BASELINE_UNAVAILABLE", "reason": "Could not identify a committed historical revision."}
    if not version.startswith("2.13."):
        return {"status": "BASELINE_UNAVAILABLE", "reason": f"HEAD is {version}, not a 2.13 implementation.", "revision": revision}
    try:
        with tempfile.TemporaryDirectory(prefix="anvil-2.13-eval-") as temporary:
            old_root = Path(temporary) / "repository"
            old_root.mkdir(mode=0o700)
            archive = subprocess.run(["git", "archive", "--format=tar", "HEAD", "scripts/analysis"], cwd=ROOT,
                                     check=True, capture_output=True, timeout=10).stdout
            with tarfile.open(fileobj=BytesIO(archive), mode="r:") as tar:
                # This tar is produced immediately from this repository's own
                # trusted Git object store; avoid a Python 3.12-only API.
                tar.extractall(old_root)
            source = Path(temporary) / "ten-thousand-rows.csv"
            _write_benchmark(source)
            completed = subprocess.run([sys.executable, "-c", _LEGACY_RUNNER, str(old_root), str(source), str(repetitions)],
                                       cwd=old_root, check=True, capture_output=True, text=True, timeout=120, close_fds=True)
            return {"status": "COMPLETE", "version": version, "revision": revision,
                    "fixture": {"rows": 10_000, "columns": 2}, "repetitions": repetitions,
                    "depths": json.loads(completed.stdout)}
    except (OSError, subprocess.SubprocessError, tarfile.TarError, json.JSONDecodeError) as exc:
        return {"status": "BASELINE_UNAVAILABLE", "reason": f"Isolated historical run failed ({type(exc).__name__}).",
                "version": version, "revision": revision}
